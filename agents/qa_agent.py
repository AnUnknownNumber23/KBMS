"""
问答 Agent — 混合检索 (Vector + Graph) + 多跳推理 + 答案生成

核心能力:
  1. 意图识别 & 查询改写
  2. 向量检索 (语义相似度)
  3. 图谱检索 (Cypher 查询 / 子图遍历)
  4. 混合排序 & 重排序
  5. 基于检索结果的答案生成（带引用来源）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config import settings


class QueryIntent(str, Enum):
    FACTOID = "factoid"           # 事实型问题
    ANALYTICAL = "analytical"     # 分析型问题
    COMPARATIVE = "comparative"   # 对比型问题
    PROCEDURAL = "procedural"     # 流程型问题
    EXPLORATORY = "exploratory"   # 探索型问题


@dataclass
class RetrievedContext:
    content: str
    source: str
    score: float
    retrieval_type: str  # "vector" | "graph" | "hybrid"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class QAResult:
    question: str
    answer: str
    contexts: list[RetrievedContext]
    intent: QueryIntent
    confidence: float
    reasoning_steps: list[str] = field(default_factory=list)


INTENT_PROMPT = """\
你是一个查询意图分类器。根据用户问题，返回意图类别（只返回类别名）：
- factoid: 事实型（谁/什么/哪里/何时）
- analytical: 分析型（为什么/怎么理解）
- comparative: 对比型（A和B有什么区别）
- procedural: 流程型（怎么做/步骤）
- exploratory: 探索型（有哪些/概述）
"""

QUERY_REWRITE_PROMPT = """\
你是一个查询改写专家。将用户问题改写为更适合检索的形式。
要求：
1. 提取核心实体和关键词
2. 生成 1-3 个检索查询
3. 返回 JSON: {"queries": ["查询1", "查询2"], "entities": ["实体1"], "keywords": ["关键词1"]}
"""

CYPHER_GENERATION_PROMPT = """\
你是一个 Neo4j Cypher 查询生成专家。根据用户问题和提取的实体，生成 Cypher 查询。

知识图谱 Schema:
- 节点标签: Person, Organization, Technology, Product, Concept, Location
- 关系类型: belongs_to, works_at, located_in, developed_by, related_to, part_of, uses, depends_on
- 节点属性: name, type, description, created_at, version

生成 1-2 条 Cypher 查询，返回 JSON: {"queries": ["MATCH ...", "MATCH ..."]}
只返回 JSON，不要其他文字。
"""

ANSWER_PROMPT = """\
你是一个专业的企业知识问答助手。根据检索到的上下文信息回答用户问题。

要求：
1. 答案必须基于提供的上下文，不要编造
2. 如果上下文信息不足，明确告知用户
3. 引用来源直接用编号（如 [来源 1]），对应上下文提供的编号
4. 如果涉及多个信息源，综合分析后给出结论
5. 保持专业、准确、简洁
"""


class QAAgent:
    """
    问答 Agent

    工作流:
      query → intent_classify → rewrite → parallel_retrieve → rerank → generate_answer
    """

    def __init__(
        self,
        vector_store: Any = None,
        knowledge_graph: Any = None,
    ) -> None:
        self.llm = ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            temperature=0,
        )
        self.vector_store = vector_store
        self.knowledge_graph = knowledge_graph

    # ── public API ───────────────────────────────────────────

    async def answer(self, question: str) -> QAResult:
        """完整问答流程"""
        intent = await self._classify_intent(question)
        rewritten = await self._rewrite_query(question)

        vector_contexts = await self._vector_retrieve(rewritten, original_question=question)
        graph_contexts = await self._graph_retrieve(question, rewritten)

        top_contexts = self._rrf_fusion(vector_contexts, graph_contexts, k=60, top_n=8)

        answer_text, reasoning = await self._generate_answer(question, top_contexts, intent)

        return QAResult(
            question=question,
            answer=answer_text,
            contexts=top_contexts,
            intent=intent,
            confidence=self._calc_confidence(top_contexts),
            reasoning_steps=reasoning,
        )

    # ── intent classification ────────────────────────────────

    async def _classify_intent(self, question: str) -> QueryIntent:
        messages = [
            SystemMessage(content=INTENT_PROMPT),
            HumanMessage(content=question),
        ]
        resp = await self.llm.ainvoke(messages)
        raw = resp.content.strip().lower()
        for intent in QueryIntent:
            if intent.value in raw:
                return intent
        return QueryIntent.FACTOID

    # ── query rewriting ──────────────────────────────────────

    async def _rewrite_query(self, question: str) -> dict:
        import json
        messages = [
            SystemMessage(content=QUERY_REWRITE_PROMPT),
            HumanMessage(content=question),
        ]
        resp = await self.llm.ainvoke(messages)
        try:
            cleaned = resp.content.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
            return json.loads(cleaned)
        except (json.JSONDecodeError, IndexError):
            return {"queries": [question], "entities": [], "keywords": []}

    # ── vector retrieval ─────────────────────────────────────

    async def _vector_retrieve(self, rewritten: dict, original_question: str = "") -> list[RetrievedContext]:
        if not self.vector_store:
            return []

        queries = rewritten.get("queries", [])
        # 保底: LLM 偶尔不返回 queries，用关键词或原问题顶替
        if not queries:
            queries = rewritten.get("keywords", [])
        if not queries:
            queries = [original_question]

        contexts: list[RetrievedContext] = []
        for query in queries:
            results = await self.vector_store.search(query, top_k=5)
            for doc, score in results:
                contexts.append(RetrievedContext(
                    content=doc.get("content", ""),
                    source=doc.get("source", "vector_store"),
                    score=score,
                    retrieval_type="vector",
                    metadata=doc.get("metadata", {}),
                ))
        return contexts

    # ── graph retrieval ──────────────────────────────────────

    async def _graph_retrieve(self, question: str, rewritten: dict) -> list[RetrievedContext]:
        if not self.knowledge_graph:
            return []

        import json
        entities = rewritten.get("entities", [])
        messages = [
            SystemMessage(content=CYPHER_GENERATION_PROMPT),
            HumanMessage(content=f"问题: {question}\n实体: {entities}"),
        ]
        resp = await self.llm.ainvoke(messages)
        try:
            cleaned = resp.content.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
            cypher_data = json.loads(cleaned)
        except (json.JSONDecodeError, IndexError):
            cypher_data = {"queries": []}

        contexts: list[RetrievedContext] = []
        for cypher in cypher_data.get("queries", []):
            try:
                records = await self.knowledge_graph.execute_cypher(cypher)
                for record in records:
                    # LLM 生成的 Cypher 查询是针对性检索，质量较高
                    contexts.append(RetrievedContext(
                        content=str(record),
                        source="knowledge_graph",
                        score=0.7,
                        retrieval_type="graph",
                        metadata={"cypher": cypher},
                    ))
            except Exception:
                continue

        # 保底: 直接搜实体邻居，分数按跳数递减
        all_entities = entities + rewritten.get("keywords", [])
        seen_names: set[str] = set()
        for name in all_entities:
            if name in seen_names:
                continue
            seen_names.add(name)
            try:
                # 单跳邻居 → 分数高，多跳 → 分数低
                for hops, base_score in [(1, 0.6), (2, 0.4)]:
                    neighbors = await self.knowledge_graph.get_neighbors(name, hops=hops)
                    for row in neighbors:
                        if row.get("target"):
                            rel_count = len(row.get("relations", []))
                            contexts.append(RetrievedContext(
                                content=f"{name} --[{', '.join(row.get('relations', []))}]--> {row['target']} (类型: {row.get('target_type', '')})",
                                source="knowledge_graph",
                                score=base_score + rel_count * 0.02,  # 多关系稍加分
                                retrieval_type="graph",
                                metadata={"entity": name, "neighbor": row["target"], "hops": hops},
                            ))
            except Exception:
                continue
        return contexts

    # ── hybrid reranking ─────────────────────────────────────

    @staticmethod
    def _rrf_fusion(
        vector_contexts: list[RetrievedContext],
        graph_contexts: list[RetrievedContext],
        k: int = 60,
        top_n: int = 8,
    ) -> list[RetrievedContext]:
        """
        RRF (Reciprocal Rank Fusion) 混合融合策略

        不比较原始分数（向量是余弦相似度，图谱是规则打分，尺度不可比），
        只看各来源内部的排名位置。Google 和 Elasticsearch 都用的这招。

        RRF_score(d) = 1/(k + rank_vector) + 1/(k + rank_graph)
        未在某来源中出现 → 该来源贡献为 0
        """
        # 按各自分数降序排
        vec_sorted = sorted(vector_contexts, key=lambda c: c.score, reverse=True)
        gr_sorted = sorted(graph_contexts, key=lambda c: c.score, reverse=True)

        # 计算 RRF 分数
        rrf_scores: dict[int, float] = {}
        for rank, ctx in enumerate(vec_sorted, start=1):
            rrf_scores[id(ctx)] = rrf_scores.get(id(ctx), 0) + 1.0 / (k + rank)
        for rank, ctx in enumerate(gr_sorted, start=1):
            rrf_scores[id(ctx)] = rrf_scores.get(id(ctx), 0) + 1.0 / (k + rank)

        # 更新分数为 RRF 分数，排重
        seen: set[str] = set()
        unique: list[RetrievedContext] = []
        for ctx in vec_sorted + gr_sorted:
            key = ctx.content[:100]
            if key not in seen:
                seen.add(key)
                ctx.score = rrf_scores.get(id(ctx), 0)
                unique.append(ctx)

        unique.sort(key=lambda c: c.score, reverse=True)
        return unique[:top_n]

    # ── answer generation ────────────────────────────────────

    async def _generate_answer(
        self,
        question: str,
        contexts: list[RetrievedContext],
        intent: QueryIntent,
    ) -> tuple[str, list[str]]:
        context_text = "\n\n".join(
            f"[来源 {i+1}: {c.source} | 类型: {c.retrieval_type} | 分数: {c.score:.2f}]\n{c.content}"
            for i, c in enumerate(contexts)
        )
        reasoning_steps = [
            f"识别问题意图: {intent.value}",
            f"检索到 {len(contexts)} 条相关上下文",
            f"向量检索: {sum(1 for c in contexts if c.retrieval_type == 'vector')} 条",
            f"图谱检索: {sum(1 for c in contexts if c.retrieval_type == 'graph')} 条",
        ]

        messages = [
            SystemMessage(content=ANSWER_PROMPT),
            HumanMessage(content=f"上下文信息:\n{context_text}\n\n用户问题: {question}"),
        ]
        resp = await self.llm.ainvoke(messages)
        reasoning_steps.append("答案生成完成")
        return resp.content, reasoning_steps

    @staticmethod
    def _calc_confidence(contexts: list[RetrievedContext]) -> float:
        if not contexts:
            return 0.0
        avg_score = sum(c.score for c in contexts) / len(contexts)
        return min(avg_score, 1.0)

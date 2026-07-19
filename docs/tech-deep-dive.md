# 核心代码逐行讲解

> 本文档深入解读项目中最关键的代码模块，帮助你在面试中做到"知其然且知其所以然"。

---

## 1. LangGraph 编排引擎 — graph.py

这是整个系统的"大脑"，决定了4个Agent怎么协作。

### 文档入库流水线

```python
def _build_ingest_graph(doc_parser, extractor, vector_store, knowledge_graph):

    # 节点1: 解析文档
    async def parse_documents(state: dict) -> dict:
        file_paths = state.get("file_paths", [])     # 从状态中取出文件路径
        chunks = await doc_parser.parse_batch(file_paths)  # 调用文档解析Agent
        return {"chunks": chunks}                     # 返回结果写入状态

    # 节点2: 抽取知识
    async def extract_knowledge(state: dict) -> dict:
        chunks = state.get("chunks", [])              # 从状态中取出上一步的结果
        extractions = await extractor.extract(chunks)  # 调用知识抽取Agent
        return {"extractions": extractions}

    # 节点3: 存入向量库 (和节点4并行执行)
    async def store_vectors(state: dict) -> dict:
        chunks = state.get("chunks", [])
        count = await vector_store.add_chunks(chunks)
        return {"vectors_stored": count}

    # 节点4: 存入知识图谱 (和节点3并行执行)
    async def store_graph(state: dict) -> dict:
        extractions = state.get("extractions", [])
        for ext in extractions:
            for ent in ext.entities:
                await knowledge_graph.upsert_entity(ent)
            for rel in ext.relations:
                await knowledge_graph.add_relation(rel)
        return {"entities_stored": entity_count}

    # 构建有向图
    graph = StateGraph(dict)
    graph.add_node("parse", parse_documents)
    graph.add_node("extract", extract_knowledge)
    graph.add_node("store_vectors", store_vectors)
    graph.add_node("store_graph", store_graph)

    # 定义边 (数据流向)
    graph.set_entry_point("parse")          # 入口: 解析
    graph.add_edge("parse", "extract")       # 解析 → 抽取 (串行)
    graph.add_edge("extract", "store_vectors")  # 抽取 → 向量化 (并行分支1)
    graph.add_edge("extract", "store_graph")    # 抽取 → 图谱化 (并行分支2)
    graph.add_edge("store_vectors", END)
    graph.add_edge("store_graph", END)

    return graph.compile()  # 编译为可执行的工作流
```

**面试时怎么说**: "我用LangGraph的StateGraph将4个Agent编排成有向图。每个Agent是图中的一个节点，节点间通过共享状态传递数据。解析和抽取是串行的，因为抽取依赖解析结果；但向量化和图谱化是并行的，因为它们互不依赖，这样可以减少总耗时。"

---

## 2. GraphRAG 混合检索 — graph_rag.py

这是本项目最有技术深度的模块。

### 核心检索流程

```python
async def retrieve(self, query: str, top_k: int = 10) -> list[GraphRAGContext]:
    # 第一步: 向量语义检索 — 找语义相关的文档块
    vector_results = await self._vector_search(query, top_k=top_k)

    # 第二步: 实体链接 — 从query中识别实体名称
    # 比如 "张三在哪工作" → 提取出 ["张三"]
    entities = await self._entity_linking(query)

    # 第三步: 子图检索 — 从实体出发N跳遍历
    # "张三" → works_at → "腾讯" → developed → "微信"
    subgraph_results = await self._subgraph_search(entities)

    # 第四步: 路径检索 — 查找实体间最短路径
    # 提供推理链: 张三 → works_at → 腾讯 → developed → 微信
    path_results = await self._path_search(entities)

    # 第五步: 社区摘要 — 对子图信息生成高层概要
    community_ctx = await self._community_summary(subgraph_results)

    # 第六步: 交叉重排序 — 不同来源施加不同权重
    all_results = vector_results + subgraph_results + path_results + [community_ctx]
    return self._cross_rerank(all_results, query)[:top_k]
```

### 多跳子图检索的 Cypher 查询

```python
async def _subgraph_search(self, entities, hops=2):
    for entity_name in entities:
        # 从指定实体出发，遍历2跳内的所有关联节点
        cypher = f"""
        MATCH path = (start:Entity {{name: $name}})-[*1..{hops}]-(neighbor)
        RETURN
            start.name AS source,
            [r IN relationships(path) | type(r)] AS relations,
            neighbor.name AS target
        LIMIT 50
        """
        # 这条Cypher的含义:
        # 1. 找到名为 $name 的实体节点
        # 2. 从它出发，沿着任意关系走1到2步
        # 3. 返回路径上的所有节点和关系类型
```

**面试时怎么说**: "我在Neo4j中用可变长度路径匹配`[*1..2]`实现多跳遍历，最多2跳可以覆盖大部分有意义的关系链。超过2跳的关系通常太远，引入噪音。同时我设了LIMIT 50防止子图过大。"

---

## 3. CDC 增量处理器 — cdc_processor.py

### 差量计算

```python
@staticmethod
def compute_diff(before: str, after: str) -> dict:
    before_lines = before.splitlines()
    after_lines = after.splitlines()

    before_set = set(before_lines)
    after_set = set(after_lines)

    added = after_set - before_set      # 新增的行
    removed = before_set - after_set    # 删除的行

    # 变化比例: 衡量这次修改有多大
    change_ratio = len(added | removed) / max(len(before_lines) + len(after_lines), 1)

    return {
        "added_lines": list(added),
        "removed_lines": list(removed),
        "change_ratio": round(change_ratio, 4),
        "is_major_change": change_ratio > 0.3,  # 超过30%视为大改
    }
```

**为什么要区分大改和小改？**
- 大改 (>30% 内容变化): 直接删除旧数据，全量重新处理这个文档
- 小改 (<30%): 只处理新增/修改的chunk，效率更高

### 版本管理

```python
def bump_version(self, resource_path: str) -> int:
    current = self._version_map.get(resource_path, 0)
    new_version = current + 1
    self._version_map[resource_path] = new_version
    return new_version
```

每个资源(文档/实体)都有独立的版本号，每次更新+1。对应到Neo4j中:
```cypher
MERGE (e:Entity {name: $name})
ON MATCH SET e.version = $version, e.updated_at = $now
```

---

## 4. 知识抽取Agent — knowledge_extract_agent.py

### LLM结构化抽取

```python
EXTRACTION_SYSTEM_PROMPT = """
你是一个专业的知识抽取引擎。给定一段文本，请提取其中的：
1. 实体 (entities)：人名、组织、产品、技术、概念等
2. 关系 (relations)：用三元组 (头实体, 关系, 尾实体) 表示

请严格按照以下 JSON 格式返回...
"""
```

**为什么用 LLM 而不是传统 NER 模型？**
1. 传统NER只能识别预定义的实体类型，LLM可以识别任意类型
2. 传统RE模型需要大量标注数据训练，LLM零样本就能做
3. LLM可以理解上下文，抽取隐含的关系

**LLM抽取的挑战与解决方案**:
- JSON格式不稳定 → 用代码清理markdown标记，try-except兜底
- 跨chunk去重 → 维护 seen_entities/seen_relations 集合

### 去重逻辑

```python
@staticmethod
def _deduplicate(results):
    seen_entities = {}   # key: "实体名::类型"
    seen_relations = set()  # key: (head, relation, tail)

    for result in results:
        # 同名同类型的实体只保留第一个
        unique_entities = []
        for ent in result.entities:
            key = f"{ent.name}::{ent.type}"
            if key not in seen_entities:
                seen_entities[key] = ent
                unique_entities.append(ent)
        result.entities = unique_entities
```

**面试时怎么说**: "跨chunk的实体去重是必须的，因为同一个实体可能在多个chunk中被提取出来。我用`名称+类型`作为唯一键做去重。更高级的做法是实体消歧(Entity Resolution)，比如'微软'和'Microsoft'应该合并，这可以作为后续优化点。"

---

## 5. 问答Agent的意图识别

```python
class QueryIntent(str, Enum):
    FACTOID = "factoid"          # "谁发明了Python？"
    ANALYTICAL = "analytical"    # "为什么React比Vue流行？"
    COMPARATIVE = "comparative"  # "Java和Go有什么区别？"
    PROCEDURAL = "procedural"    # "怎么部署Docker？"
    EXPLORATORY = "exploratory"  # "机器学习有哪些方法？"
```

**为什么要做意图识别？** 不同类型的问题，最佳检索策略不同:
- 事实型 → 精确实体匹配更重要
- 分析型 → 需要更多上下文
- 对比型 → 需要同时检索两个实体的信息
- 流程型 → 需要按步骤组织信息

---

## 6. Java版: Spring AI 集成

```java
@Component
public class QAAgent {
    private final ChatClient chatClient;  // Spring AI 提供的LLM客户端

    // 通过构造器注入 — Spring Boot 自动配置
    public QAAgent(ChatClient.Builder chatClientBuilder, ...) {
        this.chatClient = chatClientBuilder.build();
    }

    private String generateAnswer(String question, String contextText) {
        // Spring AI 的 Prompt API — 比直接拼字符串更安全
        return chatClient.prompt(new Prompt(List.of(
            new SystemMessage(ANSWER_PROMPT),
            new UserMessage("上下文:\n" + contextText + "\n\n问题: " + question)
        ))).call().content();
    }
}
```

**与Python版的对比**:
- Python用 `langchain_openai.ChatOpenAI` + `ainvoke` (异步)
- Java用 `spring-ai ChatClient` + `call` (同步，可用Virtual Thread)
- 两者的Prompt结构完全一致，只是API风格不同

---

## 7. Go版: 并发文档解析

```go
func (a *DocParserAgent) ParseBatch(filePaths []string) ([]DocumentChunk, error) {
    type result struct {
        chunks []DocumentChunk
        err    error
    }

    // 为每个文件启动一个 goroutine 并行解析
    ch := make(chan result, len(filePaths))
    for _, fp := range filePaths {
        go func(path string) {
            chunks, err := a.Parse(path)
            ch <- result{chunks: chunks, err: err}
        }(fp)
    }

    // 收集所有结果
    var allChunks []DocumentChunk
    for range filePaths {
        res := <-ch
        if res.err != nil {
            continue  // 单个文件失败不影响整体
        }
        allChunks = append(allChunks, res.chunks...)
    }
    return allChunks, nil
}
```

**Go版的独特优势**:
- goroutine 创建成本极低(~2KB栈)，可以为每个文件启动一个
- channel 天然支持生产者-消费者模式
- 单个文件解析失败不影响其他文件(容错)
- Python要达到同样效果需要asyncio或multiprocessing，Java需要CompletableFuture

---

## 总结: 面试中如何展示技术深度

1. **能画架构图**: 白板上画出4Agent+3流水线的架构
2. **能讲设计决策**: 每个技术选型都有理由
3. **能写关键代码**: Cypher查询、LangGraph编排、CDC差量计算
4. **能说优化思路**: 知道当前方案的不足和改进方向
5. **能做技术对比**: LangGraph vs CrewAI，ChromaDB vs Milvus

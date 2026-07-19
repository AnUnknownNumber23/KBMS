"""
飞书 / Lark Bot 集成 — 企业协作平台直接使用知识库

支持功能:
  1. 群里 @机器人 上传文件 → 自动入库到知识图谱
  2. 群里 @机器人 提问 → RAG 智能问答，回复到群里

对接方式: 飞书开放平台 → 事件订阅 → Webhook URL
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from typing import Any

import httpx

from agents.doc_parser_agent import DocParserAgent
from agents.knowledge_extract_agent import KnowledgeExtractAgent
from agents.qa_agent import QAAgent
from config import settings
from orchestrator.graph import build_knowledge_graph_workflow
from services.knowledge_graph import KnowledgeGraphService
from services.vector_store import VectorStoreService

logger = logging.getLogger(__name__)


# ── Feishu API Helpers ──────────────────────────────────────

class FeishuClient:
    """飞书 API 客户端"""

    BASE = "https://open.feishu.cn/open-apis"

    def __init__(self, app_id: str, app_secret: str) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self._token: str | None = None

    async def _get_token(self) -> str:
        if self._token:
            return self._token
        async with httpx.AsyncClient() as c:
            resp = await c.post(f"{self.BASE}/auth/v3/tenant_access_token/internal", json={
                "app_id": self.app_id,
                "app_secret": self.app_secret,
            })
            data = resp.json()
            self._token = data["tenant_access_token"]
            return self._token

    async def get_file_content(self, file_key: str) -> bytes:
        """下载用户上传的文件"""
        token = await self._get_token()
        async with httpx.AsyncClient() as c:
            resp = await c.get(
                f"{self.BASE}/im/v1/messages/{file_key}/resources/{file_key}?type=file",
                headers={"Authorization": f"Bearer {token}"},
            )
            return resp.content

    async def get_message_file(self, message_id: str, file_key: str) -> bytes:
        """通过消息 ID 下载文件"""
        token = await self._get_token()
        async with httpx.AsyncClient(follow_redirects=True) as c:
            resp = await c.get(
                f"{self.BASE}/im/v1/messages/{message_id}/resources/{file_key}?type=file",
                headers={"Authorization": f"Bearer {token}"},
            )
            # 飞书可能返回 JSON（含下载链接）或直接返回文件流
            content_type = resp.headers.get("content-type", "")
            if "application/json" in content_type:
                data = resp.json()
                if data.get("code") != 0:
                    raise RuntimeError(f"Feishu file download error: {data.get('msg', 'unknown')}")
                # JSON 中可能有 download_url
                url = data.get("data", {}).get("url", "")
                if url:
                    resp2 = await c.get(url)
                    return resp2.content
                raise RuntimeError(f"No file URL in response: {data}")
            return resp.content

    async def reply(self, message_id: str, content: str) -> None:
        """回复消息"""
        token = await self._get_token()
        payload = {"content": json.dumps({"text": content[:4000]}), "msg_type": "text"}
        async with httpx.AsyncClient() as c:
            resp = await c.post(
                f"{self.BASE}/im/v1/messages/{message_id}/reply",
                headers={"Authorization": f"Bearer {token}"},
                json=payload,
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.warning(f"Reply failed: {data.get('code')} {data.get('msg')} msg_id={message_id[:20]}...")


# ── Bot Handler ──────────────────────────────────────────────

class FeishuBotHandler:
    """
    飞书 Bot 事件处理器

    处理两种事件:
      - im.message.receive_v1: 收到消息
      - url_verification:        配置时的 URL 校验
    """

    SUPPORTED_FILE_EXTS = {
        "pdf", "png", "jpg", "jpeg", "txt", "md", "csv", "xlsx", "xls",
        "doc", "docx", "pptx",
    }

    def __init__(
        self,
        feishu_client: FeishuClient,
        vector_store: VectorStoreService | None = None,
        knowledge_graph: KnowledgeGraphService | None = None,
    ) -> None:
        self.client = feishu_client
        self.vector_store = vector_store
        self.knowledge_graph = knowledge_graph
        self._pipelines: dict | None = None
        self._seen_ids: set[str] = set()  # 消息去重

    async def _get_pipelines(self) -> dict:
        if self._pipelines:
            return self._pipelines
        self._pipelines = build_knowledge_graph_workflow(
            vector_store=self.vector_store,
            knowledge_graph=self.knowledge_graph,
        )
        return self._pipelines

    # ── main dispatch ───────────────────────────────────────

    async def handle(self, body: dict) -> dict:
        """事件入口 — URL 校验同步返回，消息事件后台异步处理"""
        event_type = body.get("type", "")

        # URL 校验（同步，飞书需要立即收到 challenge）
        if event_type == "url_verification":
            return {"challenge": body.get("challenge", "")}

        # 消息事件 → 先秒回 200，再后台处理，避免飞书超时重发
        if body.get("header", {}).get("event_type") == "im.message.receive_v1":
            event = body.get("event", {})
            asyncio.create_task(self._handle_message(event))
            return {"code": 0}

        return {"code": 0}

    async def _handle_message(self, event: dict) -> None:
        """处理一条消息"""
        logger.info(f"Feishu event: sender={event.get('sender')}")

        # 跳过机器人自己的消息，避免无限回复循环
        sender = event.get("sender", {})
        sender_type = sender.get("sender_type", "") or sender.get("type", "")
        is_bot = sender.get("is_bot", False)
        if sender_type == "bot" or is_bot:
            logger.info(f"Skipping bot message: sender_type={sender_type}, is_bot={is_bot}")
            return

        message = event.get("message", {})
        message_id = message.get("message_id", "")

        # 去重：飞书可能重复推送同一事件
        if not message_id or message_id in self._seen_ids:
            return
        self._seen_ids.add(message_id)
        if len(self._seen_ids) > 1000:
            self._seen_ids.clear()

        msg_type = message.get("message_type", "")
        content_str = message.get("content", "{}")

        try:
            content = json.loads(content_str)
        except json.JSONDecodeError:
            return

        # 文本消息 → 问答
        if msg_type == "text" and content.get("text"):
            question = content["text"]
            await self._qa_pipeline(message_id, question)
            return

        # 文件消息 → 入库
        if msg_type == "file":
            file_key = content.get("file_key", "")
            file_name = content.get("file_name", "unknown")
            await self._ingest_pipeline(message_id, file_key, file_name)
            return

    # ── QA pipeline ─────────────────────────────────────────

    async def _qa_pipeline(self, message_id: str, question: str) -> None:
        """问答 → 回复到群"""
        try:
            qa_agent = QAAgent(
                vector_store=self.vector_store,
                knowledge_graph=self.knowledge_graph,
            )
            result = await qa_agent.answer(question)

            answer = result.answer
            if len(answer) > 4000:
                answer = answer[:4000] + "\n\n...(答案过长已截断)"

            contexts = result.contexts[:8]
            source_lines = ["\n📎 来源:"]
            for i, c in enumerate(contexts, 1):
                if c.retrieval_type == "graph":
                    # 图谱 → 展示三元组 + 标注
                    source_lines.append(f"  [{i}] {c.content} — knowledge_graph")
                else:
                    # 向量 → 保留文件名 + 内容片段
                    snippet = c.content[:80].replace("\n", " ")
                    fname = c.source.split("\\")[-1].split("/")[-1]
                    source_lines.append(f"  [{i}] {snippet}... — {fname}")

            reply_text = f"{answer}\n{chr(10).join(source_lines)}"

        except Exception as e:
            logger.exception("QA pipeline error")
            reply_text = f"❌ 问答处理失败: {e}"

        await self.client.reply(message_id, reply_text)

    # ── ingest pipeline ──────────────────────────────────────

    async def _ingest_pipeline(self, message_id: str, file_key: str, file_name: str) -> None:
        """下载文件 → 解析 → 入库"""
        ext = os.path.splitext(file_name)[1].lower()
        if ext.lstrip(".") not in self.SUPPORTED_FILE_EXTS:
            await self.client.reply(message_id, f"⚠️ 暂不支持 {ext} 格式，支持: {', '.join(sorted(self.SUPPORTED_FILE_EXTS))}")
            return

        try:
            # 1. 下载文件
            file_bytes = await self.client.get_message_file(message_id, file_key)
            if len(file_bytes) < 10:
                await self.client.reply(message_id, f"❌ 文件下载异常（{len(file_bytes)} bytes），请重试")
                return
            tmp_path = os.path.join(tempfile.gettempdir(), file_name)
            with open(tmp_path, "wb") as f:
                f.write(file_bytes)
            logger.info(f"Downloaded {file_name}: {len(file_bytes)} bytes -> {tmp_path}")
            # 2. 入库
            pipelines = await self._get_pipelines()
            ingest_wf = pipelines.get("ingest")
            if not ingest_wf:
                await self.client.reply(message_id, "❌ 入库流水线未初始化")
                return

            result = await ingest_wf.ainvoke({"file_paths": [tmp_path]})
            chunks = result.get("chunks", [])
            extractions = result.get("extractions", [])
            total_entities = sum(len(e.entities) for e in extractions)
            total_relations = sum(len(e.relations) for e in extractions)

            reply_text = (
                f"✅ 文件《{file_name}》已入库\n"
                f"   📄 文档块: {len(chunks)}\n"
                f"   🧩 实体: {total_entities}\n"
                f"   🔗 关系: {total_relations}"
            )

        except Exception as e:
            logger.exception("Ingest pipeline error")
            reply_text = f"❌ 入库失败: {e}"

        await self.client.reply(message_id, reply_text)


# ── Factory ─────────────────────────────────────────────────

def create_feishu_bot() -> FeishuBotHandler:
    """从环境变量创建 Bot 处理器，复用现有基础设施"""
    feishu_client = FeishuClient(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret,
    )
    return FeishuBotHandler(
        feishu_client=feishu_client,
        vector_store=VectorStoreService(),
        knowledge_graph=KnowledgeGraphService(),
    )

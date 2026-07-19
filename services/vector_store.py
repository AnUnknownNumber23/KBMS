"""
向量存储服务 — 支持 ChromaDB / PGVector 双后端

职责:
  1. 文档块向量化 (Embedding)
  2. 向量存储 & 检索
  3. 按 doc_id 删除（支持增量更新）

Embedding 支持:
  - local:   本地 sentence-transformers（推荐，BGE 系列）
  - openai:  OpenAI / DeepSeek 等兼容 API
"""

from __future__ import annotations

from typing import Any

from agents.doc_parser_agent import DocumentChunk
from config import settings


def _create_embeddings():
    """根据配置创建 Embedding 实例"""
    if settings.embedding_provider == "local":
        from langchain_huggingface import HuggingFaceEmbeddings
        return HuggingFaceEmbeddings(
            model_name=settings.embedding_model,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
    else:
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(
            model=settings.embedding_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )


class VectorStoreService:
    """向量库统一接口，底层可切换 ChromaDB / PGVector"""

    COLLECTION_NAME = "knowledge_chunks"

    def __init__(self) -> None:
        self.embeddings = _create_embeddings()
        self._store: Any = None
        self._backend = settings.vector_store_type

    # ── initialization ───────────────────────────────────────

    async def init(self) -> None:
        if self._backend == "chroma":
            await self._init_chroma()
        else:
            await self._init_pgvector()

    async def _init_chroma(self) -> None:
        import os
        import chromadb
        path = os.path.join(os.path.dirname(__file__), "..", "chroma_data")
        client = chromadb.PersistentClient(path=path)
        self._store = client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    async def _init_pgvector(self) -> None:
        from langchain_community.vectorstores import PGVector
        self._store = PGVector(
            connection_string=settings.pgvector_dsn,
            collection_name=self.COLLECTION_NAME,
            embedding_function=self.embeddings,
        )

    # ── CRUD ─────────────────────────────────────────────────

    async def add_chunks(self, chunks: list[DocumentChunk]) -> int:
        """向量化并存储文档块"""
        if not chunks:
            return 0

        texts = [c.content for c in chunks]
        ids = [c.chunk_id for c in chunks]
        metadatas = [
            {"doc_id": c.doc_id, "doc_type": c.doc_type.value, "source": c.metadata.get("source", ""), "chunk_index": c.chunk_index}
            for c in chunks
        ]

        if self._backend == "chroma":
            vectors = await self.embeddings.aembed_documents(texts)
            self._store.upsert(ids=ids, embeddings=vectors, documents=texts, metadatas=metadatas)
        else:
            await self._store.aadd_texts(texts=texts, metadatas=metadatas, ids=ids)

        return len(chunks)

    async def search(self, query: str, top_k: int = 5) -> list[tuple[dict, float]]:
        """语义搜索，返回 (文档, 分数) 列表"""
        if self._backend == "chroma":
            q_vec = await self.embeddings.aembed_query(query)
            results = self._store.query(query_embeddings=[q_vec], n_results=top_k, include=["documents", "metadatas", "distances"])
            out: list[tuple[dict, float]] = []
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            dists = results.get("distances", [[]])[0]
            for doc, meta, dist in zip(docs, metas, dists):
                score = 1.0 - dist  # cosine distance → similarity
                out.append(({"content": doc, "source": meta.get("source", ""), "metadata": meta}, score))
            return out
        else:
            results = await self._store.asimilarity_search_with_score(query, k=top_k)
            return [
                ({"content": doc.page_content, "source": doc.metadata.get("source", ""), "metadata": doc.metadata}, score)
                for doc, score in results
            ]

    async def delete_by_doc_id(self, doc_id: str) -> int:
        """按 doc_id 删除所有相关向量"""
        if self._backend == "chroma":
            existing = self._store.get(where={"doc_id": doc_id}, include=[])
            ids = existing.get("ids", [])
            if ids:
                self._store.delete(ids=ids)
            return len(ids)
        return 0

    async def list_all(self, limit: int = 100) -> list[dict]:
        """列出向量库中的所有文档块"""
        if self._backend == "chroma":
            result = self._store.get(limit=limit, include=["documents", "metadatas"])
            return [
                {"content": doc[:200], "source": meta.get("source", ""), "doc_id": meta.get("doc_id", ""), "doc_type": meta.get("doc_type", "")}
                for doc, meta in zip(result.get("documents", []), result.get("metadatas", []))
            ]
        return []

    async def get_stats(self) -> dict:
        """获取向量库统计信息"""
        if self._backend == "chroma":
            count = self._store.count()
            return {"backend": "chroma", "total_vectors": count, "collection": self.COLLECTION_NAME}
        return {"backend": "pgvector", "collection": self.COLLECTION_NAME}

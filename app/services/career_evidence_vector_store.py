from __future__ import annotations

from hashlib import sha256
from typing import Any, Callable, TypeVar
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient, models

from app.core.config import settings
from app.services.embedding_provider import create_embeddings
from app.services.career_knowledge import split_knowledge_document
from app.utils.logger import setup_logger

logger = setup_logger(__name__)
T = TypeVar("T")


def _value(document: Any, field: str, default: Any = "") -> Any:
    if isinstance(document, dict):
        return document.get(field, default)
    return getattr(document, field, default)


class CareerEvidenceVectorStore:
    """Versioned Qdrant index for user-owned career technical documents.

    The store is intentionally lazy and only constructed when the feature flag is
    enabled. Retrieval callers can therefore fall back to lexical search if Qdrant
    or the embedding provider is unavailable.
    """

    _instance: "CareerEvidenceVectorStore | None" = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self.collection_name = settings.CAREER_EVIDENCE_VECTOR_COLLECTION
        self.embedding_size = settings.EMBEDDING_DIMENSIONS
        self.embedding = create_embeddings()
        self.client = self._create_client()
        self._ensure_collection()
        self._initialized = True

    def _create_client(self) -> QdrantClient:
        return QdrantClient(
            settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
            timeout=settings.CAREER_EVIDENCE_VECTOR_TIMEOUT,
        )

    def _reset_client(self) -> None:
        self.client = self._create_client()

    @staticmethod
    def _retryable(exc: Exception) -> bool:
        message = str(exc).lower()
        return isinstance(exc, (ConnectionError, OSError, TimeoutError)) or any(
            marker in message
            for marker in ("connection reset", "connection refused", "broken pipe", "server disconnected", "timeout")
        )

    def _run(self, operation_name: str, operation: Callable[[], T]) -> T:
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                return operation()
            except Exception as exc:
                last_error = exc
                if attempt == 0 and self._retryable(exc):
                    logger.warning("Career evidence vector operation %s failed; reconnecting: %s", operation_name, exc)
                    self._reset_client()
                    continue
                raise
        raise last_error or RuntimeError(f"Career evidence vector operation failed: {operation_name}")

    def _ensure_collection(self) -> None:
        collections = self._run(
            "list_collections",
            lambda: self.client.get_collections().collections,
        )
        names = {item.name for item in collections}
        if self.collection_name in names:
            return
        self._run(
            "create_collection",
            lambda: self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=self.embedding_size,
                    distance=models.Distance.COSINE,
                ),
                on_disk_payload=True,
            ),
        )

    @staticmethod
    def _point_id(tenant_id: str, user_id: str, document_id: str, chunk_id: str, source_version: str | None) -> str:
        key = "|".join((tenant_id, user_id, document_id, chunk_id, source_version or ""))
        return str(uuid5(NAMESPACE_URL, f"career-evidence:{sha256(key.encode('utf-8')).hexdigest()}"))

    def delete_document(self, *, tenant_id: str, user_id: str, document_id: str) -> None:
        document_filter = models.Filter(
            must=[
                models.FieldCondition(key="metadata.tenant_id", match=models.MatchValue(value=str(tenant_id))),
                models.FieldCondition(key="metadata.user_id", match=models.MatchValue(value=str(user_id))),
                models.FieldCondition(key="metadata.document_id", match=models.MatchValue(value=str(document_id))),
            ]
        )
        self._run(
            "delete_document",
            lambda: self.client.delete(
                collection_name=self.collection_name,
                points_selector=document_filter,
                wait=True,
            ),
        )

    def upsert_document(self, *, document: Any, tenant_id: str, user_id: str) -> int:
        document_id = str(_value(document, "id", ""))
        if not document_id:
            raise ValueError("career evidence document id is required")
        self.delete_document(tenant_id=tenant_id, user_id=user_id, document_id=document_id)

        chunks = split_knowledge_document(
            document,
            max_chunk_chars=settings.EVIDENCE_CHUNK_MAX_CHARS,
            overlap_chars=settings.EVIDENCE_CHUNK_OVERLAP_CHARS,
        )
        if not chunks:
            return 0

        texts = [str(chunk["text"]) for chunk in chunks]
        vectors = self.embedding.embed_documents(texts)
        title = str(_value(document, "title", "未命名文档"))
        fact_id = _value(document, "fact_id", None)
        source_version = str(_value(document, "source_hash", "")) or None
        points = []
        for chunk, vector in zip(chunks, vectors):
            metadata = {
                "tenant_id": str(tenant_id),
                "user_id": str(user_id),
                "document_id": document_id,
                "fact_id": str(fact_id) if fact_id is not None else "",
                "title": title,
                "section": str(chunk["section"]),
                "chunk_id": str(chunk["chunk_id"]),
                "source_version": source_version or "",
            }
            points.append(
                models.PointStruct(
                    id=self._point_id(str(tenant_id), str(user_id), document_id, str(chunk["chunk_id"]), source_version),
                    vector=vector,
                    payload={"page_content": texts[len(points)], "metadata": metadata},
                )
            )
        self._run(
            "upsert_document",
            lambda: self.client.upsert(collection_name=self.collection_name, points=points, wait=True),
        )
        return len(points)

    def search(
        self,
        *,
        tenant_id: str,
        user_id: str,
        query: str,
        fact_id: int | str | None = None,
        top_k: int = 8,
    ) -> list[dict[str, Any]]:
        query_vector = self.embedding.embed_query(query)
        filters = [
            models.FieldCondition(key="metadata.tenant_id", match=models.MatchValue(value=str(tenant_id))),
            models.FieldCondition(key="metadata.user_id", match=models.MatchValue(value=str(user_id))),
        ]
        if fact_id is not None:
            filters.append(models.FieldCondition(key="metadata.fact_id", match=models.MatchValue(value=str(fact_id))))
        hits = self._run(
            "search",
            lambda: self.client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                query_filter=models.Filter(must=filters),
                limit=top_k,
                with_payload=True,
            ),
        )
        results = []
        for hit in hits:
            payload = hit.payload or {}
            metadata = payload.get("metadata", {})
            results.append({
                "document_id": str(metadata.get("document_id", "")),
                "fact_id": metadata.get("fact_id") or None,
                "title": metadata.get("title", ""),
                "section": metadata.get("section", ""),
                "chunk_id": metadata.get("chunk_id", ""),
                "source_version": metadata.get("source_version") or None,
                "text": str(payload.get("page_content", "")),
                "score": float(hit.score),
            })
        return results

from __future__ import annotations

from hashlib import sha256
from typing import Any, Callable, TypeVar
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient, models

from app.core.config import settings
from app.services.embedding_provider import create_embeddings
from app.services.career_knowledge import split_knowledge_document
from app.services.qdrant_collection_contract import missing_payload_indexes, validate_vector_contract
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
            logger.info("Career evidence collection %s already exists", self.collection_name)
        else:
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
        collection_info = self._run(
            "get_collection_contract",
            lambda: self.client.get_collection(self.collection_name),
        )
        validate_vector_contract(
            collection_info,
            collection_name=self.collection_name,
            expected_size=self.embedding_size,
        )
        self._ensure_payload_indexes(collection_info)

    def _ensure_payload_indexes(self, collection_info: Any) -> None:
        """Index the fields used to enforce tenant/project/version boundaries."""
        required_fields = (
            "metadata.tenant_id", "metadata.user_id", "metadata.document_id",
            "metadata.fact_id", "metadata.project_key", "metadata.source_version",
        )
        for field_name in missing_payload_indexes(collection_info, required_fields):
            try:
                self._run(
                    f"create_payload_index:{field_name}",
                    lambda field_name=field_name: self.client.create_payload_index(
                        collection_name=self.collection_name,
                        field_name=field_name,
                        field_schema=models.PayloadSchemaType.KEYWORD,
                        wait=True,
                    ),
                )
            except Exception as exc:
                # An existing collection may have an incompatible schema; vector
                # retrieval remains usable because filters are still applied.
                logger.warning("Career evidence payload index unavailable for %s: %s", field_name, exc)

    @staticmethod
    def _point_id(tenant_id: str, user_id: str, document_id: str, chunk_id: str, source_version: str | None) -> str:
        key = "|".join((tenant_id, user_id, document_id, chunk_id, source_version or ""))
        return str(uuid5(NAMESPACE_URL, f"career-evidence:{sha256(key.encode('utf-8')).hexdigest()}"))

    def delete_document(self, *, tenant_id: str, user_id: str, document_id: str) -> None:
        document_filter = self._document_filter(tenant_id, user_id, document_id)
        self._run(
            "delete_document",
            lambda: self.client.delete(
                collection_name=self.collection_name,
                points_selector=document_filter,
                wait=True,
            ),
        )

    @staticmethod
    def _document_filter(tenant_id: str, user_id: str, document_id: str) -> models.Filter:
        return models.Filter(
            must=[
                models.FieldCondition(key="metadata.tenant_id", match=models.MatchValue(value=str(tenant_id))),
                models.FieldCondition(key="metadata.user_id", match=models.MatchValue(value=str(user_id))),
                models.FieldCondition(key="metadata.document_id", match=models.MatchValue(value=str(document_id))),
            ]
        )

    def _document_point_ids(self, *, tenant_id: str, user_id: str, document_id: str) -> set[str]:
        document_filter = self._document_filter(tenant_id, user_id, document_id)

        def collect() -> set[str]:
            point_ids: set[str] = set()
            offset = None
            while True:
                records, offset = self.client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=document_filter,
                    limit=256,
                    offset=offset,
                    with_payload=False,
                    with_vectors=False,
                )
                point_ids.update(str(record.id) for record in records)
                if offset is None:
                    return point_ids

        return self._run("list_document_points", collect)

    def upsert_document(self, *, document: Any, tenant_id: str, user_id: str) -> int:
        document_id = str(_value(document, "id", ""))
        if not document_id:
            raise ValueError("career evidence document id is required")

        chunks = split_knowledge_document(
            document,
            max_chunk_chars=settings.EVIDENCE_CHUNK_MAX_CHARS,
            overlap_chars=settings.EVIDENCE_CHUNK_OVERLAP_CHARS,
        )
        if not chunks:
            self.delete_document(tenant_id=tenant_id, user_id=user_id, document_id=document_id)
            return 0

        existing_point_ids = self._document_point_ids(
            tenant_id=tenant_id,
            user_id=user_id,
            document_id=document_id,
        )
        texts = [str(chunk["text"]) for chunk in chunks]
        embedding_texts = [
            " ".join(str(item) for item in chunk.get("claim_texts", []) if str(item).strip())
            + "\n\n"
            + text
            for chunk, text in zip(chunks, texts)
        ]
        batch_size = max(1, int(getattr(settings, "CAREER_EVIDENCE_VECTOR_BATCH_SIZE", 64)))
        vectors = []
        for index in range(0, len(embedding_texts), batch_size):
            vectors.extend(self.embedding.embed_documents(embedding_texts[index:index + batch_size]))
        if len(vectors) != len(chunks):
            raise ValueError(f"Embedding count mismatch: expected {len(chunks)}, got {len(vectors)}")
        if any(len(vector) != self.embedding_size for vector in vectors):
            actual = sorted({len(vector) for vector in vectors})
            raise ValueError(f"Embedding dimension mismatch: expected {self.embedding_size}, got {actual}")
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
                "project_key": str(chunk.get("project_key") or ""),
                "claim_ids": [str(item) for item in chunk.get("claim_ids", [])],
                "claim_texts": [str(item) for item in chunk.get("claim_texts", [])],
                "source_version": source_version or "",
                "chunking_version": str(chunk.get("chunking_version", "")),
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
        current_point_ids = {str(point.id) for point in points}
        stale_point_ids = sorted(existing_point_ids - current_point_ids)
        if stale_point_ids:
            self._run(
                "delete_stale_document_points",
                lambda: self.client.delete(
                    collection_name=self.collection_name,
                    points_selector=models.PointIdsList(points=stale_point_ids),
                    wait=True,
                ),
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
                "project_key": metadata.get("project_key", ""),
                "claim_ids": metadata.get("claim_ids", []) or [],
                "claim_texts": metadata.get("claim_texts", []) or [],
                "source_version": metadata.get("source_version") or None,
                "text": str(payload.get("page_content", "")),
                "score": float(hit.score),
            })
        return results

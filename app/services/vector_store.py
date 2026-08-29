from typing import List, Dict, Any, Optional, Callable, TypeVar
from uuid import uuid4

from langchain_core.embeddings import Embeddings
from qdrant_client import QdrantClient, models

from app.core.config import settings
from app.services.embedding_provider import create_embeddings
from app.services.qdrant_collection_contract import missing_payload_indexes, validate_vector_contract
from app.utils.logger import setup_logger
from app.utils.qdrant import format_chat_results

logger = setup_logger(__name__)
T = TypeVar("T")


class MultiTenantVectorStore:
    """A multi-tenant vector store using Qdrant for efficient semantic search with tenant isolation.
    
    This class implements the approach from the tutorial on building multi-tenant chatbots
    with Qdrant. It uses payload partitioning with tenant_id for data isolation.
    """
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(MultiTenantVectorStore, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(
        self,
        collection_name: str = "multi_tenant_chat_history",
        embedding: Optional[Embeddings] = None,
        use_embedding: bool = True,
    ):
        """Initialize the multi-tenant vector store.
        
        Args:
            collection_name: Name of the Qdrant collection to use
            embedding: Optional embedding model override
        """
        if self._initialized:
            return
        self.collection_name = collection_name
        self.embedding_size = settings.EMBEDDING_DIMENSIONS
        self.embedding = embedding if embedding is not None else (create_embeddings() if use_embedding else None)
        self.client = self._create_client()

        self._ensure_collection_exists()
        self._initialized = True

    def _create_client(self) -> QdrantClient:
        return QdrantClient(
            settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
            timeout=settings.QDRANT_TIMEOUT,
        )

    def _reset_client(self) -> None:
        logger.warning("Resetting Qdrant client after connection failure")
        self.client = self._create_client()

    def _is_retryable_connection_error(self, exc: Exception) -> bool:
        message = str(exc).lower()
        return (
            isinstance(exc, (ConnectionError, OSError, TimeoutError))
            or "connection reset by peer" in message
            or "broken pipe" in message
            or "connection refused" in message
            or "remoteprotocolerror" in message
            or "server disconnected" in message
        )

    def _run_with_reconnect(self, operation_name: str, operation: Callable[[], T]) -> T:
        last_exc: Exception | None = None

        for attempt in range(2):
            try:
                return operation()
            except Exception as exc:
                last_exc = exc
                if attempt == 0 and self._is_retryable_connection_error(exc):
                    logger.warning(
                        "Qdrant operation '%s' failed due to a connection issue, reconnecting and retrying once: %s",
                        operation_name,
                        str(exc),
                    )
                    self._reset_client()
                    continue
                raise

        raise last_exc or RuntimeError(f"Qdrant operation '{operation_name}' failed")
        
    def _ensure_collection_exists(self) -> None:
        """Create the collection if it doesn't exist."""
        collections = self._run_with_reconnect(
            "get_collections",
            lambda: self.client.get_collections().collections,
        )
        collection_names = [collection.name for collection in collections]
        
        if self.collection_name not in collection_names:
            logger.info(f"Creating new collection: {self.collection_name}")
            self._run_with_reconnect(
                "create_collection",
                lambda: self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(
                        size=self.embedding_size,
                        distance=models.Distance.COSINE
                    )
                )
            )
        else:
            logger.info(f"Collection {self.collection_name} already exists")
        collection_info = self._run_with_reconnect(
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
        required_fields = (
            "metadata.tenant_id",
            "metadata.user_id",
            "metadata.chat_id",
            "metadata.embedding_status",
        )
        for field_name in missing_payload_indexes(collection_info, required_fields):
            try:
                self._run_with_reconnect(
                    f"create_payload_index:{field_name}",
                    lambda field_name=field_name: self.client.create_payload_index(
                        collection_name=self.collection_name,
                        field_name=field_name,
                        field_schema=models.PayloadSchemaType.KEYWORD,
                        wait=True,
                    ),
                )
            except Exception as exc:
                logger.warning("Chat history payload index unavailable for %s: %s", field_name, exc)
    
    def store_conversation(
        self, 
        question: str, 
        answer: str, 
        tenant_id: str, 
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """Durably store a turn before optional embedding enrichment.

        Chat history is the system of record for session recovery, so a remote
        embedding outage must not prevent the payload from reaching Qdrant.
        """
        point_id = str(uuid4())
        point_metadata = dict(metadata or {})
        point_metadata["tenant_id"] = tenant_id
        point_metadata["embedding_status"] = "pending"
        content = f"User: {question}\nAssistant: {answer}"

        self._run_with_reconnect(
            "upsert_conversation_payload",
            lambda: self.client.upsert(
                collection_name=self.collection_name,
                points=[models.PointStruct(
                    id=point_id,
                    vector=[0.0] * self.embedding_size,
                    payload={"page_content": content, "metadata": point_metadata},
                )],
                wait=True,
            ),
        )
        return [point_id]

    def enrich_conversation_embedding(self, point_id: str, content: str) -> None:
        """Best-effort semantic enrichment for an already durable chat turn."""
        if self.embedding is None:
            self._set_embedding_status(point_id, "failed")
            return
        try:
            vector = self.embedding.embed_query(content)
            if len(vector) != self.embedding_size:
                raise ValueError(
                    f"Embedding dimension mismatch: expected {self.embedding_size}, got {len(vector)}"
                )
            self._run_with_reconnect(
                "update_conversation_vector",
                lambda: self.client.update_vectors(
                    collection_name=self.collection_name,
                    points=[models.PointVectors(id=point_id, vector=vector)],
                    wait=True,
                ),
            )
            self._set_embedding_status(point_id, "ready")
        except Exception:
            try:
                self._set_embedding_status(point_id, "failed")
            except Exception as status_error:
                logger.warning("Could not mark failed chat embedding point_id=%s: %s", point_id, status_error)
            raise

    def _set_embedding_status(self, point_id: str, status: str) -> None:
        self._run_with_reconnect(
            "set_conversation_embedding_status",
            lambda: self.client.set_payload(
                collection_name=self.collection_name,
                payload={"embedding_status": status},
                points=[point_id],
                key="metadata",
                wait=True,
            ),
        )
        
    def get_chats_by_user_id(
        self,
        user_id: str,
        tenant_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get all chat messages for a specific user, with pagination"""
        response = self._run_with_reconnect(
            "scroll_user_chats",
            lambda: self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="metadata.tenant_id",
                            match=models.MatchValue(value=tenant_id)
                        ),
                        models.FieldCondition(
                            key="metadata.user_id",
                            match=models.MatchValue(value=str(user_id))
                        )
                ]),
                limit=limit,
                offset=offset,
                with_payload=True,
                with_vectors=False
            )
        )

        results = format_chat_results(response[0])
        results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return results
        
    def get_chat_by_id(
        self,
        chat_id: str,
        tenant_id: str,
        user_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get all messages for a specific chat ID belonging to a user"""
        response = self._run_with_reconnect(
            "scroll_chat_by_id",
            lambda: self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="metadata.tenant_id",
                            match=models.MatchValue(value=tenant_id)
                        ),
                        models.FieldCondition(
                            key="metadata.user_id",
                            match=models.MatchValue(value=str(user_id))
                        ),
                        models.FieldCondition(
                            key="metadata.chat_id",
                            match=models.MatchValue(value=chat_id)
                        )
                ]),
                limit=limit,
                offset=offset,
                with_payload=True,
                with_vectors=False
            )
        )

        results = format_chat_results(response[0])
        results.sort(key=lambda x: x.get("timestamp", ""))
        return results

    def search_chat_by_id(
        self,
        query: str,
        chat_id: str,
        tenant_id: str,
        user_id: str,
        limit: int = 6,
    ) -> List[Dict[str, Any]]:
        """Retrieve semantically relevant older turns from one owned chat."""
        if not query.strip():
            return []

        chat_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="metadata.tenant_id",
                    match=models.MatchValue(value=tenant_id),
                ),
                models.FieldCondition(
                    key="metadata.user_id",
                    match=models.MatchValue(value=str(user_id)),
                ),
                models.FieldCondition(
                    key="metadata.chat_id",
                    match=models.MatchValue(value=chat_id),
                ),
            ],
            must_not=[
                models.FieldCondition(
                    key="metadata.embedding_status",
                    match=models.MatchAny(any=["pending", "failed"]),
                ),
            ],
        )

        def search() -> List[Dict[str, Any]]:
            if self.embedding is None:
                raise RuntimeError("Semantic search requires an embedding provider")
            query_vector = self.embedding.embed_query(query)
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                query_filter=chat_filter,
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )
            return format_chat_results(response.points)

        return self._run_with_reconnect("search_chat_by_id", search)

    def delete_chat_by_id(self, chat_id: str, tenant_id: str, user_id: str) -> None:
        """Delete every vector point belonging to one user's interview session."""
        chat_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="metadata.tenant_id",
                    match=models.MatchValue(value=tenant_id),
                ),
                models.FieldCondition(
                    key="metadata.user_id",
                    match=models.MatchValue(value=str(user_id)),
                ),
                models.FieldCondition(
                    key="metadata.chat_id",
                    match=models.MatchValue(value=chat_id),
                ),
            ]
        )
        self._run_with_reconnect(
            "delete_chat_by_id",
            lambda: self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.FilterSelector(filter=chat_filter),
                wait=True,
            ),
        )

    def update_conversation_evaluation(
        self,
        point_id: str,
        tenant_id: str,
        user_id: str,
        chat_id: str,
        status: str,
        evaluation: Optional[Dict[str, Any]] = None,
        job_id: str | None = None,
        error_message: str | None = None,
        evidence_feedback: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Update evaluation metadata for an owned conversation point."""
        def update_payload() -> None:
            records = self.client.retrieve(
                collection_name=self.collection_name,
                ids=[point_id],
                with_payload=True,
                with_vectors=False,
            )
            if not records:
                raise ValueError(f"Conversation point {point_id} was not found")

            metadata = dict((records[0].payload or {}).get("metadata") or {})
            if str(metadata.get("tenant_id")) != str(tenant_id):
                raise PermissionError("Conversation point tenant does not match evaluation scope")
            if str(metadata.get("user_id")) != str(user_id) or str(metadata.get("chat_id")) != str(chat_id):
                raise PermissionError("Conversation point owner does not match evaluation scope")

            updates: Dict[str, Any] = {"evaluation_status": status}
            if evaluation is not None:
                updates["evaluation"] = evaluation
            if evidence_feedback is not None:
                updates["evidence_feedback"] = evidence_feedback
            if job_id:
                updates["evaluation_job_id"] = job_id
            if status in {"queued", "processing", "completed"}:
                metadata.pop("evaluation_error", None)
            if error_message:
                metadata["evaluation_error"] = error_message[:1000]
            metadata.update(updates)
            payload = dict(records[0].payload or {})
            payload["metadata"] = metadata
            self.client.overwrite_payload(
                collection_name=self.collection_name,
                payload=payload,
                points=[point_id],
                wait=True,
            )

        self._run_with_reconnect("update_conversation_evaluation", update_payload)

    def set_conversation_evaluation_job_id(
        self,
        point_id: str,
        tenant_id: str,
        user_id: str,
        chat_id: str,
        job_id: str,
    ) -> None:
        """Attach a queue job ID without overwriting a worker status update."""
        def update_job_reference() -> None:
            records = self.client.retrieve(
                collection_name=self.collection_name,
                ids=[point_id],
                with_payload=True,
                with_vectors=False,
            )
            if not records:
                raise ValueError(f"Conversation point {point_id} was not found")
            metadata = dict((records[0].payload or {}).get("metadata") or {})
            if str(metadata.get("tenant_id")) != str(tenant_id):
                raise PermissionError("Conversation point tenant does not match evaluation scope")
            if str(metadata.get("user_id")) != str(user_id) or str(metadata.get("chat_id")) != str(chat_id):
                raise PermissionError("Conversation point owner does not match evaluation scope")
            self.client.set_payload(
                collection_name=self.collection_name,
                payload={"evaluation_job_id": job_id},
                points=[point_id],
                key="metadata",
                wait=True,
            )

        self._run_with_reconnect("set_conversation_evaluation_job_id", update_job_reference)

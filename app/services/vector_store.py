from typing import List, Dict, Any, Optional, Callable, TypeVar

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from qdrant_client import QdrantClient, models
from langchain_qdrant import QdrantVectorStore

from app.core.config import settings
from app.services.embedding_provider import create_embeddings
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

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MultiTenantVectorStore, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(
        self,
        collection_name: str = "multi_tenant_chat_history",
        embedding: Optional[Embeddings] = None,
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
        self.embedding = embedding or create_embeddings()
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
    
    def store_conversation(
        self, 
        question: str, 
        answer: str, 
        tenant_id: str, 
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """Store a conversation in the vector store with tenant isolation"""
        doc = Document(
            page_content=f"User: {question}\nAssistant: {answer}",
            metadata=metadata or {}
        )

        doc.metadata["tenant_id"] = tenant_id

        return self._run_with_reconnect(
            "add_documents",
            lambda: QdrantVectorStore(
                client=self.client,
                collection_name=self.collection_name,
                embedding=self.embedding,
                validate_embeddings=False,
                validate_collection_config=False,
            ).add_documents([doc]),
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

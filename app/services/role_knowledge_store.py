from typing import Any, Callable, Dict, List, Optional, TypeVar

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient, models

from app.core.config import settings
from app.services.embedding_provider import create_embeddings
from app.services.interview_kit import normalize_interview_role
from app.services.role_question_bank_loader import load_role_question_bank
from app.utils.logger import setup_logger

logger = setup_logger(__name__)
T = TypeVar("T")


class QdrantRoleKnowledgeStore:
    """Dedicated Qdrant-backed role knowledge base for interview RAG.

    This store is intentionally separated from chat-memory collections so role knowledge
    retrieval does not affect existing conversation history behavior.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(QdrantRoleKnowledgeStore, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(
        self,
        collection_name: str = settings.QDRANT_ROLE_KNOWLEDGE_COLLECTION,
        embedding: Optional[Embeddings] = None,
    ):
        if self._initialized:
            return

        self.collection_name = collection_name
        self.embedding_size = settings.EMBEDDING_DIMENSIONS
        self.embedding = embedding or create_embeddings()
        self.client = self._create_client()

        self._ensure_collection_exists()
        self._seed_documents_if_needed()
        self._initialized = True

    def _create_client(self) -> QdrantClient:
        return QdrantClient(
            settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
            timeout=settings.QDRANT_TIMEOUT,
        )

    def _reset_client(self) -> None:
        logger.warning("Resetting Qdrant client after connection failure in role knowledge store")
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
                        "Role knowledge store operation '%s' failed due to connection issue, reconnecting and retrying once: %s",
                        operation_name,
                        str(exc),
                    )
                    self._reset_client()
                    continue
                raise

        raise last_exc or RuntimeError(f"Role knowledge store operation '{operation_name}' failed")

    def _ensure_collection_exists(self) -> None:
        collections = self._run_with_reconnect(
            "get_collections",
            lambda: self.client.get_collections().collections,
        )
        collection_names = [collection.name for collection in collections]

        if self.collection_name not in collection_names:
            logger.info("Creating role knowledge collection: %s", self.collection_name)
            self._run_with_reconnect(
                "create_role_knowledge_collection",
                lambda: self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(
                        size=self.embedding_size,
                        distance=models.Distance.COSINE,
                    ),
                ),
            )
        else:
            logger.info("Role knowledge collection %s already exists", self.collection_name)

    def get_document_count(self) -> int:
        return self._run_with_reconnect(
            "count_role_knowledge_points",
            lambda: self.client.count(
                collection_name=self.collection_name,
                count_filter=None,
                exact=True,
            ).count,
        )

    def _build_documents(self, seed_documents: List[dict]) -> List[Document]:
        return [
            Document(
                page_content=(
                    f"岗位：{document['role']}\n"
                    f"题型：{document['category']}\n"
                    f"面试题：{document['question']}\n"
                    f"考察点：{'；'.join(document.get('focus_points', []))}\n"
                    f"参考回答方向：{document.get('answer_framework', '')}"
                ),
                metadata={
                    "role": document["role"],
                    "doc_type": "interview_question",
                    "title": document["question"],
                    "category": document["category"],
                    "focus_points": document.get("focus_points", []),
                    "answer_framework": document.get("answer_framework", ""),
                    "source": document.get("source", "role_question_bank_json"),
                },
            )
            for document in seed_documents
        ]

    def _list_existing_questions(self) -> set[tuple[str, str, str]]:
        all_points, _ = self._run_with_reconnect(
            "scroll_role_knowledge_points",
            lambda: self.client.scroll(
                collection_name=self.collection_name,
                limit=10000,
                with_payload=True,
                with_vectors=False,
            ),
        )
        existing = set()
        for point in all_points:
            payload = point.payload or {}
            metadata = payload.get("metadata", payload)
            existing.add(
                (
                    str(metadata.get("role", "")),
                    str(metadata.get("category", "")),
                    str(metadata.get("title", "")),
                )
            )
        return existing

    def _append_documents(self, seed_documents: List[dict]) -> int:
        if not seed_documents:
            return 0
        docs = self._build_documents(seed_documents)
        logger.info("Appending %s role knowledge documents into Qdrant", len(docs))
        self._run_with_reconnect(
            "append_role_knowledge_documents",
            lambda: QdrantVectorStore(
                client=self.client,
                collection_name=self.collection_name,
                embedding=self.embedding,
            ).add_documents(docs),
        )
        return len(docs)

    def _seed_documents_if_needed(self) -> None:
        points_count = self.get_document_count()
        if points_count > 0:
            logger.info("Role knowledge collection already seeded with %s documents", points_count)
            return

        seed_documents = load_role_question_bank()
        self._append_documents(seed_documents)

    def append_new_documents(self) -> Dict[str, int]:
        seed_documents = load_role_question_bank()
        existing = self._list_existing_questions()
        new_documents = []

        for document in seed_documents:
            key = (
                str(document.get("role", "")),
                str(document.get("category", "")),
                str(document.get("question", "")),
            )
            if key in existing:
                continue
            new_documents.append(document)

        added_count = self._append_documents(new_documents)
        return {
            "added_count": added_count,
            "total_count": self.get_document_count(),
        }

    def rebuild_collection(self) -> Dict[str, int]:
        self._run_with_reconnect(
            "delete_role_knowledge_collection",
            lambda: self.client.delete_collection(collection_name=self.collection_name),
        )
        self._ensure_collection_exists()
        added_count = self._append_documents(load_role_question_bank())
        return {
            "added_count": added_count,
            "total_count": self.get_document_count(),
        }

    def search_role_knowledge(
        self,
        interview_role: str | None,
        query: str,
        top_k: int = 4,
    ) -> List[Dict[str, Any]]:
        role = normalize_interview_role(interview_role)
        filters = []
        if role and role != "通用软件工程师":
            filters.append(
                models.FieldCondition(
                    key="metadata.role",
                    match=models.MatchValue(value=role),
                )
            )

        query_filter = models.Filter(must=filters) if filters else None
        docs = self._run_with_reconnect(
            "similarity_search_role_knowledge",
            lambda: QdrantVectorStore(
                client=self.client,
                collection_name=self.collection_name,
                embedding=self.embedding,
            ).similarity_search(
                query=query,
                k=top_k,
                filter=query_filter,
            ),
        )

        return [
            {
                "content": doc.page_content,
                "role": doc.metadata.get("role"),
                "doc_type": doc.metadata.get("doc_type"),
                "title": doc.metadata.get("title"),
                "category": doc.metadata.get("category"),
                "focus_points": doc.metadata.get("focus_points", []),
                "answer_framework": doc.metadata.get("answer_framework", ""),
            }
            for doc in docs
        ]

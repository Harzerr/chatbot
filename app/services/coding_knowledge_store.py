from typing import Any, Callable, Dict, List, Optional, TypeVar

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient, models

from app.core.config import settings
from app.services.embedding_provider import create_embeddings
from app.services.coding_question_bank_loader import load_coding_question_bank
from app.services.interview_kit import normalize_interview_role, normalize_interview_round
from app.utils.logger import setup_logger

logger = setup_logger(__name__)
T = TypeVar("T")


class QdrantCodingKnowledgeStore:
    """Dedicated Qdrant-backed coding-question knowledge base for interview RAG."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(QdrantCodingKnowledgeStore, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(
        self,
        collection_name: str = settings.QDRANT_CODING_KNOWLEDGE_COLLECTION,
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
        logger.warning("Resetting Qdrant client after connection failure in coding knowledge store")
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
                        "Coding knowledge store operation '%s' failed due to connection issue, reconnecting and retrying once: %s",
                        operation_name,
                        str(exc),
                    )
                    self._reset_client()
                    continue
                raise
        raise last_exc or RuntimeError(f"Coding knowledge store operation '{operation_name}' failed")

    def _ensure_collection_exists(self) -> None:
        collections = self._run_with_reconnect(
            "get_coding_collections",
            lambda: self.client.get_collections().collections,
        )
        collection_names = [collection.name for collection in collections]
        if self.collection_name not in collection_names:
            logger.info("Creating coding knowledge collection: %s", self.collection_name)
            self._run_with_reconnect(
                "create_coding_knowledge_collection",
                lambda: self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(
                        size=self.embedding_size,
                        distance=models.Distance.COSINE,
                    ),
                ),
            )
        else:
            logger.info("Coding knowledge collection %s already exists", self.collection_name)

    def get_document_count(self) -> int:
        return self._run_with_reconnect(
            "count_coding_knowledge_points",
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
                    f"轮次：{'、'.join(document.get('rounds', []))}\n"
                    f"难度：{document.get('difficulty', '')}\n"
                    f"专题：{document.get('topic', '')}\n"
                    f"代码题：{document['title']}\n"
                    f"题目要求：{document.get('prompt', '')}\n"
                    f"输入要求：{document.get('input_spec', '')}\n"
                    f"输出要求：{document.get('output_spec', '')}\n"
                    f"示例：{'；'.join(document.get('examples', []))}\n"
                    f"考察点：{'；'.join(document.get('evaluation_focus', []))}"
                ),
                metadata={
                    "role": document["role"],
                    "doc_type": "coding_question",
                    "title": document["title"],
                    "rounds": document.get("rounds", []),
                    "difficulty": document.get("difficulty", ""),
                    "topic": document.get("topic", ""),
                    "source_basis": document.get("source_basis", "coding_question_bank"),
                    "prompt": document.get("prompt", ""),
                    "input_spec": document.get("input_spec", ""),
                    "output_spec": document.get("output_spec", ""),
                    "examples": document.get("examples", []),
                    "evaluation_focus": document.get("evaluation_focus", []),
                },
            )
            for document in seed_documents
        ]

    def _list_existing_questions(self) -> set[tuple[str, str]]:
        all_points, _ = self._run_with_reconnect(
            "scroll_coding_knowledge_points",
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
                    str(metadata.get("title", "")),
                )
            )
        return existing

    def _append_documents(self, seed_documents: List[dict]) -> int:
        if not seed_documents:
            return 0
        docs = self._build_documents(seed_documents)
        logger.info("Appending %s coding knowledge documents into Qdrant", len(docs))
        self._run_with_reconnect(
            "append_coding_knowledge_documents",
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
            logger.info("Coding knowledge collection already seeded with %s documents", points_count)
            return
        self._append_documents(load_coding_question_bank())

    def append_new_documents(self) -> Dict[str, int]:
        seed_documents = load_coding_question_bank()
        existing = self._list_existing_questions()
        new_documents = []
        for document in seed_documents:
            key = (str(document.get("role", "")), str(document.get("title", "")))
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
            "delete_coding_knowledge_collection",
            lambda: self.client.delete_collection(collection_name=self.collection_name),
        )
        self._ensure_collection_exists()
        added_count = self._append_documents(load_coding_question_bank())
        return {
            "added_count": added_count,
            "total_count": self.get_document_count(),
        }

    def search_coding_questions(
        self,
        interview_role: str | None,
        interview_type: str | None,
        query: str,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        role = normalize_interview_role(interview_role)
        interview_round = normalize_interview_round(interview_type)
        should_filters = []

        if role and role != "通用软件工程师":
            should_filters.append(
                models.FieldCondition(
                    key="metadata.role",
                    match=models.MatchValue(value=role),
                )
            )
        should_filters.append(
            models.FieldCondition(
                key="metadata.role",
                match=models.MatchValue(value="通用软件工程师"),
            )
        )

        must_filters = [
            models.FieldCondition(
                key="metadata.rounds[]",
                match=models.MatchValue(value=interview_round),
            )
        ]

        query_filter = models.Filter(must=must_filters, should=should_filters)
        docs = self._run_with_reconnect(
            "similarity_search_coding_knowledge",
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

        results: List[Dict[str, Any]] = []
        for doc in docs:
            metadata = dict(doc.metadata or {})
            results.append(
                {
                    "role": metadata.get("role"),
                    "title": metadata.get("title"),
                    "rounds": metadata.get("rounds", []),
                    "difficulty": metadata.get("difficulty"),
                    "topic": metadata.get("topic"),
                    "source_basis": metadata.get("source_basis"),
                    "prompt": metadata.get("prompt", ""),
                    "input_spec": metadata.get("input_spec", ""),
                    "output_spec": metadata.get("output_spec", ""),
                    "examples": metadata.get("examples", []),
                    "evaluation_focus": metadata.get("evaluation_focus", []),
                    "content": doc.page_content,
                }
            )
        return results

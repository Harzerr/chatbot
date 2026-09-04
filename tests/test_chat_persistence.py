import unittest

from qdrant_client import QdrantClient, models

from app.services.vector_store import MultiTenantVectorStore


class StaticEmbedding:
    def __init__(self, vector=None, error=None):
        self.vector = vector or [1.0, 0.0, 0.0]
        self.error = error
        self.calls = 0

    def embed_query(self, _content):
        self.calls += 1
        if self.error:
            raise self.error
        return list(self.vector)


class ChatPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.store = object.__new__(MultiTenantVectorStore)
        self.store.collection_name = "chat_persistence_test"
        self.store.embedding_size = 3
        self.store.client = QdrantClient(":memory:")
        self.store.client.create_collection(
            collection_name=self.store.collection_name,
            vectors_config=models.VectorParams(size=3, distance=models.Distance.COSINE),
        )
        self.store._run_with_reconnect = lambda _name, operation: operation()

    def _store_turn(self):
        return self.store.store_conversation(
            question="第一题回答",
            answer="第二题",
            tenant_id="public",
            metadata={
                "user_id": "2",
                "chat_id": "interview-refresh-test",
                "timestamp": "2026-08-24 10:00:00",
                "question_grounded": True,
                "question_grounding_version": "career-question-grounding-v1",
                "question_evidence_ids": ["doc-a:0"],
                "question_evidence_items": [{
                    "evidence_id": "doc-a:0",
                    "document_id": "doc-a",
                    "document_title": "路径学习项目",
                    "section": "并发模型",
                    "quote": "路径容器由 mutex 保护。",
                }],
            },
        )[0]

    def _retrieve(self, point_id):
        return self.store.client.retrieve(
            collection_name=self.store.collection_name,
            ids=[point_id],
            with_payload=True,
            with_vectors=True,
        )[0]

    def test_payload_is_durable_before_embedding_is_requested(self):
        embedding = StaticEmbedding(error=RuntimeError("403 provider terms of service"))
        self.store.embedding = embedding

        point_id = self._store_turn()
        record = self._retrieve(point_id)

        self.assertEqual(embedding.calls, 0)
        self.assertEqual(record.vector, [0.0, 0.0, 0.0])
        self.assertEqual(record.payload["metadata"]["embedding_status"], "pending")
        self.assertEqual(
            self.store.get_chat_by_id("interview-refresh-test", "public", "2")[0]["user_message"],
            "第一题回答",
        )
        restored = self.store.get_chat_by_id("interview-refresh-test", "public", "2")[0]
        self.assertTrue(restored["question_grounded"])
        self.assertEqual(restored["question_evidence_ids"], ["doc-a:0"])
        self.assertEqual(restored["question_evidence_items"][0]["section"], "并发模型")

    def test_embedding_failure_keeps_payload_and_marks_record_failed(self):
        self.store.embedding = StaticEmbedding(error=RuntimeError("403 provider terms of service"))
        point_id = self._store_turn()

        with self.assertRaisesRegex(RuntimeError, "403"):
            self.store.enrich_conversation_embedding(point_id, "conversation")

        record = self._retrieve(point_id)
        self.assertEqual(record.payload["metadata"]["embedding_status"], "failed")
        self.assertIn("第一题回答", record.payload["page_content"])

    def test_successful_enrichment_updates_vector_and_search_uses_ready_records(self):
        self.store.embedding = StaticEmbedding([1.0, 0.0, 0.0])
        ready_point_id = self._store_turn()
        pending_point_id = self._store_turn()

        self.store.enrich_conversation_embedding(ready_point_id, "conversation")
        matches = self.store.search_chat_by_id(
            query="第一题",
            chat_id="interview-refresh-test",
            tenant_id="public",
            user_id="2",
            limit=10,
        )

        self.assertEqual([match["id"] for match in matches], [ready_point_id])
        self.assertEqual(self._retrieve(ready_point_id).payload["metadata"]["embedding_status"], "ready")
        self.assertEqual(self._retrieve(pending_point_id).payload["metadata"]["embedding_status"], "pending")


if __name__ == "__main__":
    unittest.main()

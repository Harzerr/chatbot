import unittest

from app.services.career_evidence_vector_store import CareerEvidenceVectorStore


class FakeEmbedding:
    def embed_documents(self, texts):
        return [[float(index + 1), 0.0] for index, _ in enumerate(texts)]

    def embed_query(self, query):
        return [1.0, 0.0]


class FakeHit:
    def __init__(self, payload, score):
        self.payload = payload
        self.score = score


class FakeClient:
    def __init__(self):
        self.deleted = []
        self.upserted = []
        self.existing_ids = []

    def delete(self, **kwargs):
        self.deleted.append(kwargs)

    def upsert(self, **kwargs):
        self.upserted.extend(kwargs["points"])

    def scroll(self, **kwargs):
        records = [type("Point", (), {"id": point_id})() for point_id in self.existing_ids]
        return records, None

    def search(self, **kwargs):
        return [FakeHit({
            "page_content": "Redis RQ worker",
            "metadata": {
                "tenant_id": "tenant-a",
                "user_id": "user-1",
                "document_id": "7",
                "fact_id": "11",
                "title": "异步任务",
                "section": "队列",
                "chunk_id": "7:0",
                "source_version": "v1",
            },
        }, 0.88)]


class CareerEvidenceVectorTests(unittest.TestCase):
    def _store(self):
        store = CareerEvidenceVectorStore.__new__(CareerEvidenceVectorStore)
        store.collection_name = "career_evidence_test"
        store.embedding = FakeEmbedding()
        store.client = FakeClient()
        store.embedding_size = 2
        return store

    def test_index_uses_stable_ids_and_tenant_metadata(self):
        store = self._store()
        document = {
            "id": 7,
            "fact_id": 11,
            "title": "异步任务",
            "source_hash": "v1",
            "content_text": "# 队列\nRedis RQ worker 负责异步任务。",
        }

        first_count = store.upsert_document(document=document, tenant_id="tenant-a", user_id="user-1")
        first_id = str(store.client.upserted[0].id)
        store.client.upserted.clear()
        second_count = store.upsert_document(document=document, tenant_id="tenant-a", user_id="user-1")
        second_id = str(store.client.upserted[0].id)

        self.assertEqual(first_count, second_count)
        self.assertEqual(first_id, second_id)
        metadata = store.client.upserted[0].payload["metadata"]
        self.assertEqual(metadata["tenant_id"], "tenant-a")
        self.assertEqual(metadata["user_id"], "user-1")
        self.assertEqual(metadata["source_version"], "v1")
        self.assertEqual(len(store.client.deleted), 0)

    def test_new_version_is_written_before_stale_points_are_deleted(self):
        store = self._store()
        store.client.existing_ids = ["old-version-point"]
        document = {
            "id": 7,
            "fact_id": 11,
            "title": "异步任务",
            "source_hash": "v2",
            "content_text": "# 队列\nRedis RQ worker 负责异步任务。",
        }

        store.upsert_document(document=document, tenant_id="tenant-a", user_id="user-1")

        self.assertTrue(store.client.upserted)
        self.assertEqual(len(store.client.deleted), 1)
        self.assertEqual(store.client.deleted[0]["points_selector"].points, ["old-version-point"])

    def test_embedding_failure_does_not_delete_previous_version(self):
        store = self._store()
        store.client.existing_ids = ["old-version-point"]
        store.embedding = type("FailingEmbedding", (), {
            "embed_documents": lambda self, texts: (_ for _ in ()).throw(TimeoutError("provider timeout")),
        })()
        document = {
            "id": 7,
            "title": "异步任务",
            "source_hash": "v2",
            "content_text": "# 队列\nRedis RQ worker 负责异步任务。",
        }

        with self.assertRaises(TimeoutError):
            store.upsert_document(document=document, tenant_id="tenant-a", user_id="user-1")

        self.assertEqual(store.client.upserted, [])
        self.assertEqual(store.client.deleted, [])

    def test_search_returns_provenance_metadata(self):
        result = self._store().search(
            tenant_id="tenant-a",
            user_id="user-1",
            query="后台任务",
            fact_id=11,
        )

        self.assertEqual(result[0]["document_id"], "7")
        self.assertEqual(result[0]["chunk_id"], "7:0")
        self.assertEqual(result[0]["score"], 0.88)


if __name__ == "__main__":
    unittest.main()

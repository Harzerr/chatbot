import unittest
from unittest.mock import MagicMock, patch

from app.schemas.chat import AnswerEvaluation
from app.services.evaluation_jobs import process_evaluation_job
from app.services.task_queue import enqueue_evaluation_job


class FakeVectorStore:
    def __init__(self):
        self.updates = []

    def update_conversation_evaluation(self, **kwargs):
        self.updates.append(kwargs)


class FakeEvaluationAgent:
    calls = 0

    async def evaluate(self, request):
        self.calls += 1
        return AnswerEvaluation(
            technical_accuracy=80,
            knowledge_depth=75,
            communication_clarity=80,
            logical_structure=75,
            problem_solving=80,
            job_match_score=70,
            overall_score=77,
            summary="评估完成。",
            strengths=["回答包含具体方案"],
            improvement_areas=["补充边界条件"],
        )


class FailOnceEvaluationAgent(FakeEvaluationAgent):
    def __init__(self):
        self.failed = False

    async def evaluate(self, request):
        if not self.failed:
            self.failed = True
            raise RuntimeError("模拟模型调用失败")
        return await super().evaluate(request)


class FakeRedisCache:
    def __init__(self):
        self.values = {}
        self.locks = {}
        self.available = True

    def get_text(self, key):
        return self.values.get(key)

    def set_text(self, key, value, ttl_seconds):
        self.values[key] = value
        return True

    def delete(self, key):
        return self.values.pop(key, None) is not None

    def acquire_lock(self, key, ttl_seconds):
        if key in self.locks:
            return None
        self.locks[key] = "token"
        return "token"

    def release_lock(self, key, token):
        self.locks.pop(key, None)
        return True


class InterviewEvaluationQueueTests(unittest.IsolatedAsyncioTestCase):
    def test_evaluation_jobs_are_configured_for_isolated_retries(self):
        queue = MagicMock()
        queue.enqueue.return_value = MagicMock()
        with patch("app.services.task_queue.get_evaluation_queue", return_value=queue):
            enqueue_evaluation_job({"point_id": "point-1"})

        retry = queue.enqueue.call_args.kwargs["retry"]
        self.assertEqual(retry.max, 2)
        self.assertEqual(retry.intervals, [5, 15])

    async def test_worker_marks_processing_and_completed(self):
        vector_store = FakeVectorStore()
        payload = {
            "point_id": "point-1",
            "tenant_id": "tenant-a",
            "user_id": "7",
            "chat_id": "chat-1",
            "request": {
                "previous_question": "请介绍缓存方案。",
                "user_answer": "我使用 Redis 做缓存。",
            },
        }

        with patch("app.services.evaluation_jobs.MultiTenantVectorStore", return_value=vector_store), patch(
            "app.services.evaluation_jobs.RedisCache", return_value=FakeRedisCache()
        ), patch(
            "app.services.evaluation_jobs.EvaluationAgent", return_value=FakeEvaluationAgent()
        ):
            result = await process_evaluation_job(payload)

        self.assertEqual(result["overall_score"], 77)
        self.assertEqual([item["status"] for item in vector_store.updates], ["processing", "completed"])
        self.assertEqual(vector_store.updates[-1]["evaluation"]["overall_score"], 77)

    async def test_worker_reuses_llm_result_for_identical_request(self):
        vector_store = FakeVectorStore()
        cache = FakeRedisCache()
        agent = FakeEvaluationAgent()
        payload = {
            "point_id": "point-cache",
            "tenant_id": "tenant-a",
            "user_id": "7",
            "chat_id": "chat-cache",
            "request": {
                "previous_question": "请介绍缓存方案。",
                "user_answer": "我使用 Redis 做缓存。",
            },
        }

        with patch("app.services.evaluation_jobs.MultiTenantVectorStore", return_value=vector_store), patch(
            "app.services.evaluation_jobs.RedisCache", return_value=cache
        ), patch("app.services.evaluation_jobs.EvaluationAgent", return_value=agent):
            first = await process_evaluation_job(payload)
            second = await process_evaluation_job({**payload, "point_id": "point-cache-2"})

        self.assertEqual(first["overall_score"], second["overall_score"])
        self.assertFalse(first["evaluation_cache_hit"])
        self.assertTrue(second["evaluation_cache_hit"])
        self.assertEqual(agent.calls, 1)

    async def test_force_refresh_bypasses_previous_evaluation_cache(self):
        vector_store = FakeVectorStore()
        cache = FakeRedisCache()
        agent = FakeEvaluationAgent()
        payload = {
            "point_id": "point-refresh",
            "tenant_id": "tenant-a",
            "user_id": "7",
            "chat_id": "chat-refresh",
            "request": {
                "previous_question": "请介绍缓存方案。",
                "user_answer": "我使用 Redis 做缓存。",
            },
        }

        with patch("app.services.evaluation_jobs.MultiTenantVectorStore", return_value=vector_store), patch(
            "app.services.evaluation_jobs.RedisCache", return_value=cache
        ), patch("app.services.evaluation_jobs.EvaluationAgent", return_value=agent):
            await process_evaluation_job(payload)
            refreshed = await process_evaluation_job({**payload, "point_id": "point-refresh-2", "force_refresh": True})

        self.assertFalse(refreshed["evaluation_cache_hit"])
        self.assertEqual(agent.calls, 2)

    async def test_one_failed_job_does_not_block_the_next_job(self):
        vector_store = FakeVectorStore()
        agent = FailOnceEvaluationAgent()
        payload = {
            "point_id": "point-failure",
            "tenant_id": "tenant-a",
            "user_id": "7",
            "chat_id": "chat-failure",
            "request": {
                "previous_question": "请介绍缓存方案。",
                "user_answer": "我使用 Redis 做缓存。",
            },
        }

        with patch("app.services.evaluation_jobs.MultiTenantVectorStore", return_value=vector_store), patch(
            "app.services.evaluation_jobs.RedisCache", return_value=FakeRedisCache()
        ), patch("app.services.evaluation_jobs.EvaluationAgent", return_value=agent):
            with self.assertRaisesRegex(RuntimeError, "模拟模型调用失败"):
                await process_evaluation_job(payload)
            result = await process_evaluation_job({**payload, "point_id": "point-after-failure"})

        self.assertEqual(result["overall_score"], 77)
        self.assertEqual(
            [item["status"] for item in vector_store.updates],
            ["processing", "failed", "processing", "completed"],
        )


if __name__ == "__main__":
    unittest.main()

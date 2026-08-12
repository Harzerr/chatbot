import unittest
from unittest.mock import patch

from app.schemas.chat import AnswerEvaluation
from app.services.evaluation_jobs import process_evaluation_job


class FakeVectorStore:
    def __init__(self):
        self.updates = []

    def update_conversation_evaluation(self, **kwargs):
        self.updates.append(kwargs)


class FakeEvaluationAgent:
    async def evaluate(self, request):
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


class InterviewEvaluationQueueTests(unittest.IsolatedAsyncioTestCase):
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
            "app.services.evaluation_jobs.EvaluationAgent", return_value=FakeEvaluationAgent()
        ):
            result = await process_evaluation_job(payload)

        self.assertEqual(result["overall_score"], 77)
        self.assertEqual([item["status"] for item in vector_store.updates], ["processing", "completed"])
        self.assertEqual(vector_store.updates[-1]["evaluation"]["overall_score"], 77)


if __name__ == "__main__":
    unittest.main()

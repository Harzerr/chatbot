from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from app.services.career_fact_jobs import process_career_fact_job


class CareerFactJobTests(IsolatedAsyncioTestCase):
    async def test_resume_fact_extraction_runs_in_worker_and_validates_each_fact(self):
        extracted = [
            {
                "fact_type": "project",
                "title": "异步评估平台",
                "content": {"summary": "使用 Redis 和 RQ 解耦逐题评估。"},
                "tags": ["Redis", "RQ"],
                "evidence": "逐题评估由 RQ Worker 异步执行。",
            },
            {"fact_type": "unsupported", "title": "无效事实", "content": {}},
        ]
        with patch(
            "app.services.career_fact_jobs.CareerStudioService.extract_facts",
            new=AsyncMock(return_value=extracted),
        ):
            result = await process_career_fact_job({
                "job_type": "resume",
                "resume_text": "项目经历：使用 Redis 和 RQ 解耦逐题评估。",
            })

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["accepted_count"], 1)
        self.assertEqual(result["rejected_count"], 1)
        self.assertEqual(result["facts"][0]["title"], "异步评估平台")
        self.assertEqual(result["warnings"][0]["title"], "无效事实")


if __name__ == "__main__":
    import unittest

    unittest.main()

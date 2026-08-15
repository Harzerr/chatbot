import unittest

from app.schemas.evaluation import EvaluationRequest, EvidenceFeedbackRequest
from app.services.evaluation_cache import evaluation_cache_key
from app.services.interview_evaluator import InterviewEvaluator
from app.services.interview_report import InterviewReportBuilder


class EvidenceFeedbackTests(unittest.TestCase):
    def test_feedback_is_part_of_evaluation_request_and_cache_key(self):
        base = EvaluationRequest(previous_question="介绍项目。", user_answer="我负责后端。")
        corrected = EvaluationRequest(
            previous_question="介绍项目。",
            user_answer="我负责后端。",
            evidence_feedback=[{"evidence_id": "doc-1:chunk-1", "verdict": "incorrect", "correction": "该证据不是这个项目。"}],
        )
        self.assertNotEqual(evaluation_cache_key(base), evaluation_cache_key(corrected))
        self.assertEqual(corrected.evidence_feedback[0].verdict, "incorrect")

    def test_feedback_schema_limits_to_supported_verdicts(self):
        payload = EvidenceFeedbackRequest(feedback=[{"evidence_id": "doc-1:chunk-1", "verdict": "partial"}])
        self.assertEqual(payload.feedback[0].correction, "")
        with self.assertRaises(ValueError):
            EvidenceFeedbackRequest(feedback=[{"evidence_id": "doc-1:chunk-1", "verdict": "unknown"}])

    def test_report_keeps_feedback_with_question_evidence(self):
        builder = InterviewReportBuilder.__new__(InterviewReportBuilder)
        questions = builder._build_interview_questions_from_chat_messages([
            {"assistant_message": "请介绍项目。", "user_message": "我负责后端。"},
            {
                "assistant_message": "",
                "user_message": "我负责后端。",
                "evaluation": {"knowledge_evidence_items": [{"evidence_id": "doc-1:chunk-1"}]},
                "evidence_feedback": [{"evidence_id": "doc-1:chunk-1", "verdict": "incorrect", "correction": "不是该项目"}],
                "answer_counted": True,
            },
        ], include_reference_answers=False)
        self.assertEqual(questions[0]["evidence_feedback"][0]["verdict"], "incorrect")

    def test_legacy_markdown_context_becomes_stable_evidence_items(self):
        context = (
            "用户上传的技术资料（仅作为候选人提供的证据）：\n"
            "[用户资料：面面通技术文档｜类型：technical_doc]\n"
            "# 面面通\n"
            "负责 FastAPI 面试流程和 LangGraph 节点编排。\n\n"
            "## 技术栈\n"
            "FastAPI、LangGraph、Qdrant。"
        )
        first = InterviewEvaluator.extract_knowledge_evidence(context)
        second = InterviewEvaluator.extract_knowledge_evidence(context)

        self.assertGreaterEqual(len(first[2]), 2)
        self.assertEqual(
            [item.evidence_id for item in first[2]],
            [item.evidence_id for item in second[2]],
        )
        self.assertTrue(all(item.source_type == "career_rag" for item in first[2]))
        self.assertIn("[证据ID：legacy:", first[0][0])

    def test_report_backfills_evidence_for_legacy_evaluation(self):
        builder = InterviewReportBuilder.__new__(InterviewReportBuilder)
        context = "[用户资料：项目文档｜类型：technical_doc]\n## 架构\n使用 Redis 和 RQ Worker。"
        questions = builder._build_interview_questions_from_chat_messages([
            {"assistant_message": "请介绍项目。", "user_message": "我负责异步任务。"},
            {
                "assistant_message": "",
                "user_message": "我负责异步任务。",
                "knowledge_context": context,
                "evaluation": {
                    "question_type": "项目经历题",
                    "overall_score": 70,
                    "summary": "已评估",
                },
                "answer_counted": True,
            },
        ], include_reference_answers=False)

        evidence_items = questions[0]["evaluation"]["knowledge_evidence_items"]
        self.assertEqual(len(evidence_items), 1)
        self.assertEqual(evidence_items[0]["section"], "架构")


if __name__ == "__main__":
    unittest.main()

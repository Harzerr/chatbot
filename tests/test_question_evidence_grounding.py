import unittest
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage

from app.services.interview_report import InterviewReportBuilder
from app.services.interview_skill import InterviewSkill
from app.services.interview_workflow import InterviewWorkflowDecision


def evidence_pack() -> dict:
    return {
        "version": "evidence-pack-v2",
        "retrieval_method": "lexical_bm25_heading_boost",
        "evidence_ids": ["doc-a:0", "doc-a:1", "doc-b:0"],
        "chunks": [
            {
                "evidence_id": "doc-a:0",
                "document_id": "doc-a",
                "title": "路径学习项目",
                "section": "并发模型",
                "fact_id": 7,
                "project_key": "project:path",
                "source_version": "v1",
                "retrieval_method": "lexical_bm25_heading_boost",
                "score": 0.91,
                "text": "路径容器由 mutex 保护，运行状态由 atomic 保存。",
            },
            {
                "evidence_id": "doc-a:1",
                "document_id": "doc-a",
                "title": "路径学习项目",
                "section": "异常恢复",
                "fact_id": 7,
                "project_key": "project:path",
                "source_version": "v1",
                "retrieval_method": "lexical_bm25_heading_boost",
                "score": 0.82,
                "text": "定位跳变时丢弃异常点，并保留上一条有效路径。",
            },
            {
                "evidence_id": "doc-b:0",
                "document_id": "doc-b",
                "title": "标定平台",
                "section": "任务编排",
                "fact_id": 8,
                "project_key": "project:calibration",
                "source_version": "v2",
                "retrieval_method": "lexical_bm25_heading_boost",
                "score": 0.61,
                "text": "平台使用分层状态机编排标定任务。",
            },
        ],
    }


class CapturingLLM:
    def __init__(self):
        self.messages = []

    async def ainvoke(self, messages):
        self.messages = messages
        return AIMessage(content="基于 doc-a:0，路径容器和运行状态为什么分别选择 mutex 与 atomic？")


class QuestionEvidenceSelectionTests(unittest.TestCase):
    def test_selects_only_the_lead_project_for_question_grounding(self):
        decision = InterviewWorkflowDecision(
            phase="project_deep_dive",
            question_mode="follow_up",
            completed_questions=4,
            follow_up_count=1,
            max_follow_ups=2,
            should_switch_to_coding=False,
            should_finish=False,
        )

        references = InterviewSkill._question_evidence_references(evidence_pack(), decision)

        self.assertEqual([item["evidence_id"] for item in references], ["doc-a:0", "doc-a:1"])
        self.assertTrue(all(item["project_key"] == "project:path" for item in references))
        self.assertNotIn("doc-b:0", {item["evidence_id"] for item in references})

    def test_coding_questions_do_not_claim_career_evidence_grounding(self):
        decision = InterviewWorkflowDecision(
            phase="coding",
            question_mode="coding",
            completed_questions=7,
            follow_up_count=0,
            max_follow_ups=2,
            should_switch_to_coding=True,
            should_finish=False,
        )

        self.assertEqual(InterviewSkill._question_evidence_references(evidence_pack(), decision), [])


class QuestionEvidencePromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_project_follow_up_prompt_and_workflow_state_share_the_same_evidence_ids(self):
        llm = CapturingLLM()
        skill = InterviewSkill.__new__(InterviewSkill)
        skill._llm = llm
        skill._evaluator = MagicMock()
        skill._evaluator.should_evaluate.return_value = True
        skill._analyze_jd = lambda *_args: ""
        skill._analyze_resume = lambda *_args: ""
        skill._extract_resume_highlights = lambda *_args: []
        skill._build_skill_instruction_context = lambda: ""
        skill._build_opening_strategy = lambda **_kwargs: ""
        skill._get_company_style = lambda *_args: ""
        skill._build_history_messages = lambda *_args: []
        skill._get_role_knowledge_context = lambda **_kwargs: ""
        skill._build_coding_round_context = lambda **_kwargs: ""
        relevant_docs = [
            {
                "user_message": f"第 {index + 1} 个有效回答包含实现细节。",
                "assistant_message": f"第 {index + 1} 题",
                "answer_counted": True,
                "question_mode": "primary",
                "follow_up_count": 0,
            }
            for index in range(3)
        ]

        result = await skill.run(
            question="我使用 mutex 保护路径容器，atomic 保存运行状态。",
            previous_interviewer_question="路径学习模块如何处理并发？",
            relevant_docs=relevant_docs,
            history_context_docs=relevant_docs,
            context="",
            interview_role="C++开发工程师",
            interview_level="中级",
            interview_type="一面",
            knowledge_context="用户上传的路径学习技术资料",
            evidence_pack=evidence_pack(),
        )

        state = result["workflow_state"]
        self.assertEqual(state["phase"], "project_deep_dive")
        self.assertEqual(state["question_mode"], "follow_up")
        self.assertTrue(state["question_grounded"])
        self.assertEqual(state["question_evidence_ids"], ["doc-a:0", "doc-a:1"])
        prompt = llm.messages[0].content
        self.assertIn("以下证据是本题生成的强制项目锚点", prompt)
        self.assertIn("doc-a:0", prompt)
        self.assertNotIn("doc-b:0｜标定平台", prompt)
        self.assertNotIn("doc-a:0", result["response"])
        self.assertIn("相关项目资料", result["response"])


class QuestionEvidenceReportTests(unittest.TestCase):
    def test_report_binds_previous_generated_question_grounding_to_current_answer(self):
        builder = InterviewReportBuilder.__new__(InterviewReportBuilder)
        builder._generate_reference_answers = lambda _questions: ["参考答案"]
        messages = [
            {
                "id": "turn-1",
                "user_message": "开始面试",
                "assistant_message": "路径容器为什么使用 mutex？",
                "answer_counted": False,
                "question_grounded": True,
                "question_grounding_version": "career-question-grounding-v1",
                "question_evidence_ids": ["doc-a:0"],
                "question_evidence_items": InterviewSkill._question_evidence_references(
                    evidence_pack(),
                    InterviewWorkflowDecision(
                        phase="project_deep_dive",
                        question_mode="follow_up",
                        completed_questions=4,
                        follow_up_count=1,
                        max_follow_ups=2,
                        should_switch_to_coding=False,
                        should_finish=False,
                    ),
                    limit=1,
                ),
            },
            {
                "id": "turn-2",
                "user_message": "因为路径容器包含多个点，需要保证复合读写的一致性。",
                "assistant_message": "下一题",
                "answer_counted": True,
            },
        ]

        questions = builder._build_interview_questions_from_chat_messages(messages)

        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0]["question_evidence_ids"], ["doc-a:0"])
        self.assertEqual(questions[0]["question_evidence_items"][0]["section"], "并发模型")
        self.assertTrue(questions[0]["question_grounded"])


if __name__ == "__main__":
    unittest.main()

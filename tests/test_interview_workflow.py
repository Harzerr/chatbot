import unittest
from unittest.mock import MagicMock

from app.services.interview_skill import InterviewSkill
from app.services.interview_workflow import decide_interview_workflow


class InterviewWorkflowDecisionTests(unittest.TestCase):
    def test_follow_up_count_is_bounded_and_then_switches_topic(self):
        documents = [
            {"question_mode": "follow_up", "follow_up_count": 2},
        ]
        decision = decide_interview_workflow(
            answer="我通过 Redis 锁和唯一请求键实现并发合并。",
            has_previous_question=True,
            current_answer_counted=True,
            completed_questions=3,
            question_limit=10,
            interview_type="一面",
            relevant_docs=documents,
            coding_started=False,
            max_follow_ups=2,
        )

        self.assertEqual(decision.question_mode, "topic_switch")
        self.assertEqual(decision.follow_up_count, 0)

    def test_non_answer_is_not_counted_and_forces_topic_switch(self):
        decision = decide_interview_workflow(
            answer="不知道",
            has_previous_question=True,
            current_answer_counted=False,
            completed_questions=4,
            question_limit=10,
            interview_type="二面",
            relevant_docs=[{"question_mode": "primary", "follow_up_count": 0}],
            coding_started=False,
            max_follow_ups=2,
        )

        self.assertEqual(decision.completed_questions, 4)
        self.assertEqual(decision.question_mode, "topic_switch")

    def test_coding_transition_is_a_backend_decision(self):
        decision = decide_interview_workflow(
            answer="我负责服务拆分，并使用幂等键处理重复任务。",
            has_previous_question=True,
            current_answer_counted=True,
            completed_questions=6,
            question_limit=10,
            interview_type="一面",
            relevant_docs=[{"question_mode": "topic_switch", "follow_up_count": 0}],
            coding_started=False,
            max_follow_ups=2,
        )

        self.assertEqual(decision.phase, "coding")
        self.assertTrue(decision.should_switch_to_coding)

    def test_last_valid_answer_finishes_before_next_question(self):
        decision = decide_interview_workflow(
            answer="我会先构造故障注入测试，再验证补偿任务。",
            has_previous_question=True,
            current_answer_counted=True,
            completed_questions=9,
            question_limit=10,
            interview_type="三面",
            relevant_docs=[],
            coding_started=True,
            max_follow_ups=2,
        )

        self.assertTrue(decision.should_finish)
        self.assertEqual(decision.phase, "closing")
        self.assertEqual(decision.question_mode, "finish")


class InterviewSkillWorkflowIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_coding_transition_keeps_current_answer_evaluation(self):
        skill = InterviewSkill.__new__(InterviewSkill)
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
        skill._pick_coding_question = lambda **_kwargs: {"title": "LRU", "prompt": "实现 LRU"}
        skill._render_coding_question_prompt = lambda *_args: "请实现 LRU。"
        documents = [
            {
                "user_message": "我会给出具体实现和验证方法。",
                "assistant_message": f"第 {index + 1} 题",
                "answer_counted": True,
                "question_mode": "topic_switch",
            }
            for index in range(6)
        ]

        result = await skill.run(
            question="我使用唯一请求键和 Redis 锁合并重复任务。",
            previous_interviewer_question="如何处理重复任务？",
            relevant_docs=documents,
            history_context_docs=documents,
            context="",
            interview_role="Java后端工程师",
            interview_level="中级",
            interview_type="一面",
        )

        self.assertEqual(result["workflow_state"]["question_mode"], "coding")
        self.assertTrue(result["answer_counted"])
        self.assertEqual(result["evaluation_request"]["previous_question"], "如何处理重复任务？")


if __name__ == "__main__":
    unittest.main()

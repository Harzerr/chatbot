import unittest
from unittest.mock import AsyncMock, patch

from app.agent.evaluation_agent import EvaluationAgent
from app.services.interview_assessment import (
    calculate_confidence,
    classify_question_type,
    count_countable_answers,
    extract_jd_requirements,
    extract_resume_evidence,
    get_rubric,
    infer_capability_tags,
    is_countable_answer,
    is_non_answer,
    should_use_career_evidence,
)
from app.schemas.chat import AnswerEvaluation, LLMAnswerEvaluation, RubricScore
from app.schemas.evaluation import EvaluationRequest
from app.services.interview_evaluator import InterviewEvaluator
from app.services.interview_report import InterviewReportBuilder
from app.services.interview_report_pdf import InterviewReportPdfBuilder


class InterviewAssessmentTests(unittest.TestCase):
    def test_non_answers_are_not_counted(self):
        self.assertTrue(is_non_answer("我不太了解这个机制"))
        self.assertTrue(is_non_answer("这个我不太清楚"))
        self.assertTrue(is_non_answer("不清楚"))
        self.assertFalse(is_non_answer("我不了解旧方案，但我会通过 Redis 过期策略和监控来验证。"))
        self.assertFalse(is_countable_answer("开始面试", has_previous_question=False))
        self.assertFalse(is_countable_answer("不知道"))
        self.assertTrue(is_countable_answer("我会先确认数据一致性，再设计重试和补偿机制。"))

    def test_countable_answer_count_ignores_opening_and_unknown_answers(self):
        messages = [
            {"user_message": "开始面试"},
            {"user_message": "不知道", "answer_counted": False},
            {"user_message": "我会先确认边界条件，再选择合适的缓存策略。", "answer_counted": True},
        ]
        self.assertEqual(count_countable_answers(messages), 1)

    def test_evaluator_skips_non_answers(self):
        evaluator = InterviewEvaluator.__new__(InterviewEvaluator)
        self.assertFalse(evaluator.should_evaluate("不了解这个问题", "请解释缓存一致性。"))
        self.assertFalse(evaluator.should_evaluate("不清楚", "请解释缓存一致性。"))
        self.assertTrue(evaluator.should_evaluate("我会先更新数据库，再删除缓存并补偿重试。", "请解释缓存一致性。"))

    def test_report_omits_unknown_answer_from_effective_questions(self):
        builder = InterviewReportBuilder.__new__(InterviewReportBuilder)
        questions = builder._build_interview_questions_from_chat_messages([
            {"user_message": "开始面试", "assistant_message": "请介绍 Redis 的一致性方案。"},
            {"user_message": "不清楚", "assistant_message": "那换一个问题：如何设计缓存失效重试？"},
            {
                "user_message": "我会记录失败事件，使用重试和补偿机制，并通过监控验证结果。",
                "assistant_message": "本场面试已结束。",
                "evaluation": {"expected_key_points": ["说明重试和补偿机制"]},
            },
        ])
        self.assertEqual(len(questions), 1)
        self.assertIn("缓存失效重试", questions[0]["question"])

    def test_report_rechecks_stale_counted_unknown_answers(self):
        builder = InterviewReportBuilder.__new__(InterviewReportBuilder)
        questions = builder._build_interview_questions_from_chat_messages([
            {"user_message": "开始面试", "assistant_message": "请解释 Redis 的一致性方案。"},
            {
                "user_message": "这个我不太清楚",
                "assistant_message": "那换一个问题：如何设计缓存失效重试？",
                "answer_counted": True,
                "evaluation_status": None,
            },
            {
                "user_message": "我会记录失败事件并通过重试补偿。",
                "assistant_message": "本场面试已结束。",
                "answer_counted": True,
                "evaluation_status": "completed",
                "evaluation": {"expected_key_points": ["说明重试和补偿机制"]},
            },
        ], include_reference_answers=False)
        self.assertEqual(len(questions), 1)
        self.assertTrue(questions[0]["answer_counted"])

    def test_partial_report_does_not_generate_reference_answers(self):
        builder = InterviewReportBuilder.__new__(InterviewReportBuilder)
        messages = [
            {"user_message": "开始面试", "assistant_message": "请解释 Redis 的一致性方案。"},
            {
                "user_message": "我会先更新数据库，再删除缓存并做失败补偿。",
                "assistant_message": "下一题：如何定位缓存击穿？",
                "evaluation_status": "processing",
            },
        ]
        with patch.object(builder, "_generate_reference_answers") as generate:
            questions = builder._build_interview_questions_from_chat_messages(
                messages,
                include_reference_answers=False,
            )
        generate.assert_not_called()
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0]["reference_answer"], "暂时无法生成参考答案。")

    def test_report_keeps_evaluation_state_for_question_record(self):
        builder = InterviewReportBuilder.__new__(InterviewReportBuilder)
        messages = [
            {"user_message": "开始面试", "assistant_message": "请解释 Redis 的一致性方案。"},
            {
                "user_message": "我会先更新数据库，再删除缓存。",
                "assistant_message": "下一题。",
                "evaluation_status": "failed",
                "evaluation_error": "模型输出超出长度限制",
            },
        ]
        questions = builder._build_interview_questions_from_chat_messages(
            messages,
            include_reference_answers=False,
        )
        self.assertEqual(questions[0]["evaluation_status"], "failed")
        self.assertEqual(questions[0]["evaluation_error"], "模型输出超出长度限制")

    def test_report_omits_dimension_defaults_when_only_overall_score_exists(self):
        builder = InterviewReportBuilder.__new__(InterviewReportBuilder)
        messages = [
            {
                "user_message": "我会先拆分问题，再通过监控验证结果。",
                "assistant_message": "请说明你的排障方法。",
                "evaluation": {
                    "overall_score": 72,
                    "technical_accuracy": 0,
                    "knowledge_depth": 0,
                    "communication_clarity": 0,
                    "logical_structure": 0,
                    "problem_solving": 0,
                    "job_match_score": 0,
                },
            },
        ]
        report = builder.build("chat-1", messages, include_reference_answers=False)
        self.assertEqual(report.overall_score, 72)
        self.assertIsNone(report.technical_accuracy)
        self.assertIsNone(report.knowledge_depth)
        self.assertIsNone(report.job_match_score)

    def test_report_keeps_explicit_zero_dimensions_when_overall_is_zero(self):
        builder = InterviewReportBuilder.__new__(InterviewReportBuilder)
        messages = [
            {
                "user_message": "没有给出有效回答。",
                "assistant_message": "请说明你的排障方法。",
                "evaluation": {
                    "overall_score": 0,
                    "technical_accuracy": 0,
                    "knowledge_depth": 0,
                    "communication_clarity": 0,
                    "logical_structure": 0,
                    "problem_solving": 0,
                    "job_match_score": 0,
                },
            },
        ]
        report = builder.build("chat-2", messages, include_reference_answers=False)
        self.assertEqual(report.technical_accuracy, 0)
        self.assertEqual(report.job_match_score, 0)

    def test_report_uses_candidate_answer_as_unverified_evidence(self):
        builder = InterviewReportBuilder.__new__(InterviewReportBuilder)
        capabilities = builder._build_competency_assessments([
            {
                "overall_score": 72,
                "capability_tags": ["系统设计"],
                "_candidate_answer": "我会先拆分服务边界，再通过监控验证延迟。",
            },
        ])
        self.assertIn("作答摘录（待核验）", capabilities[0].evidence[0])

    def test_evaluator_preserves_rag_evidence_provenance(self):
        context = (
            "用户上传的技术资料：\n"
            "[证据ID：fact-1:0｜职业事实：12｜文档：项目说明｜章节：架构]\n"
            "使用 Redis 和 RQ 将耗时任务移出请求线程。"
        )
        evidence, evidence_ids = InterviewEvaluator._retrieved_knowledge_evidence(context)
        self.assertEqual(evidence_ids, ["fact-1:0"])
        self.assertIn("项目说明", evidence[0])
        self.assertIn("RQ", evidence[0])

    def test_evaluator_parses_structured_evidence_metadata_and_legacy_headers(self):
        structured = (
            "[证据ID：17:17:0｜职业事实：42｜文档：面试平台技术文档｜章节：评估链路｜"
            "版本：abc123456789｜检索分数：2.75]\n"
            "使用 Judge0 执行代码并保存超时结果。"
        )
        legacy = (
            "[证据ID：17:17:1｜职业事实：42｜文档：面试平台技术文档｜章节：代码执行]\n"
            "保存编译状态和运行状态。"
        )

        structured_items = InterviewEvaluator._retrieved_knowledge_items(structured)
        legacy_items = InterviewEvaluator._retrieved_knowledge_items(legacy)

        self.assertEqual(len(structured_items), 1)
        self.assertEqual(structured_items[0].source_version, "abc123456789")
        self.assertEqual(structured_items[0].retrieval_score, 2.75)
        self.assertEqual(structured_items[0].verification_status, "user_provided")
        self.assertEqual(len(legacy_items), 1)
        self.assertIsNone(legacy_items[0].retrieval_score)

    def test_report_prefers_rag_evidence_over_candidate_answer_fallback(self):
        builder = InterviewReportBuilder.__new__(InterviewReportBuilder)
        capabilities = builder._build_competency_assessments([
            {
                "overall_score": 80,
                "capability_tags": ["项目实践"],
                "knowledge_evidence": ["[证据ID：fact-1:0] RQ 异步任务"],
                "_candidate_answer": "我说过自己做过这个项目。",
            },
        ])
        self.assertIn("RQ 异步任务", capabilities[0].evidence[0])
        self.assertNotIn("我说过自己做过", " ".join(capabilities[0].evidence))

    def test_code_answer_is_rendered_as_verbatim_block(self):
        self.assertTrue(InterviewReportPdfBuilder._is_code_answer(
            "class Solution { return answer; }",
            type("Evaluation", (), {"question_type": "代码题"})(),
        ))
        block = InterviewReportPdfBuilder._code_block("```python\ndef solve():\n    return 1\n```")
        self.assertIn("\\begin{Verbatim}", block)
        self.assertNotIn("```", block)

    def test_fallback_evaluation_still_has_reference_points(self):
        builder = InterviewReportBuilder.__new__(InterviewReportBuilder)
        reference = builder._format_reference_answer_from_evaluation({
            "evaluation_mode": "fallback",
            "rubric_scores": [
                {
                    "label": "技术正确性",
                    "missing_points": ["缺少边界条件说明"],
                },
            ],
        })
        self.assertIn("参考要点", reference)
        self.assertIn("技术正确性", reference)
        self.assertNotIn("暂时无法生成参考答案", reference)

    def test_classifies_project_and_coding_questions(self):
        self.assertEqual(classify_question_type("介绍一下你在这个项目里负责什么，以及如何优化延迟"), "项目深挖题")
        self.assertEqual(classify_question_type("请手撕代码实现 LRU，并分析时间复杂度"), "代码题")
        self.assertTrue(should_use_career_evidence("请介绍你在实习项目中负责的缓存优化"))
        self.assertFalse(should_use_career_evidence("请实现二叉树右视图并分析时间复杂度"))
        self.assertFalse(should_use_career_evidence("什么是 Redis 的持久化机制"))
        self.assertFalse(should_use_career_evidence("Redis 缓存击穿怎么优化，线上指标如何监控"))

    def test_project_rubric_has_explicit_weighting(self):
        rubric = get_rubric("项目深挖题")
        self.assertEqual(round(sum(item.weight for item in rubric), 4), 1.0)
        self.assertTrue(any(item.key == "personal_ownership" for item in rubric))

    def test_extracts_jd_requirements_and_resume_evidence(self):
        jd = """岗位职责：负责高并发服务设计
        任职要求：熟悉 Redis、MySQL 和缓存一致性
        有 Java 服务端开发经验者优先"""
        resume = """AI 面试平台项目：负责 FastAPI 服务设计和 Redis 会话缓存优化。
        使用 MySQL 保存训练记录，并处理缓存失效重试。"""
        requirements = extract_jd_requirements(jd)
        evidence = extract_resume_evidence(resume, "请介绍你如何处理 Redis 缓存一致性问题")
        self.assertTrue(any("Redis" in item for item in requirements))
        self.assertTrue(any("Redis" in item for item in evidence))

    def test_capability_tags_and_confidence_are_bounded(self):
        tags = infer_capability_tags("设计 Redis 缓存一致性方案，并说明高并发下的取舍", "系统设计题")
        self.assertIn("缓存与一致性", tags)
        self.assertIn("系统设计", tags)
        self.assertGreaterEqual(calculate_confidence("x" * 200, 5, True, True), 40)
        self.assertLessEqual(calculate_confidence("x" * 200, 5, True, True), 85)

    def test_fallback_evaluation_exposes_auditable_scoring_basis(self):
        result = InterviewEvaluator._fallback_evaluation(
            user_answer="我会先确认缓存一致性，再通过 Redis 重试和监控验证结果。",
            question_type="技术原理题",
            rubric=get_rubric("技术原理题"),
            capability_tags=["缓存与一致性"],
            reason="主请求 LengthFinishReasonError；紧凑请求 TimeoutError",
        )
        self.assertEqual(result.evaluation_mode, "fallback")
        self.assertTrue(result.evaluation_basis)
        self.assertIn("rubric-v2", result.evaluation_basis[0])
        self.assertIn("综合分", result.evaluation_basis[2])
        self.assertTrue(all(item.rationale for item in result.rubric_scores))
        self.assertIn("LengthFinishReasonError", result.evidence_warnings[0])
        self.assertTrue(result.capability_assessments)

    def test_compact_evaluation_prompt_is_bounded_and_does_not_duplicate_full_prompt(self):
        prompt = InterviewEvaluator._build_compact_prompt(
            role="后端工程师",
            level="中级",
            interview_kind="一面",
            question_type="技术原理题",
            previous_question="问题 " * 1000,
            user_answer="回答 " * 2000,
            rubric=get_rubric("技术原理题"),
            knowledge_context="资料 " * 2000,
        )
        self.assertLess(len(prompt), 5000)
        self.assertIn("只输出结构化 JSON", prompt)

    def test_rubric_overrides_model_total_and_report_aggregates_evidence(self):
        evaluation = AnswerEvaluation(
            technical_accuracy=80,
            knowledge_depth=80,
            communication_clarity=80,
            logical_structure=80,
            problem_solving=80,
            job_match_score=80,
            overall_score=1,
            verdict="正确",
            summary="回答覆盖了关键点。",
            strengths=["技术正确"],
            improvement_areas=["补充边界"],
            capability_assessments=[{
                "capability": "缓存与一致性",
                "score": 75,
                "evidence": ["说明了 Cache Aside"],
                "missing_points": ["未说明并发竞争"],
            }],
            jd_requirement_matches=[{
                "requirement": "熟悉 Redis 缓存一致性",
                "status": "部分体现",
                "evidence": ["说明了 Cache Aside"],
                "gap": "补充重试和补偿",
            }],
            rubric_scores=[
                RubricScore(dimension=item.key, label=item.label, score=4)
                for item in get_rubric("技术原理题")
            ],
        )
        result = InterviewEvaluator._apply_rubric(
            evaluation,
            get_rubric("技术原理题"),
            "我会先更新数据库，再删除缓存，并通过重试补偿失败。",
            True,
            True,
        )
        self.assertEqual(result.overall_score, 100)
        self.assertEqual(result.assessment_version, "rubric-v2")

        builder = InterviewReportBuilder.__new__(InterviewReportBuilder)
        payload = result.model_dump()
        capabilities = builder._build_competency_assessments([payload, payload])
        jd_matches = builder._build_jd_requirement_matches([payload])
        self.assertEqual(capabilities[0].confidence, "中")
        self.assertEqual(jd_matches[0].status, "部分体现")

    def test_judge0_failure_caps_coding_correctness(self):
        rubric = get_rubric("代码题")
        evaluation = AnswerEvaluation(
            technical_accuracy=90,
            knowledge_depth=90,
            communication_clarity=90,
            logical_structure=90,
            problem_solving=90,
            job_match_score=80,
            overall_score=90,
            summary="给出了实现。",
            strengths=["思路完整"],
            improvement_areas=[],
            rubric_scores=[RubricScore(dimension=item.key, label=item.label, score=4) for item in rubric],
        )
        result = InterviewEvaluator._apply_rubric(
            evaluation,
            rubric,
            "这里是我的代码实现",
            False,
            False,
            code_execution={"status": "Compilation Error"},
        )
        correctness = next(item for item in result.rubric_scores if item.dimension == "solution_correctness")
        self.assertEqual(correctness.score, 1)
        self.assertLess(result.overall_score, 100)

    def test_incomplete_rubric_is_not_silently_converted_to_zero(self):
        rubric = get_rubric("技术原理题")
        incomplete = LLMAnswerEvaluation(
            technical_accuracy=0,
            knowledge_depth=0,
            communication_clarity=0,
            logical_structure=0,
            problem_solving=0,
            overall_score=0,
            summary="模型未完整返回评分。",
            rubric_scores=[RubricScore(
                dimension=rubric[0].key,
                label=rubric[0].label,
                score=0,
            )],
        )
        with self.assertRaisesRegex(ValueError, "Rubric 输出不完整"):
            InterviewEvaluator._validate_rubric_completeness(incomplete, rubric)


class EvaluationAgentTests(unittest.IsolatedAsyncioTestCase):
    def _evaluation(self, evidence: list[str]) -> AnswerEvaluation:
        return AnswerEvaluation(
            technical_accuracy=80,
            knowledge_depth=75,
            communication_clarity=80,
            logical_structure=75,
            problem_solving=80,
            job_match_score=70,
            overall_score=77,
            summary="回答覆盖主要技术点。",
            strengths=["给出了具体技术方案"],
            improvement_areas=["补充异常场景"],
            rubric_scores=[
                RubricScore(
                    dimension="technical_correctness",
                    label="技术正确性",
                    score=3,
                    evidence=evidence,
                )
            ],
        )

    async def test_evaluator_agent_adds_auditable_metadata(self):
        core_evaluator = type("CoreEvaluator", (), {})()
        core_evaluator.evaluate_answer = AsyncMock(return_value=self._evaluation(["使用 Redis 做缓存"]))
        core_evaluator.should_evaluate = lambda answer, question: True
        agent = EvaluationAgent(core_evaluator)

        result = await agent.evaluate(
            EvaluationRequest(
                previous_question="请介绍你的缓存方案。",
                user_answer="我使用 Redis 做缓存，并在更新数据库后删除缓存。",
            )
        )

        self.assertEqual(result.evaluator_name, "InterviewEvaluator")
        self.assertTrue(result.evaluator_model)
        self.assertTrue(result.evaluation_run_id)
        self.assertGreaterEqual(result.evaluation_latency_ms, 0)
        self.assertTrue(result.evidence_grounded)
        core_evaluator.evaluate_answer.assert_awaited_once()

    async def test_evaluator_agent_rejects_unverifiable_evidence(self):
        core_evaluator = type("CoreEvaluator", (), {})()
        core_evaluator.evaluate_answer = AsyncMock(return_value=self._evaluation(["使用了不存在的 Kafka 集群"])
        )
        core_evaluator.should_evaluate = lambda answer, question: True
        agent = EvaluationAgent(core_evaluator)

        result = await agent.evaluate(
            EvaluationRequest(
                previous_question="请介绍你的缓存方案。",
                user_answer="我使用 Redis 做缓存。",
            )
        )

        self.assertFalse(result.evidence_grounded)
        self.assertEqual(result.rubric_scores[0].evidence, [])
        self.assertTrue(result.evidence_warnings)

    async def test_evaluator_agent_preserves_fallback_warning(self):
        core_evaluator = type("CoreEvaluator", (), {})()
        core_evaluator.evaluate_answer = AsyncMock(return_value=AnswerEvaluation(
            technical_accuracy=50,
            knowledge_depth=50,
            communication_clarity=50,
            logical_structure=50,
            problem_solving=50,
            overall_score=50,
            summary="规则降级",
            strengths=[],
            improvement_areas=[],
            evaluation_mode="fallback",
            evidence_warnings=["远程评估调用失败：TimeoutError。"],
        ))
        core_evaluator.should_evaluate = lambda answer, question: True
        agent = EvaluationAgent(core_evaluator)
        result = await agent.evaluate(EvaluationRequest(
            previous_question="请解释缓存一致性。",
            user_answer="我会使用缓存和重试机制。",
        ))
        self.assertTrue(any("TimeoutError" in item for item in result.evidence_warnings))

    async def test_incomplete_llm_output_falls_back_instead_of_returning_zero(self):
        evaluator = InterviewEvaluator.__new__(InterviewEvaluator)
        evaluator.llm = object()
        evaluator.compact_llm = object()
        evaluator._invoke_json = AsyncMock(side_effect=ValueError("Rubric 输出不完整"))

        result = await evaluator.evaluate_answer(
            previous_question="请解释 Redis 缓存一致性。",
            user_answer="我会先更新数据库，再删除缓存，并增加失败重试和监控。",
            interview_role="后端工程师",
            interview_level="中级",
            interview_type="技术面",
        )

        self.assertEqual(result.evaluation_mode, "fallback")
        self.assertGreater(result.overall_score, 0)
        self.assertIn("Rubric 输出不完整", result.evidence_warnings[0])
        self.assertEqual(evaluator._invoke_json.await_count, 2)


if __name__ == "__main__":
    unittest.main()

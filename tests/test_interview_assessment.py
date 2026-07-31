import unittest

from app.services.interview_assessment import (
    calculate_confidence,
    classify_question_type,
    extract_jd_requirements,
    extract_resume_evidence,
    get_rubric,
    infer_capability_tags,
)
from app.schemas.chat import AnswerEvaluation, RubricScore
from app.services.interview_evaluator import InterviewEvaluator
from app.services.interview_report import InterviewReportBuilder


class InterviewAssessmentTests(unittest.TestCase):
    def test_classifies_project_and_coding_questions(self):
        self.assertEqual(classify_question_type("介绍一下你在这个项目里负责什么，以及如何优化延迟"), "项目深挖题")
        self.assertEqual(classify_question_type("请手撕代码实现 LRU，并分析时间复杂度"), "代码题")

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


if __name__ == "__main__":
    unittest.main()

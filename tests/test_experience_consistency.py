import unittest
from types import SimpleNamespace

from app.schemas.chat import AnswerEvaluation, ExperienceConsistencyCheck, LLMAnswerEvaluation, RubricScore
from app.schemas.evaluation import EvidencePack, EvaluationRequest
from app.agent.evaluation_agent import EvaluationAgent
from app.services.interview_assessment import get_rubric
from app.services.interview_evaluator import InterviewEvaluator


ANSWER = "我在面试平台项目中使用 Redis 和 RQ 将逐题评估移出请求线程。"
EVIDENCE_TEXT = "面试平台使用 Redis 和 RQ 将逐题评估移出请求线程，并由独立 Worker 处理。"


def make_pack() -> EvidencePack:
    return EvidencePack(
        retrieval_method="lexical_bm25_heading_boost",
        query="Redis RQ 逐题评估",
        retrieval_count=1,
        evidence_ids=["doc-1:chunk-1"],
        chunks=[{
            "evidence_id": "doc-1:chunk-1",
            "text": EVIDENCE_TEXT,
            "document_id": "doc-1",
            "title": "面试平台技术文档",
            "section": "异步评估",
            "fact_id": 7,
            "project_key": "project:interview",
            "source_version": "abc123",
            "retrieval_method": "lexical_bm25_heading_boost",
            "score": 0.91,
        }],
        context=EVIDENCE_TEXT,
    )


def make_result(checks) -> AnswerEvaluation:
    rubric = get_rubric("项目深挖题")
    return AnswerEvaluation(
        technical_accuracy=90,
        knowledge_depth=90,
        communication_clarity=90,
        logical_structure=90,
        problem_solving=90,
        job_match_score=90,
        overall_score=100,
        summary="回答包含项目实现细节。",
        strengths=["项目表达清晰"],
        improvement_areas=[],
        rubric_scores=[
            RubricScore(dimension=spec.key, label=spec.label, score=4)
            for spec in rubric
        ],
        rubric_overall_score=100,
        confidence_score=80,
        confidence_level="高",
        consistency_checks=checks,
    )


class ExperienceConsistencyTests(unittest.TestCase):
    def apply(self, result, *, pack=None, feedback=None, question_type="项目深挖题", answer=ANSWER):
        return InterviewEvaluator._apply_experience_consistency(
            result,
            question_type=question_type,
            user_answer=answer,
            evidence_pack=pack,
            evidence_feedback=feedback,
            rubric=get_rubric("项目深挖题"),
        )

    def test_supported_claim_produces_auditable_consistent_result(self):
        result = make_result([ExperienceConsistencyCheck(
            candidate_claim="使用 Redis 和 RQ 将逐题评估移出请求线程",
            verdict="支持",
            citations=[{"evidence_id": "doc-1:chunk-1", "quote": "使用 Redis 和 RQ 将逐题评估移出请求线程"}],
            rationale="回答声明与项目资料中的技术链路一致。",
        )])

        checked = self.apply(result, pack=make_pack())

        self.assertEqual(checked.resume_consistency, "一致")
        self.assertEqual(checked.knowledge_evidence_ids, ["doc-1:chunk-1"])
        self.assertEqual(checked.knowledge_evidence_source, "evidence_pack_v2")
        self.assertEqual(checked.knowledge_evidence_items[0].document_title, "面试平台技术文档")
        self.assertEqual(checked.overall_score, 100)

        EvaluationAgent._validate_evidence(checked, EvaluationRequest(
            previous_question="请介绍你在项目中的异步评估链路。",
            user_answer=ANSWER,
            knowledge_context=EVIDENCE_TEXT,
            evidence_pack=make_pack(),
        ))
        self.assertTrue(checked.evidence_grounded)

    def test_confirmed_claim_text_is_a_valid_evidence_pack_citation(self):
        claim_text = "基于层次状态机编排标定任务，并结合 PostgreSQL 任务状态推进回放流程。"
        answer = "标定平台使用层次状态机编排任务，并通过 PostgreSQL 保存任务状态。"
        pack = EvidencePack(
            retrieval_count=1,
            evidence_ids=["doc-hsm:chunk-1"],
            chunks=[{
                "evidence_id": "doc-hsm:chunk-1",
                "text": "父状态管理生命周期，子 Action 负责回放、计算和结果处理。",
                "document_id": "doc-hsm",
                "title": "标定平台技术文档",
                "section": "层次状态机",
                "claim_texts": [claim_text],
            }],
        )
        result = make_result([ExperienceConsistencyCheck(
            candidate_claim="标定平台使用层次状态机编排任务",
            verdict="支持",
            citations=[{"evidence_id": "doc-hsm:chunk-1", "quote": claim_text}],
        )])

        checked = self.apply(result, pack=pack, answer=answer)

        self.assertEqual(checked.resume_consistency, "一致")
        self.assertEqual(checked.knowledge_evidence, [claim_text])
        EvaluationAgent._validate_evidence(checked, EvaluationRequest(
            previous_question="请介绍标定平台状态机。",
            user_answer=answer,
            evidence_pack=pack,
        ))
        self.assertTrue(checked.evidence_grounded)

    def test_conflict_caps_project_ownership_without_overwriting_other_dimensions(self):
        conflicting_answer = "我在面试平台项目中将逐题评估保留在请求线程同步执行。"
        result = make_result([ExperienceConsistencyCheck(
            candidate_claim="将逐题评估保留在请求线程同步执行",
            verdict="冲突",
            citations=[{"evidence_id": "doc-1:chunk-1", "quote": "由独立 Worker 处理"}],
            rationale="回答声称在请求线程处理，但资料记录为独立 Worker。",
        )])

        checked = self.apply(result, pack=make_pack(), answer=conflicting_answer)

        ownership = next(item for item in checked.rubric_scores if item.dimension == "personal_ownership")
        technical = next(item for item in checked.rubric_scores if item.dimension != "personal_ownership")
        self.assertEqual(checked.resume_consistency, "存在冲突")
        self.assertEqual(ownership.score, 1)
        self.assertEqual(technical.score, 4)
        self.assertLess(checked.overall_score, 100)
        self.assertLessEqual(checked.confidence_score, 40)

    def test_unknown_evidence_id_is_replaced_only_with_backend_verified_evidence(self):
        result = make_result([ExperienceConsistencyCheck(
            candidate_claim="使用 Redis 和 RQ 将逐题评估移出请求线程",
            verdict="支持",
            citations=[{"evidence_id": "forged-id", "quote": "使用 Redis 和 RQ"}],
        )])

        checked = self.apply(result, pack=make_pack())

        self.assertEqual(checked.resume_consistency, "一致")
        self.assertEqual(checked.consistency_checks[0].verdict, "支持")
        self.assertEqual(checked.consistency_checks[0].citations[0].evidence_id, "doc-1:chunk-1")
        self.assertNotIn("forged-id", checked.knowledge_evidence_ids)
        self.assertTrue(checked.evidence_warnings)

    def test_unknown_evidence_id_cannot_support_an_unmatched_claim(self):
        answer = "我将面试平台改造成了无锁架构。"
        result = make_result([ExperienceConsistencyCheck(
            candidate_claim="将面试平台改造成了无锁架构",
            verdict="支持",
            citations=[{"evidence_id": "forged-id", "quote": "无锁架构"}],
        )])

        checked = self.apply(result, pack=make_pack(), answer=answer)

        self.assertEqual(checked.resume_consistency, "证据不足")
        self.assertEqual(checked.consistency_checks[0].verdict, "证据不足")
        self.assertEqual(checked.knowledge_evidence_ids, [])
        self.assertIn("未通过后端校验", checked.consistency_checks[0].rationale)

    def test_mixed_claim_is_split_into_supported_and_insufficient_boundaries(self):
        answer = "路径学习模块使用单层有限状态机，分层状态机主要用于标定回放平台。"
        confirmed_claim = "标定回放平台基于层次状态机将数据准备、回放执行、结果解析和日志归档封装为独立 Action。"
        pack = EvidencePack(
            retrieval_count=1,
            evidence_ids=["doc-hsm:chunk-1"],
            chunks=[{
                "evidence_id": "doc-hsm:chunk-1",
                "text": "完整 HSM 位于 Python 标定 Agent。",
                "document_id": "doc-hsm",
                "title": "标定平台技术文档",
                "section": "状态机归属",
                "claim_texts": [confirmed_claim],
            }],
        )
        result = make_result([ExperienceConsistencyCheck(
            candidate_claim=answer,
            verdict="支持",
            citations=[{"evidence_id": "forged-id", "quote": "状态机"}],
        )])

        checked = self.apply(result, pack=pack, answer=answer)

        self.assertEqual(checked.resume_consistency, "部分一致")
        self.assertEqual([item.verdict for item in checked.consistency_checks], ["证据不足", "部分支持"])
        self.assertEqual(checked.consistency_checks[1].citations[0].evidence_id, "doc-hsm:chunk-1")

    def test_direct_project_fact_match_recovers_provider_insufficient_verdict(self):
        answer = "我不是只按相似度截断，而是按岗位方向和难度过滤，再通过 Qdrant 召回相关考点。"
        pack = EvidencePack(
            retrieval_count=1,
            evidence_ids=["doc-2:chunk-1"],
            chunks=[{
                "evidence_id": "doc-2:chunk-1",
                "text": "问题生成节点按岗位方向和题目难度过滤候选内容，并通过 Qdrant 向量检索召回相关考点。",
                "document_id": "doc-2",
                "title": "AI 模拟面试平台技术文档",
                "section": "岗位知识检索",
            }],
        )
        result = make_result([ExperienceConsistencyCheck(
            candidate_claim="按岗位方向和难度过滤，再通过 Qdrant 召回相关考点",
            claim_type="project_fact",
            verdict="证据不足",
            rationale="资料提到相同机制，但模型漏填了引用。",
        )])

        checked = self.apply(result, pack=pack, answer=answer)

        self.assertEqual(checked.resume_consistency, "一致")
        self.assertEqual(checked.consistency_checks[0].verdict, "支持")
        self.assertEqual(checked.consistency_checks[0].citations[0].evidence_id, "doc-2:chunk-1")

    def test_direct_match_does_not_infer_personal_ownership_from_passive_project_text(self):
        answer = "我主导了 Redis 和 RQ 异步评估链路的设计和落地。"
        result = make_result([ExperienceConsistencyCheck(
            candidate_claim="我主导了 Redis 和 RQ 异步评估链路的设计和落地",
            claim_type="responsibility_scope",
            verdict="证据不足",
        )])

        checked = self.apply(result, pack=make_pack(), answer=answer)

        self.assertEqual(checked.resume_consistency, "证据不足")
        self.assertEqual(checked.consistency_checks[0].verdict, "证据不足")

    def test_flexible_context_parser_preserves_new_header_metadata(self):
        context = (
            "用户资料：\n[证据ID：6:6:1｜职业事实：44｜文档：博世实习｜章节：路径记录｜"
            "项目边界：project:bosch｜对应要点：记录路径｜版本：abc123｜"
            "检索方式：lexical_bm25_heading_boost｜检索分数：0.9]\n路径记录模块使用状态机。"
        )

        items = InterviewEvaluator._retrieved_knowledge_items(context)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].section, "路径记录")
        self.assertEqual(items[0].source_version, "abc123")

    def test_non_verbatim_candidate_claim_is_rejected(self):
        result = make_result([ExperienceConsistencyCheck(
            candidate_claim="我将系统吞吐提升了百分之五十",
            verdict="支持",
            citations=[{"evidence_id": "doc-1:chunk-1", "quote": "使用 Redis 和 RQ"}],
        )])

        checked = self.apply(result, pack=make_pack())

        self.assertEqual(checked.resume_consistency, "证据不足")
        self.assertEqual(checked.consistency_checks, [])
        self.assertTrue(checked.evidence_warnings)

    def test_user_rejected_or_partial_evidence_cannot_support_consistency(self):
        for verdict in ("incorrect", "partial"):
            with self.subTest(verdict=verdict):
                result = make_result([ExperienceConsistencyCheck(
                    candidate_claim="使用 Redis 和 RQ 将逐题评估移出请求线程",
                    verdict="支持",
                    citations=[{"evidence_id": "doc-1:chunk-1", "quote": "使用 Redis 和 RQ"}],
                )])
                checked = self.apply(
                    result,
                    pack=make_pack(),
                    feedback=[{"evidence_id": "doc-1:chunk-1", "verdict": verdict}],
                )
                self.assertEqual(checked.resume_consistency, "证据不足")

    def test_missing_pack_never_claims_consistency(self):
        checked = self.apply(make_result([]), pack=None)

        self.assertEqual(checked.resume_consistency, "证据不足")
        self.assertIn("未检索到", checked.consistency_summary)
        self.assertLessEqual(checked.confidence_score, 60)

    def test_non_project_question_skips_consistency_check(self):
        checked = self.apply(make_result([]), pack=make_pack(), question_type="技术原理题")

        self.assertEqual(checked.resume_consistency, "不适用")
        self.assertEqual(checked.consistency_checks, [])

    def test_provider_schema_and_queue_round_trip_preserve_consistency_contract(self):
        provider_result = LLMAnswerEvaluation.model_validate({
            "summary": "一致性判断",
            "resume_consistency": "一致",
            "consistency_summary": "资料支持回答。",
            "consistency_checks": [{
                "candidate_claim": "使用 Redis 和 RQ",
                "verdict": "支持",
                "citations": [{"evidence_id": "doc-1:chunk-1", "quote": "使用 Redis 和 RQ"}],
            }],
        })
        pack_payload = make_pack().model_copy(
            update={"chunks": [make_pack().chunks[0].model_copy(update={"source_version": None})]},
        ).model_dump(mode="json")
        queue_request = EvaluationRequest(
            previous_question="请介绍项目",
            user_answer=ANSWER,
            evidence_pack=pack_payload,
        )
        restored = EvaluationRequest.model_validate(queue_request.model_dump(mode="json"))

        self.assertEqual(provider_result.consistency_checks[0].verdict, "支持")
        self.assertEqual(restored.evidence_pack.chunks[0].evidence_id, "doc-1:chunk-1")
        self.assertIsNone(restored.evidence_pack.chunks[0].source_version)

    def test_provider_consistency_aliases_are_normalized_before_validation(self):
        parsed = InterviewEvaluator._parse_json_message(SimpleNamespace(content='''{
          "summary": "部分一致",
          "resume_consistency": "部分一致",
          "consistency_checks": [{
            "candidate_claim": "使用 Redis 和 RQ",
            "verdict": "supported",
            "citations": [{"evidence_id": "doc-1:chunk-1", "quote": "使用 Redis 和 RQ"}]
          }]
        }'''))

        self.assertEqual(parsed.resume_consistency, "部分一致")
        self.assertEqual(parsed.consistency_checks[0].verdict, "支持")

    def test_provider_single_values_are_normalized_to_schema_lists(self):
        parsed = InterviewEvaluator._parse_json_message(SimpleNamespace(content='''{
          "summary": "结构正常",
          "strengths": "说明了异步链路",
          "rubric_scores": {
            "fact_grounding": {
              "score": 3,
              "evidence": "使用 Redis 和 RQ",
              "missing_points": "缺少量化指标"
            }
          }
        }'''))

        self.assertEqual(parsed.strengths, ["说明了异步链路"])
        self.assertEqual(parsed.rubric_scores[0].evidence, ["使用 Redis 和 RQ"])
        self.assertEqual(parsed.rubric_scores[0].missing_points, ["缺少量化指标"])

    def test_provider_fractional_score_and_partial_status_are_safe_to_parse(self):
        parsed = InterviewEvaluator._parse_json_message(SimpleNamespace(content='''{
          "overall_score": 1.25,
          "resume_consistency": "partial",
          "summary": "后端将重新计算总分"
        }'''))

        self.assertEqual(parsed.overall_score, 1)
        self.assertEqual(parsed.resume_consistency, "部分一致")

    def test_provider_boolean_consistency_is_normalized_before_backend_recalculation(self):
        parsed = InterviewEvaluator._parse_json_message(SimpleNamespace(content='''{
          "summary": "供应商返回布尔一致性",
          "resume_consistency": true,
          "consistency_checks": []
        }'''))

        self.assertEqual(parsed.resume_consistency, "一致")


if __name__ == "__main__":
    unittest.main()

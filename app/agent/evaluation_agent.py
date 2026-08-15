import re
from time import perf_counter
from uuid import uuid4

from app.core.config import settings
from app.schemas.chat import AnswerEvaluation
from app.schemas.evaluation import EvaluationRequest, EvaluationRunMetadata
from app.services.interview_evaluator import InterviewEvaluator


class EvaluationAgent:
    """Independent LLM-as-a-Judge agent for interview answer evaluation."""

    name = "InterviewEvaluator"

    def __init__(self, evaluator: InterviewEvaluator | None = None) -> None:
        self._evaluator = evaluator or InterviewEvaluator()

    def should_evaluate(self, user_answer: str, previous_question: str | None) -> bool:
        return self._evaluator.should_evaluate(user_answer, previous_question)

    async def evaluate(self, request: EvaluationRequest) -> AnswerEvaluation:
        started_at = perf_counter()
        result = await self._evaluator.evaluate_answer(**request.model_dump())
        metadata = EvaluationRunMetadata(
            evaluator_name=self.name,
            evaluator_model=settings.EVALUATION_LLM_MODEL,
            evaluation_run_id=uuid4().hex,
            latency_ms=round((perf_counter() - started_at) * 1000),
            model_latency_ms=result.evaluation_model_latency_ms,
            prompt_tokens=result.evaluation_prompt_tokens,
            completion_tokens=result.evaluation_completion_tokens,
            total_tokens=result.evaluation_total_tokens,
            attempts=result.evaluation_attempts,
        )
        result.evaluator_name = metadata.evaluator_name
        result.evaluator_model = metadata.evaluator_model
        result.evaluation_run_id = metadata.evaluation_run_id
        result.evaluation_latency_ms = metadata.latency_ms
        self._validate_evidence(result, request)
        metadata.evidence_grounded = result.evidence_grounded
        metadata.evidence_warnings = result.evidence_warnings
        return result

    async def evaluate_answer(
        self,
        previous_question: str,
        user_answer: str,
        interview_role: str | None,
        interview_level: str | None,
        interview_type: str | None,
        target_company: str | None = None,
        jd_content: str | None = None,
        resume_content: str | None = None,
        code_execution: dict | None = None,
        knowledge_context: str | None = None,
        knowledge_context_cache_hit: bool = False,
    ) -> AnswerEvaluation:
        request = EvaluationRequest(
            previous_question=previous_question,
            user_answer=user_answer,
            interview_role=interview_role,
            interview_level=interview_level,
            interview_type=interview_type,
            target_company=target_company,
            jd_content=jd_content,
            resume_content=resume_content,
            code_execution=code_execution,
            knowledge_context=knowledge_context,
            knowledge_context_cache_hit=knowledge_context_cache_hit,
        )
        return await self.evaluate(request)

    @classmethod
    def _validate_evidence(cls, result: AnswerEvaluation, request: EvaluationRequest) -> None:
        answer_sources = [request.user_answer]
        warnings: list[str] = list(result.evidence_warnings or [])

        for rubric_score in result.rubric_scores:
            rubric_score.evidence, invalid = cls._ground_evidence(rubric_score.evidence, answer_sources)
            if invalid:
                warnings.append(f"Rubric {rubric_score.dimension} 存在无法在回答中核验的证据。")

        for capability in result.capability_assessments:
            capability.evidence, invalid = cls._ground_evidence(capability.evidence, answer_sources)
            if invalid:
                warnings.append(f"能力 {capability.capability} 存在无法在回答中核验的证据。")

        for requirement in result.jd_requirement_matches:
            requirement.evidence, invalid = cls._ground_evidence(requirement.evidence, answer_sources)
            if invalid:
                warnings.append(f"JD 要求 {requirement.requirement} 存在无法在回答中核验的证据。")

        result.resume_evidence, invalid = cls._ground_evidence(result.resume_evidence, [request.resume_content or ""])
        if invalid:
            warnings.append("简历一致性证据中存在无法在简历原文中核验的内容。")

        result.knowledge_evidence, invalid = cls._ground_evidence(
            result.knowledge_evidence,
            [request.knowledge_context or ""],
        )
        if invalid:
            warnings.append("用户资料证据中存在无法在上传文档中核验的内容。")

        result.evidence_warnings = warnings
        result.evidence_grounded = not warnings and any(
            item
            for item in [
                *[score.evidence for score in result.rubric_scores],
                *[item.evidence for item in result.capability_assessments],
                *[item.evidence for item in result.jd_requirement_matches],
                result.resume_evidence,
                result.knowledge_evidence,
            ]
        )

    @classmethod
    def _ground_evidence(cls, evidence: list[str], sources: list[str]) -> tuple[list[str], bool]:
        valid: list[str] = []
        invalid = False
        normalized_sources = [cls._normalize(source) for source in sources if source]
        for item in evidence:
            normalized_item = cls._normalize(item)
            if normalized_item and any(cls._is_supported(normalized_item, source) for source in normalized_sources):
                valid.append(item)
            else:
                invalid = True
        return valid, invalid

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"[^\w\u4e00-\u9fff]+", "", value or "").lower()

    @classmethod
    def _is_supported(cls, evidence: str, source: str) -> bool:
        if len(evidence) >= 6 and evidence in source:
            return True
        tokens = re.findall(r"[a-z0-9+#.-]{2,}|[\u4e00-\u9fff]{2,}", evidence)
        if len(tokens) < 2:
            return False
        matched = sum(1 for token in tokens if token in source)
        return matched / len(tokens) >= 0.6

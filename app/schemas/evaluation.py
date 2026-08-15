from typing import Any, Literal

from pydantic import BaseModel, Field


class EvidenceFeedback(BaseModel):
    """User verification of one retrieved career-document evidence item."""

    evidence_id: str = Field(min_length=1, max_length=255)
    verdict: Literal["correct", "incorrect", "partial"]
    correction: str = Field(default="", max_length=2000)


class EvidenceFeedbackRequest(BaseModel):
    feedback: list[EvidenceFeedback] = Field(min_length=1, max_length=12)


class EvaluationRequest(BaseModel):
    previous_question: str
    user_answer: str
    interview_role: str | None = None
    interview_level: str | None = None
    interview_type: str | None = None
    target_company: str | None = None
    jd_content: str | None = None
    resume_content: str | None = None
    code_execution: dict[str, Any] | None = None
    knowledge_context: str | None = None
    knowledge_context_cache_hit: bool = False
    evidence_feedback: list[EvidenceFeedback] = Field(default_factory=list)


class EvaluationRunMetadata(BaseModel):
    evaluator_name: str = "InterviewEvaluator"
    evaluator_model: str = ""
    evaluation_run_id: str = ""
    latency_ms: int = 0
    model_latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    attempts: int = 0
    evidence_grounded: bool = False
    evidence_warnings: list[str] = Field(default_factory=list)

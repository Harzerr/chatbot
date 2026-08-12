from typing import Any

from pydantic import BaseModel, Field


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


class EvaluationRunMetadata(BaseModel):
    evaluator_name: str = "InterviewEvaluator"
    evaluator_model: str = ""
    evaluation_run_id: str = ""
    latency_ms: int = 0
    evidence_grounded: bool = False
    evidence_warnings: list[str] = Field(default_factory=list)

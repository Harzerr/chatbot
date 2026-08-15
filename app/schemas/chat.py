from typing import List, Optional, Literal

from pydantic import BaseModel, Field
from app.schemas.evaluation import EvidenceFeedback

class RubricScore(BaseModel):
    dimension: str
    label: str
    score: int = Field(ge=0, le=4)
    rationale: str = ""
    evidence: List[str] = Field(default_factory=list)
    missing_points: List[str] = Field(default_factory=list)


class JDRequirementMatch(BaseModel):
    requirement: str
    status: Literal["已体现", "部分体现", "未体现", "不适用"] = "不适用"
    evidence: List[str] = Field(default_factory=list)
    gap: str = ""


class CapabilityAssessment(BaseModel):
    capability: str
    score: int
    evidence: List[str] = Field(default_factory=list)
    missing_points: List[str] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    evidence_id: str
    source_type: Literal["career_rag", "candidate_answer", "resume", "judge0"]
    verification_status: Literal["user_provided", "candidate_claim", "objective", "unverified"] = "unverified"
    quote: str = ""
    fact_id: str | None = None
    document_id: str | None = None
    document_title: str | None = None
    section: str | None = None
    chunk_id: str | None = None
    source_version: str | None = None
    retrieval_method: str = "unknown"
    retrieval_score: float | None = None


class CompetencySummary(BaseModel):
    capability: str
    score: int
    confidence: Literal["低", "中", "高"] = "低"
    covered_questions: int = 0
    evidence: List[str] = Field(default_factory=list)
    evidence_items: List[EvidenceItem] = Field(default_factory=list)
    missing_points: List[str] = Field(default_factory=list)


class AnswerEvaluation(BaseModel):
    technical_accuracy: int
    knowledge_depth: int
    communication_clarity: int
    logical_structure: int
    problem_solving: int
    job_match_score: int = 0
    overall_score: int
    verdict: Optional[str] = None
    correctness_summary: Optional[str] = None
    error_analysis: List[str] = []
    expected_key_points: List[str] = []
    correction_suggestion: Optional[str] = None
    summary: str
    strengths: List[str]
    improvement_areas: List[str]
    assessment_version: str = "legacy"
    question_type: str = "通用技术题"
    capability_tags: List[str] = Field(default_factory=list)
    rubric_scores: List[RubricScore] = Field(default_factory=list)
    rubric_overall_score: int = 0
    confidence_score: int = 0
    confidence_level: Literal["低", "中", "高"] = "低"
    jd_requirement_matches: List[JDRequirementMatch] = Field(default_factory=list)
    resume_consistency: Literal["一致", "证据不足", "存在冲突", "不适用"] = "不适用"
    resume_evidence: List[str] = Field(default_factory=list)
    knowledge_evidence: List[str] = Field(default_factory=list)
    knowledge_evidence_ids: List[str] = Field(default_factory=list)
    knowledge_evidence_source: str = "none"
    knowledge_evidence_items: List[EvidenceItem] = Field(default_factory=list)
    capability_assessments: List[CapabilityAssessment] = Field(default_factory=list)
    evaluator_name: str = "InterviewEvaluator"
    evaluator_model: str = ""
    evaluation_run_id: str = ""
    evaluation_latency_ms: int = 0
    evaluation_model_latency_ms: int = 0
    evaluation_prompt_tokens: int = 0
    evaluation_completion_tokens: int = 0
    evaluation_total_tokens: int = 0
    evaluation_attempts: int = 0
    evaluation_mode: str = "llm"
    evaluation_cache_hit: bool = False
    evidence_grounded: bool = False
    evidence_warnings: List[str] = Field(default_factory=list)
    evaluation_basis: List[str] = Field(default_factory=list)


class LLMAnswerEvaluation(BaseModel):
    """Small provider-facing schema; the service expands it into AnswerEvaluation."""

    technical_accuracy: int = 0
    knowledge_depth: int = 0
    communication_clarity: int = 0
    logical_structure: int = 0
    problem_solving: int = 0
    job_match_score: int = 0
    overall_score: int = 0
    verdict: Optional[str] = None
    correctness_summary: Optional[str] = None
    error_analysis: List[str] = Field(default_factory=list)
    expected_key_points: List[str] = Field(default_factory=list)
    correction_suggestion: Optional[str] = None
    summary: str = ""
    strengths: List[str] = Field(default_factory=list)
    improvement_areas: List[str] = Field(default_factory=list)
    rubric_scores: List[RubricScore] = Field(default_factory=list)

class ChatMessage(BaseModel):
    """Chat message model for API responses"""
    id: str
    user_message: str
    assistant_message: str
    timestamp: str
    chat_id: str
    user_id: str
    interview_role: str | None = None
    interview_level: str | None = None
    interview_type: str | None = None
    target_company: str | None = None
    jd_content: str | None = None
    resume_content: str | None = None
    evaluation: Optional[AnswerEvaluation] = None
    evaluation_status: Optional[str] = None
    evaluation_job_id: Optional[str] = None
    evaluation_error: Optional[str] = None
    answer_counted: Optional[bool] = None
    interview_status: Optional[str] = None
    interview_paused_at: Optional[str] = None
    interview_paused_seconds: float = 0.0


class InterviewSessionActionResponse(BaseModel):
    chat_id: str
    status: str
    paused_at: Optional[str] = None
    paused_seconds: float = 0.0


class ChatDeleteResponse(BaseModel):
    chat_id: str
    deleted: bool

class ChatHistoryResponse(BaseModel):
    """Response model for chat history endpoints"""
    messages: List[ChatMessage]
    total: int

class RecommendedResource(BaseModel):
    title: str
    category: str
    reason: str


class InterviewQuestionReference(BaseModel):
    point_id: Optional[str] = None
    question: str
    candidate_answer: Optional[str] = None
    reference_answer: str
    evaluation: Optional[AnswerEvaluation] = None
    evaluation_status: Optional[str] = None
    evaluation_error: Optional[str] = None
    answer_counted: Optional[bool] = None
    evidence_feedback: List[EvidenceFeedback] = Field(default_factory=list)

class InterviewReportResponse(BaseModel):
    chat_id: str
    interview_role: Optional[str] = None
    interview_level: Optional[str] = None
    interview_type: Optional[str] = None
    target_company: Optional[str] = None
    total_answers: int
    overall_score: Optional[int] = None
    technical_accuracy: Optional[int] = None
    knowledge_depth: Optional[int] = None
    communication_clarity: Optional[int] = None
    logical_structure: Optional[int] = None
    problem_solving: Optional[int] = None
    job_match_score: Optional[int] = None
    summary: str
    content_analysis: str = ""
    strengths: List[str]
    improvement_areas: List[str]
    recommendations: List[str]
    recommended_resources: List[RecommendedResource]
    interview_questions: List[InterviewQuestionReference] = Field(default_factory=list)
    assessment_version: str = "legacy"
    coverage_status: str = "暂无有效能力覆盖数据"
    competency_assessments: List[CompetencySummary] = Field(default_factory=list)
    jd_requirement_matches: List[JDRequirementMatch] = Field(default_factory=list)

class VoiceTranscriptTurn(BaseModel):
    role: Literal["candidate", "interviewer"]
    text: str
    timestamp: Optional[str] = None

class VoiceInterviewReportRequest(BaseModel):
    chat_id: Optional[str] = None
    interview_role: Optional[str] = None
    interview_level: Optional[str] = None
    interview_type: Optional[str] = None
    target_company: Optional[str] = None
    jd_content: Optional[str] = None
    transcript: List[VoiceTranscriptTurn] = []

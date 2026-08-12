from typing import List, Optional, Literal

from pydantic import BaseModel, Field

class RubricScore(BaseModel):
    dimension: str
    label: str
    score: int
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


class CompetencySummary(BaseModel):
    capability: str
    score: int
    confidence: Literal["低", "中", "高"] = "低"
    covered_questions: int = 0
    evidence: List[str] = Field(default_factory=list)
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
    capability_assessments: List[CapabilityAssessment] = Field(default_factory=list)
    evaluator_name: str = "InterviewEvaluator"
    evaluator_model: str = ""
    evaluation_run_id: str = ""
    evaluation_latency_ms: int = 0
    evidence_grounded: bool = False
    evidence_warnings: List[str] = Field(default_factory=list)

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
    question: str
    candidate_answer: Optional[str] = None
    reference_answer: str

class InterviewReportResponse(BaseModel):
    chat_id: str
    interview_role: Optional[str] = None
    interview_level: Optional[str] = None
    interview_type: Optional[str] = None
    target_company: Optional[str] = None
    total_answers: int
    overall_score: int
    technical_accuracy: int
    knowledge_depth: int
    communication_clarity: int
    logical_structure: int
    problem_solving: int
    job_match_score: int
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

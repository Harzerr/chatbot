from typing import List, Optional, Literal

from pydantic import BaseModel, Field

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



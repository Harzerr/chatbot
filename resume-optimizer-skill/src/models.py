from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field

class DocumentChunk(BaseModel):
    chunk_id: str
    text: str
    chunk_index: Optional[int] = None
    page: Optional[int] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    section_hint: Optional[str] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None

class ExtractorInput(BaseModel):
    document_id: str
    source_type: Optional[str] = None
    project_mode: Literal["single_project", "multi_project"] = "single_project"
    project_metadata: dict = Field(default_factory=dict)
    chunks: list[DocumentChunk]

class EvidenceChunk(BaseModel):
    chunk_id: str
    quote: str
    support: str
    page: Optional[int] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None

PointCategory = Literal[
    'background', 'goal', 'role', 'responsibility', 'architecture', 'implementation',
    'integration', 'data_processing', 'algorithm', 'performance', 'reliability',
    'security', 'testing', 'deployment', 'operations', 'result', 'metric', 'other',
]

class ProjectKeyPoint(BaseModel):
    point_id: str
    category: PointCategory
    title: str
    normalized_fact: str
    resume_bullet: str
    confidence: Literal['high','medium','low']
    notes: Optional[str] = None
    evidence_chunks: list[EvidenceChunk] = Field(min_length=1, max_length=3)

class ProjectExtraction(BaseModel):
    project_id: str
    project_name: str
    time_range: Optional[str] = None
    role: Optional[str] = None
    summary: Optional[str] = None
    engineering_challenge: Optional[str] = None
    design_rationale: Optional[str] = None
    tech_stack: list[str] = Field(default_factory=list)
    industrial_roles: list[dict] = Field(default_factory=list)
    source_chunk_ids: list[str] = Field(default_factory=list)
    key_points: list[ProjectKeyPoint] = Field(default_factory=list)

class ExtractorOutput(BaseModel):
    document_id: str
    projects: list[ProjectExtraction]
    unassigned_chunks: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

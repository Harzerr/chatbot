from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator


FactType = Literal["experience", "project", "skill", "education", "certificate", "award", "language", "other"]


class CareerFactBase(BaseModel):
    fact_type: FactType
    title: str = Field(min_length=1, max_length=255)
    content: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    evidence: str | None = Field(default=None, max_length=10000)
    is_verified: bool = False

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(tag.strip() for tag in value if tag.strip()))[:30]


class CareerFactCreate(CareerFactBase):
    pass


class CareerFactUpdate(BaseModel):
    fact_type: FactType | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: dict[str, Any] | None = None
    tags: list[str] | None = None
    evidence: str | None = Field(default=None, max_length=10000)
    is_verified: bool | None = None
    is_archived: bool | None = None


class CareerFactRead(CareerFactBase):
    id: int
    is_archived: bool
    source_resume_name: str | None = None
    created_at: datetime
    updated_at: datetime


class FactExtractionWarning(BaseModel):
    index: int
    title: str = ""
    reason: str


class FactExtractionResponse(BaseModel):
    facts: list[CareerFactCreate]
    status: str = "completed"
    accepted_count: int = 0
    rejected_count: int = 0
    warnings: list[FactExtractionWarning] = Field(default_factory=list)
    message: str = ""


class ResumeProfileImportRequest(BaseModel):
    draft: dict[str, Any]


class ResumeProfileImportResponse(BaseModel):
    imported_facts: int
    skipped_facts: int
    updated_profile: bool
    education_records: int


class JobImportRequest(BaseModel):
    source_url: HttpUrl | None = None
    raw_content: str | None = Field(default=None, max_length=50000)

    @field_validator("raw_content")
    @classmethod
    def strip_content(cls, value: str | None) -> str | None:
        return value.strip() if value else value


class JobPostingUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    company: str | None = Field(default=None, max_length=255)
    raw_content: str | None = Field(default=None, min_length=20, max_length=50000)
    normalized: dict[str, Any] | None = None


class JobPostingRead(BaseModel):
    id: int
    title: str
    company: str
    source_url: str | None = None
    raw_content: str
    normalized: dict[str, Any]
    extraction_status: str
    created_at: datetime
    updated_at: datetime


class TailoredResumeRequest(BaseModel):
    job_id: int
    title: str | None = Field(default=None, max_length=255)
    fact_ids: list[int] = Field(default_factory=list, max_length=100)

    @field_validator("fact_ids")
    @classmethod
    def normalize_fact_ids(cls, value: list[int]) -> list[int]:
        return list(dict.fromkeys(fact_id for fact_id in value if fact_id > 0))


class ResumeDocumentRead(BaseModel):
    id: int
    job_id: int | None = None
    kind: str
    title: str
    schema_version: str
    content: dict[str, Any]
    match: dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime


class ResumeDocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: dict[str, Any] | None = None
    status: str | None = Field(default=None, pattern=r"^[a-z_]{1,32}$")

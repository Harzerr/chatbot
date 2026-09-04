from datetime import datetime

from pydantic import BaseModel, Field


class ResumeParseJobRead(BaseModel):
    id: int
    source_id: int
    status: str
    stage: str
    progress: int
    parser_name: str | None = None
    page_count: int | None = None
    quality_score: float | None = None
    warnings: list[str] = Field(default_factory=list)
    executor: str = "rq"
    queue_job_id: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ResumeSourceRead(BaseModel):
    id: int
    original_filename: str
    content_type: str
    file_size: int
    sha256: str
    status: str
    created_at: datetime
    updated_at: datetime

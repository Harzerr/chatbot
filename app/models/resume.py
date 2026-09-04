from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text

from app.db.base_class import Base


class ResumeSource(Base):
    __tablename__ = "resume_sources"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    original_filename = Column(String(255), nullable=False)
    stored_path = Column(String(1024), nullable=False)
    content_type = Column(String(128), nullable=False)
    file_size = Column(Integer, nullable=False, default=0)
    sha256 = Column(String(64), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="uploaded", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class ResumeParseJob(Base):
    __tablename__ = "resume_parse_jobs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    source_id = Column(Integer, ForeignKey("resume_sources.id"), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="queued", index=True)
    stage = Column(String(64), nullable=False, default="queued")
    progress = Column(Integer, nullable=False, default=0)
    extracted_text = Column(Text, nullable=True)
    parser_name = Column(String(64), nullable=True)
    page_count = Column(Integer, nullable=True)
    quality_score = Column(Float, nullable=True)
    warnings_json = Column(Text, nullable=False, default="[]")
    executor = Column(String(32), nullable=False, default="rq")
    queue_job_id = Column(String(128), nullable=True, index=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

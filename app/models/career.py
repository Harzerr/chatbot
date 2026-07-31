from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from app.db.base_class import Base


class CareerFact(Base):
    __tablename__ = "career_facts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    fact_type = Column(String(64), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    content_json = Column(Text, nullable=False)
    tags_json = Column(Text, nullable=False, default="[]")
    evidence = Column(Text, nullable=True)
    source_resume_name = Column(String(255), nullable=True)
    is_verified = Column(Boolean, nullable=False, default=False, index=True)
    is_archived = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class JobPosting(Base):
    __tablename__ = "job_postings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    title = Column(String(255), nullable=False, default="")
    company = Column(String(255), nullable=False, default="")
    source_url = Column(String(2048), nullable=True)
    raw_content = Column(Text, nullable=False)
    normalized_json = Column(Text, nullable=False)
    extraction_status = Column(String(32), nullable=False, default="ready")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class ResumeDocument(Base):
    __tablename__ = "resume_documents"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    job_id = Column(Integer, nullable=True, index=True)
    kind = Column(String(32), nullable=False, default="tailored")
    title = Column(String(255), nullable=False)
    schema_version = Column(String(32), nullable=False, default="1.0")
    content_json = Column(Text, nullable=False)
    match_json = Column(Text, nullable=False, default="{}")
    status = Column(String(32), nullable=False, default="draft")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

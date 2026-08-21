from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

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


class CareerKnowledgeDocument(Base):
    __tablename__ = "career_knowledge_documents"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    fact_id = Column(Integer, nullable=True, index=True)
    title = Column(String(255), nullable=False)
    file_name = Column(String(255), nullable=False)
    document_type = Column(String(32), nullable=False, default="technical_doc", index=True)
    content_type = Column(String(128), nullable=False, default="text/plain")
    content_text = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=False, default="{}")
    source_hash = Column(String(64), nullable=False, index=True)
    is_archived = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    chunks = relationship(
        "CareerKnowledgeChunk",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="CareerKnowledgeChunk.chunk_index",
    )


class CareerKnowledgeChunk(Base):
    """Canonical derived chunk kept separately from the source document."""

    __tablename__ = "career_knowledge_chunks"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(ForeignKey("career_knowledge_documents.id"), nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    fact_id = Column(Integer, nullable=True, index=True)
    chunk_index = Column(Integer, nullable=False)
    chunk_id = Column(String(255), nullable=False, index=True)
    section = Column(String(255), nullable=False, default="")
    text = Column(Text, nullable=False)
    project_key = Column(String(128), nullable=False, default="", index=True)
    claim_ids_json = Column(Text, nullable=False, default="[]")
    claim_texts_json = Column(Text, nullable=False, default="[]")
    source_version = Column(String(64), nullable=True, index=True)
    chunking_version = Column(String(64), nullable=False, default="career-evidence-v2:900:120")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    document = relationship("CareerKnowledgeDocument", back_populates="chunks")

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, UniqueConstraint

from app.db.base_class import Base


class InterviewSession(Base):
    """Persistent controls for an interview whose messages live in Qdrant."""

    __tablename__ = "interview_sessions"
    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", "chat_id", name="uq_interview_session_owner"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    tenant_id = Column(String(128), nullable=False, index=True)
    chat_id = Column(String(255), nullable=False, index=True)
    status = Column(String(16), nullable=False, default="active")
    paused_at = Column(DateTime, nullable=True)
    paused_seconds = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

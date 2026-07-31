from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text

from app.db.base_class import Base


class TrainingItem(Base):
    __tablename__ = "training_items"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    source_type = Column(String(32), nullable=False, index=True)
    source_ref = Column(String(255), nullable=True)
    source_label = Column(String(255), nullable=False)
    question = Column(Text, nullable=False)
    focus_json = Column(Text, nullable=False, default="[]")
    reference_answer = Column(Text, nullable=False, default="")
    original_answer = Column(Text, nullable=False, default="")
    priority = Column(Integer, nullable=False, default=50)
    status = Column(String(16), nullable=False, default="active", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_score = Column(Float, nullable=True)
    due_at = Column(DateTime, nullable=True, index=True)
    job_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class TrainingAttempt(Base):
    __tablename__ = "training_attempts"

    id = Column(Integer, primary_key=True, index=True)
    training_item_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    answer = Column(Text, nullable=False)
    score = Column(Float, nullable=False)
    feedback = Column(Text, nullable=False)
    evaluation_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

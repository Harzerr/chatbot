from datetime import datetime
from sqlalchemy import Column, DateTime, Float, Integer, String
from app.db.base_class import Base


class AIRequestMetric(Base):
    __tablename__ = "ai_request_metrics"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=True, index=True)
    tenant_id = Column(String(128), nullable=True, index=True)
    operation = Column(String(64), nullable=False, index=True)
    model = Column(String(128), nullable=True)
    success = Column(Integer, nullable=False, default=1)
    latency_ms = Column(Float, nullable=False, default=0)
    retrieval_count = Column(Integer, nullable=False, default=0)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    estimated_cost_usd = Column(Float, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

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
    model_latency_ms = Column(Float, nullable=False, default=0)
    queue_wait_ms = Column(Float, nullable=False, default=0)
    retrieval_count = Column(Integer, nullable=False, default=0)
    evidence_retrieval_count = Column(Integer, nullable=False, default=0)
    evidence_context_chars = Column(Integer, nullable=False, default=0)
    evidence_cache_hit = Column(Integer, nullable=False, default=0)
    evidence_retrieval_method = Column(String(64), nullable=False, default="none")
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    cache_hit = Column(Integer, nullable=False, default=0)
    attempt = Column(Integer, nullable=False, default=1)
    estimated_cost_usd = Column(Float, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class ToolCallMetric(Base):
    __tablename__ = "tool_call_metrics"

    id = Column(Integer, primary_key=True)
    trace_id = Column(String(128), nullable=False, index=True)
    tool_call_id = Column(String(128), nullable=True, index=True)
    user_id = Column(Integer, nullable=True, index=True)
    tenant_id = Column(String(128), nullable=True, index=True)
    agent_name = Column(String(64), nullable=False, index=True)
    tool_name = Column(String(128), nullable=False, index=True)
    validation_stage = Column(String(32), nullable=False, default="passed")
    error_type = Column(String(128), nullable=True)
    schema_valid = Column(Integer, nullable=False, default=1)
    business_valid = Column(Integer, nullable=True)
    success = Column(Integer, nullable=False, default=1)
    timed_out = Column(Integer, nullable=False, default=0)
    retry_attempt = Column(Integer, nullable=False, default=0)
    auto_repair_attempted = Column(Integer, nullable=False, default=0)
    auto_repair_succeeded = Column(Integer, nullable=False, default=0)
    input_hash = Column(String(64), nullable=True, index=True)
    latency_ms = Column(Float, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

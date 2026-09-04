"""Tool Calling validation, execution and repair observability."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from app.db.session import AsyncSessionLocal
from app.models.ai_metrics import ToolCallMetric


def classify_tool_error(error: Any) -> tuple[str, str]:
    text = str(error or "").lower()
    if "timeout" in text or "timed out" in text:
        return "timeout", "timeout"
    if any(token in text for token in ("validationerror", "validation error", "field required", "missing", "unexpected keyword", "invalid argument", "type error")):
        return "schema", "schema_validation"
    if any(token in text for token in ("invalid url", "url must", "query cannot", "business validation")):
        return "business", "business_validation"
    return "execution", "tool_execution"


def _input_hash(value: Any) -> str | None:
    if value is None:
        return None
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    except TypeError:
        encoded = str(value).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass
class ToolCallObservation:
    tool_name: str
    tool_call_id: str | None = None
    input_hash: str | None = None
    started_at: float = field(default_factory=time.perf_counter)
    latency_ms: float = 0
    validation_stage: str = "passed"
    error_type: str | None = None
    schema_valid: int = 1
    business_valid: int | None = 1
    success: int = 1
    timed_out: int = 0
    retry_attempt: int = 0
    auto_repair_attempted: int = 0
    auto_repair_succeeded: int = 0


class ToolCallMetricsCollector(BaseCallbackHandler):
    """Collect tool lifecycle callbacks without storing raw tool arguments."""

    def __init__(self) -> None:
        self._observations: dict[str, ToolCallObservation] = {}

    @staticmethod
    def _tool_name(serialized: dict | None, kwargs: dict) -> str:
        return str(
            kwargs.get("name")
            or (serialized or {}).get("name")
            or (serialized or {}).get("id", ["unknown"])[-1]
            or "unknown"
        )

    def on_tool_start(self, serialized: dict, input_str: str, *, run_id, inputs: Any = None, **kwargs: Any) -> None:
        key = str(run_id)
        observation = ToolCallObservation(
            tool_name=self._tool_name(serialized, kwargs),
            tool_call_id=key,
            input_hash=_input_hash(inputs if inputs is not None else input_str),
        )
        self._observations[key] = observation

    def on_tool_end(self, output: Any, *, run_id, **kwargs: Any) -> None:
        key = str(run_id)
        observation = self._observations.setdefault(key, ToolCallObservation(tool_name=self._tool_name(None, kwargs), tool_call_id=key))
        observation.latency_ms = (time.perf_counter() - observation.started_at) * 1000
        if isinstance(output, dict) and (output.get("ok") is False or output.get("error")):
            observation.validation_stage, observation.error_type = classify_tool_error(output.get("error"))
            observation.schema_valid = 0 if observation.validation_stage == "schema" else 1
            observation.business_valid = 0 if observation.validation_stage == "business" else 1
            observation.success = 0
            observation.timed_out = int(observation.validation_stage == "timeout")

    def on_tool_error(self, error: BaseException, *, run_id, **kwargs: Any) -> None:
        key = str(run_id)
        observation = self._observations.setdefault(key, ToolCallObservation(tool_name=self._tool_name(None, kwargs), tool_call_id=key))
        observation.latency_ms = (time.perf_counter() - observation.started_at) * 1000
        observation.validation_stage, observation.error_type = classify_tool_error(error)
        observation.schema_valid = 0 if observation.validation_stage == "schema" else 1
        observation.business_valid = 0 if observation.validation_stage == "business" else 1
        observation.success = 0
        observation.timed_out = int(observation.validation_stage == "timeout")

    def observations(self) -> list[ToolCallObservation]:
        observations = list(self._observations.values())
        observations.sort(key=lambda item: item.started_at)
        failed_by_tool: set[str] = set()
        for observation in observations:
            if not observation.success:
                failed_by_tool.add(observation.tool_name)
                continue
            if observation.tool_name in failed_by_tool:
                observation.auto_repair_attempted = 1
                observation.auto_repair_succeeded = 1
        return observations


async def record_tool_call_metrics(
    observations: list[ToolCallObservation],
    *,
    trace_id: str,
    agent_name: str,
    user_id: int | None = None,
    tenant_id: str | None = None,
) -> None:
    if not observations:
        return
    try:
        async with AsyncSessionLocal() as session:
            session.add_all(
                ToolCallMetric(
                    trace_id=trace_id,
                    tool_call_id=item.tool_call_id,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    agent_name=agent_name,
                    tool_name=item.tool_name,
                    validation_stage=item.validation_stage,
                    error_type=item.error_type,
                    schema_valid=item.schema_valid,
                    business_valid=item.business_valid,
                    success=item.success,
                    timed_out=item.timed_out,
                    retry_attempt=item.retry_attempt,
                    auto_repair_attempted=item.auto_repair_attempted,
                    auto_repair_succeeded=item.auto_repair_succeeded,
                    input_hash=item.input_hash,
                    latency_ms=item.latency_ms,
                )
                for item in observations
            )
            await session.commit()
    except Exception:
        # Observability must never break the user request.
        return


def summarize_tool_call_metrics(rows: list[Any]) -> dict[str, Any]:
    total = len(rows)
    schema_errors = sum(row.validation_stage == "schema" for row in rows)
    business_errors = sum(row.validation_stage == "business" for row in rows)
    execution_errors = sum(row.validation_stage == "execution" for row in rows)
    timeouts = sum(bool(row.timed_out) for row in rows)
    successes = sum(bool(row.success) for row in rows)
    repair_attempts = sum(bool(row.auto_repair_attempted) for row in rows)
    repair_successes = sum(bool(row.auto_repair_succeeded) for row in rows)
    latencies = sorted(float(row.latency_ms or 0) for row in rows)
    p95_index = min(len(latencies) - 1, max(0, int(len(latencies) * 0.95) - 1)) if latencies else 0

    def rate(value: int, denominator: int = total) -> float:
        return round(value / denominator, 4) if denominator else 0.0

    return {
        "total_calls": total,
        "success_rate": rate(successes),
        "schema_error_rate": rate(schema_errors),
        "business_error_rate": rate(business_errors),
        "execution_error_rate": rate(execution_errors),
        "timeout_rate": rate(timeouts),
        "auto_repair_attempts": repair_attempts,
        "auto_repair_successes": repair_successes,
        "auto_repair_success_rate": rate(repair_successes, repair_attempts),
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0,
        "p95_latency_ms": round(latencies[p95_index], 1) if latencies else 0,
    }

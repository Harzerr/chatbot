"""Versioned cache for deterministic interview evaluation requests."""

import json

from app.core.config import settings
from app.schemas.evaluation import EvaluationRequest
from app.services.interview_assessment import ASSESSMENT_VERSION
from app.services.redis_cache import RedisCache, stable_cache_key


def evaluation_cache_key(request: EvaluationRequest) -> str:
    payload = request.model_dump(mode="json")
    return stable_cache_key(
        "evaluation-result",
        [
            getattr(settings, "EVALUATION_CACHE_VERSION", "evaluation-v1"),
            ASSESSMENT_VERSION,
            settings.EVALUATION_LLM_MODEL,
            payload,
        ],
    )


def get_cached_evaluation(request: EvaluationRequest, cache: RedisCache | None = None) -> dict | None:
    cache = cache or RedisCache()
    value = cache.get_text(evaluation_cache_key(request))
    if value is None:
        return None
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def set_cached_evaluation(
    request: EvaluationRequest,
    result: dict,
    cache: RedisCache | None = None,
) -> bool:
    if result.get("evaluation_mode") != "llm":
        return False
    cache = cache or RedisCache()
    return cache.set_text(
        evaluation_cache_key(request),
        json.dumps(result, ensure_ascii=False, separators=(",", ":")),
        getattr(settings, "EVALUATION_CACHE_TTL_SECONDS", 86400),
    )

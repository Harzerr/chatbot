from collections.abc import Mapping
from typing import Any


def _as_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def extract_token_usage(message: Any) -> dict[str, int]:
    """Normalize usage metadata from LangChain/OpenAI-compatible responses."""
    if message is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    usage: Any = getattr(message, "usage_metadata", None)
    response_metadata = getattr(message, "response_metadata", None) or {}
    if not usage and isinstance(response_metadata, Mapping):
        usage = (
            response_metadata.get("token_usage")
            or response_metadata.get("usage")
            or response_metadata.get("usage_metadata")
        )
    if not isinstance(usage, Mapping):
        usage = {}

    prompt_tokens = _as_int(usage.get("prompt_tokens") or usage.get("input_tokens"))
    completion_tokens = _as_int(
        usage.get("completion_tokens") or usage.get("output_tokens")
    )
    total_tokens = _as_int(usage.get("total_tokens")) or prompt_tokens + completion_tokens
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def merge_token_usage(current: dict[str, int], incoming: dict[str, int]) -> dict[str, int]:
    """Keep the largest observed value, avoiding double counting stream chunks."""
    merged = {
        key: max(int(current.get(key, 0)), int(incoming.get(key, 0)))
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    }
    merged["total_tokens"] = max(
        merged["total_tokens"],
        merged["prompt_tokens"] + merged["completion_tokens"],
    )
    return merged

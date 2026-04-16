from __future__ import annotations

import time
from dataclasses import dataclass

from langchain_openai import OpenAIEmbeddings

from app.core.config import settings
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class EmbeddingConfig:
    model: str
    api_key: str
    base_url: str
    dimensions: int


def _normalize_model_name(model: str, use_openrouter: bool) -> str:
    normalized = (model or "text-embedding-3-small").strip()
    if use_openrouter:
        return normalized if normalized.startswith("openai/") else f"openai/{normalized}"
    return normalized.split("/", 1)[1] if normalized.startswith("openai/") else normalized


def resolve_embedding_config() -> EmbeddingConfig:
    has_openai_key = bool((settings.OPENAI_API_KEY or "").strip())

    if has_openai_key:
        return EmbeddingConfig(
            model=_normalize_model_name(settings.EMBEDDING_MODEL, use_openrouter=False),
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_API_BASE,
            dimensions=settings.EMBEDDING_DIMENSIONS,
        )

    return EmbeddingConfig(
        model=_normalize_model_name(settings.EMBEDDING_MODEL, use_openrouter=True),
        api_key=settings.OPENROUTER_API_KEY,
        base_url=settings.OPENROUTER_API_BASE,
        dimensions=settings.EMBEDDING_DIMENSIONS,
    )


class ResilientOpenAIEmbeddings(OpenAIEmbeddings):
    def _with_retry(self, func, *args, **kwargs):
        retries = max(0, settings.EMBEDDING_MAX_RETRIES)
        last_error: Exception | None = None

        for attempt in range(retries + 1):
            try:
                result = func(*args, **kwargs)
                if not result:
                    raise ValueError("embedding response is empty")
                return result
            except Exception as exc:
                last_error = exc
                message = str(exc).lower()
                is_retryable = (
                    "none" in message
                    or "timeout" in message
                    or "rate limit" in message
                    or "server error" in message
                    or "temporarily unavailable" in message
                )

                if attempt < retries and is_retryable:
                    sleep_s = settings.EMBEDDING_RETRY_INTERVAL * (attempt + 1)
                    logger.warning(
                        "Embedding request failed (%s/%s), retrying in %.2fs: %s",
                        attempt + 1,
                        retries + 1,
                        sleep_s,
                        exc,
                    )
                    time.sleep(sleep_s)
                    continue
                raise

        if last_error:
            raise last_error
        raise RuntimeError("embedding request failed unexpectedly")

    def embed_documents(self, texts, chunk_size=None):
        return self._with_retry(super().embed_documents, texts, chunk_size=chunk_size)

    def embed_query(self, text):
        return self._with_retry(super().embed_query, text)


def create_embeddings() -> ResilientOpenAIEmbeddings:
    config = resolve_embedding_config()
    return ResilientOpenAIEmbeddings(
        model=config.model,
        api_key=config.api_key,
        base_url=config.base_url,
        dimensions=config.dimensions,
    )


def get_mem0_embedder_config() -> dict:
    config = resolve_embedding_config()
    return {
        "provider": "openai",
        "config": {
            "model": config.model,
            "embedding_dims": config.dimensions,
            "api_key": config.api_key,
            "openai_base_url": config.base_url,
        },
    }


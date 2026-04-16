import os
from urllib.parse import urlsplit


HTTP_PROXY_ENV_KEYS = (
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "ALL_PROXY",
    "all_proxy",
)


def clean_optional(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return normalized or None


def get_env_http_proxy() -> tuple[str | None, str | None]:
    for key in HTTP_PROXY_ENV_KEYS:
        value = clean_optional(os.getenv(key))
        if value:
            return value, key
    return None, None


def redact_url(value: str | None) -> str:
    normalized = clean_optional(value)
    if not normalized:
        return ""

    parts = urlsplit(normalized)
    if parts.scheme and parts.hostname:
        port = f":{parts.port}" if parts.port else ""
        return f"{parts.scheme}://{parts.hostname}{port}"

    return "<set>"

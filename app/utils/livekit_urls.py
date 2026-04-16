from urllib.parse import urlsplit, urlunsplit


def _clean_livekit_url(url: str) -> str:
    return (url or "").strip().rstrip("/")


def first_livekit_url(*urls: str | None) -> str:
    for url in urls:
        normalized = _clean_livekit_url(url or "")
        if normalized:
            return normalized
    return ""


def _swap_scheme(url: str, *, default_scheme: str, scheme_map: dict[str, str]) -> str:
    normalized = _clean_livekit_url(url)
    if not normalized:
        return normalized

    parts = urlsplit(normalized)
    if not parts.scheme:
        return f"{default_scheme}://{normalized}"

    scheme = parts.scheme.lower()
    target_scheme = scheme_map.get(scheme, scheme)

    return urlunsplit(
        (target_scheme, parts.netloc, parts.path, parts.query, parts.fragment)
    )


def to_livekit_api_url(url: str) -> str:
    return _swap_scheme(
        url,
        default_scheme="https",
        scheme_map={
            "http": "http",
            "https": "https",
            "ws": "http",
            "wss": "https",
        },
    )


def to_livekit_rtc_url(url: str) -> str:
    return _swap_scheme(
        url,
        default_scheme="wss",
        scheme_map={
            "http": "ws",
            "https": "wss",
            "ws": "ws",
            "wss": "wss",
        },
    )

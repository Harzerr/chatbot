import asyncio
import ipaddress
import json
import socket
from typing import Annotated
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Request, status
from livekit import api
from livekit.api.twirp_client import TwirpError

from app.api.deps import get_current_user
from app.core.config import settings
from app.models.user import User as DBUser
from app.schemas.token import LivekitToken, VoiceInterviewTokenRequest
from app.utils.livekit_urls import first_livekit_url, to_livekit_api_url, to_livekit_rtc_url
from app.utils.logger import setup_logger
from app.utils.proxy import clean_optional, get_env_http_proxy, redact_url

logger = setup_logger(__name__)
router = APIRouter()


def _is_missing_setting(value: str | None, *, placeholders: tuple[str, ...] = ()) -> bool:
    if not value:
        return True
    normalized = value.strip()
    return normalized.strip("*") == "" or normalized in placeholders


def _missing_voice_agent_settings() -> list[str]:
    required_settings = {
        "LIVEKIT_URL": (settings.LIVEKIT_URL, ("livekit_url",)),
        "LIVEKIT_API_KEY": (settings.LIVEKIT_API_KEY, ()),
        "LIVEKIT_API_SECRET": (settings.LIVEKIT_API_SECRET, ()),
        "DEEPGRAM_API_KEY": settings.DEEPGRAM_API_KEY,
        "CARTESIA_API_KEY": settings.CARTESIA_API_KEY,
        "OPENROUTER_API_KEY": settings.OPENROUTER_API_KEY,
    }
    missing: list[str] = []
    for name, config in required_settings.items():
        if isinstance(config, tuple):
            value, placeholders = config
        else:
            value, placeholders = config, ()
        if _is_missing_setting(value, placeholders=placeholders):
            missing.append(name)
    return missing


def _livekit_http_proxy() -> tuple[str | None, str | None]:
    proxy_sources = (
        ("LIVEKIT_API_HTTP_PROXY", settings.LIVEKIT_API_HTTP_PROXY),
        ("LIVEKIT_AGENT_HTTP_PROXY", settings.LIVEKIT_AGENT_HTTP_PROXY),
    )
    for source, value in proxy_sources:
        proxy = clean_optional(value)
        if proxy:
            return proxy, source
    return None, None


def _is_livekit_not_found(exc: TwirpError) -> bool:
    return exc.status == 404 and exc.code == "not_found"


def _is_livekit_already_exists(exc: TwirpError) -> bool:
    return exc.status == 409 or exc.code == "already_exists"


def _mask_api_key(api_key: str | None) -> str:
    if not api_key:
        return "<empty>"
    if len(api_key) <= 4:
        return "*" * len(api_key)
    return f"{api_key[:2]}***{api_key[-2:]}(len={len(api_key)})"


def _url_host_port(url: str) -> tuple[str, int | None]:
    parsed = urlsplit(url)
    return parsed.hostname or "", parsed.port


def _is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    normalized = host.strip().lower()
    return normalized in {"localhost", "127.0.0.1", "::1"}


def _parse_hostname(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"//{raw}"
    try:
        return urlsplit(raw).hostname or ""
    except Exception:  # pragma: no cover - best-effort parsing
        return ""


def _is_private_or_link_local_host(host: str | None) -> bool:
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_link_local


def _replace_url_hostname(url: str, hostname: str) -> str:
    parsed = urlsplit(url)
    if not parsed.scheme:
        return url

    port = parsed.port
    port_part = f":{port}" if port is not None else ""
    if ":" in hostname and not hostname.startswith("["):
        netloc = f"[{hostname}]{port_part}"
    else:
        netloc = f"{hostname}{port_part}"

    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _resolve_livekit_public_url(base_public_url: str, http_request: Request) -> tuple[str, str]:
    current_host, _ = _url_host_port(base_public_url)
    candidate_hosts = [
        ("origin", _parse_hostname(http_request.headers.get("origin", ""))),
        ("x-forwarded-host", _parse_hostname(http_request.headers.get("x-forwarded-host", ""))),
        ("host", _parse_hostname(http_request.headers.get("host", ""))),
        ("client", http_request.client.host if http_request.client else ""),
    ]

    # 1) Loopback public URL must be rewritten for remote clients.
    for source, host in candidate_hosts:
        if host and not _is_loopback_host(host):
            if _is_loopback_host(current_host):
                return _replace_url_hostname(base_public_url, host), f"rewritten_from_{source}"
            break

    # 2) If configured public host is a private IP (e.g., old LAN IP) and the
    # requester uses another reachable host, rewrite to the request host.
    # This avoids regressions when the machine/network changes.
    for source, host in candidate_hosts:
        if not host or _is_loopback_host(host):
            continue
        if not current_host:
            return _replace_url_hostname(base_public_url, host), f"rewritten_from_{source}"
        if host.lower() == current_host.lower():
            return base_public_url, "configured"
        if _is_private_or_link_local_host(current_host):
            return _replace_url_hostname(base_public_url, host), f"rewritten_private_from_{source}"

    return base_public_url, "configured_loopback"


def _resolve_dns_snapshot(url: str) -> str:
    host, port = _url_host_port(url)
    if not host:
        return "<host-missing>"
    port_value = port or (443 if urlsplit(url).scheme in {"https", "wss"} else 80)
    try:
        infos = socket.getaddrinfo(host, port_value, proto=socket.IPPROTO_TCP)
        addresses = sorted({info[4][0] for info in infos})
        if not addresses:
            return f"{host}:{port_value} -> <no-address>"
        return f"{host}:{port_value} -> {', '.join(addresses[:4])}"
    except Exception as exc:  # pragma: no cover - best-effort diagnostic
        return f"{host}:{port_value} -> DNS lookup failed: {exc}"


def _extract_client_error_details(exc: aiohttp.ClientError) -> str:
    parts = [f"type={type(exc).__name__}", f"message={exc}"]
    conn_key = getattr(exc, "_conn_key", None)
    if conn_key is not None:
        parts.append(f"target={conn_key.host}:{conn_key.port}")
        parts.append(f"is_ssl={conn_key.is_ssl}")
    os_error = getattr(exc, "os_error", None)
    if os_error is not None:
        parts.append(f"os_error={os_error}")
    return "; ".join(parts)


async def _create_livekit_room_if_needed(
    livekit_api: api.LiveKitAPI,
    room_name: str,
    *,
    request_id: str,
) -> None:
    try:
        await livekit_api.room.create_room(
            api.CreateRoomRequest(name=room_name, empty_timeout=60 * 10, max_participants=2)
        )
        logger.info("[voice:%s] Created LiveKit room %s", request_id, room_name)
    except TwirpError as exc:
        if _is_livekit_already_exists(exc):
            logger.info("[voice:%s] LiveKit room %s already exists", request_id, room_name)
            return
        raise


async def _ensure_livekit_room(
    livekit_api: api.LiveKitAPI,
    room_name: str,
    *,
    request_id: str,
) -> None:
    rooms = await livekit_api.room.list_rooms(api.ListRoomsRequest(names=[room_name]))
    if any(room.name == room_name for room in rooms.rooms):
        logger.info("[voice:%s] Reusing existing LiveKit room %s", request_id, room_name)
        return
    await _create_livekit_room_if_needed(livekit_api, room_name, request_id=request_id)


async def _list_dispatches_with_room_retry(
    livekit_api: api.LiveKitAPI,
    room_name: str,
    *,
    request_id: str,
) -> list[api.AgentDispatch]:
    try:
        return await livekit_api.agent_dispatch.list_dispatch(room_name)
    except TwirpError as exc:
        if not _is_livekit_not_found(exc):
            raise
        logger.warning(
            "[voice:%s] Room %s not found while listing dispatches. Recreating room and continuing with no dispatches.",
            request_id,
            room_name,
        )
        await _create_livekit_room_if_needed(livekit_api, room_name, request_id=request_id)
        await asyncio.sleep(0.5)
        return []


async def _create_dispatch_with_room_retry(
    livekit_api: api.LiveKitAPI,
    room_name: str,
    *,
    request_id: str,
) -> None:
    request = api.CreateAgentDispatchRequest(agent_name="voice-assistant", room=room_name)
    try:
        await livekit_api.agent_dispatch.create_dispatch(request)
    except TwirpError as exc:
        if not _is_livekit_not_found(exc):
            raise
        logger.warning(
            "[voice:%s] Room %s not found while creating dispatch. Recreating room and retrying once.",
            request_id,
            room_name,
        )
        await _create_livekit_room_if_needed(livekit_api, room_name, request_id=request_id)
        await asyncio.sleep(0.5)
        await livekit_api.agent_dispatch.create_dispatch(request)


@router.post("/generate_token", response_model=LivekitToken)
async def chat_completions(
    http_request: Request,
    current_user: Annotated[DBUser, Depends(get_current_user)],
    request: VoiceInterviewTokenRequest | None = None,
) -> LivekitToken:
    request_id = uuid4().hex[:8]
    room_name = current_user.username
    request = request or VoiceInterviewTokenRequest()

    missing_settings = _missing_voice_agent_settings()
    if missing_settings:
        missing_list = ", ".join(missing_settings)
        logger.error("[voice:%s] Voice agent configuration missing: %s", request_id, missing_list)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"VOICE_CONFIG_MISSING (request_id={request_id})：语音服务配置缺失 {missing_list}。"
                "请补齐 .env 后重启 backend 与 livekit worker。"
            ),
        )

    http_proxy, http_proxy_source = _livekit_http_proxy()
    env_proxy, env_proxy_source = get_env_http_proxy()
    timeout = aiohttp.ClientTimeout(total=30, connect=10)
    session_kwargs: dict[str, object] = {"timeout": timeout}
    if http_proxy:
        session_kwargs.update({"trust_env": False, "proxy": http_proxy})
    else:
        # Do not inherit system proxy by default.
        # Local LiveKit deployments (127.0.0.1/private network) can be
        # accidentally routed to an unavailable proxy and fail with 503.
        session_kwargs["trust_env"] = False

    livekit_api_url = to_livekit_api_url(
        first_livekit_url(settings.LIVEKIT_INTERNAL_URL, settings.LIVEKIT_URL)
    )
    livekit_public_url = to_livekit_rtc_url(
        first_livekit_url(settings.LIVEKIT_PUBLIC_URL, settings.LIVEKIT_URL)
    )
    livekit_public_url, public_url_source = _resolve_livekit_public_url(
        livekit_public_url, http_request
    )
    client_host = http_request.client.host if http_request.client else "<unknown>"
    origin = http_request.headers.get("origin", "")

    logger.info(
        "[voice:%s] generate_token start user_id=%s username=%s room=%s client_host=%s origin=%s api_url=%s public_url=%s public_url_source=%s api_key=%s trust_env=%s explicit_proxy=%s env_proxy=%s",
        request_id,
        current_user.id,
        current_user.username,
        room_name,
        client_host,
        origin,
        livekit_api_url,
        livekit_public_url,
        public_url_source,
        _mask_api_key(settings.LIVEKIT_API_KEY),
        session_kwargs.get("trust_env"),
        f"{http_proxy_source}={redact_url(http_proxy)}" if http_proxy else "<none>",
        f"{env_proxy_source}={redact_url(env_proxy)}" if env_proxy else "<none>",
    )

    session = aiohttp.ClientSession(**session_kwargs)
    try:
        async with api.LiveKitAPI(
            url=livekit_api_url,
            api_key=settings.LIVEKIT_API_KEY,
            api_secret=settings.LIVEKIT_API_SECRET,
            session=session,
        ) as livekit_api:
            await _ensure_livekit_room(livekit_api, room_name, request_id=request_id)
            existing_dispatches = await _list_dispatches_with_room_retry(
                livekit_api, room_name, request_id=request_id
            )
            if existing_dispatches:
                logger.info(
                    "[voice:%s] Found %s stale dispatch(es) in room %s, deleting before new dispatch",
                    request_id,
                    len(existing_dispatches),
                    room_name,
                )
            for dispatch in existing_dispatches:
                await livekit_api.agent_dispatch.delete_dispatch(dispatch.id, room_name)
                logger.info(
                    "[voice:%s] Deleted dispatch id=%s room=%s agent=%s",
                    request_id,
                    dispatch.id,
                    room_name,
                    dispatch.agent_name,
                )
            await _create_dispatch_with_room_retry(livekit_api, room_name, request_id=request_id)
            logger.info("[voice:%s] Created fresh voice-assistant dispatch for room %s", request_id, room_name)
    except aiohttp.ClientError as exc:
        dns_snapshot = _resolve_dns_snapshot(livekit_api_url)
        logger.error(
            "[voice:%s] LiveKit network failure while generating token. api_url=%s dns=%s details=%s",
            request_id,
            livekit_api_url,
            dns_snapshot,
            _extract_client_error_details(exc),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"VOICE_LIVEKIT_NETWORK_ERROR (request_id={request_id})：后端无法连接 LiveKit API（{livekit_api_url}）。"
                "请检查 LIVEKIT_URL/LIVEKIT_INTERNAL_URL、代理、防火墙与 DNS。"
                f"DNS 快照：{dns_snapshot}"
            ),
        ) from exc
    except TwirpError as exc:
        logger.error(
            "[voice:%s] LiveKit Twirp error while generating token. status=%s code=%s message=%s api_url=%s",
            request_id,
            exc.status,
            exc.code,
            exc.message,
            livekit_api_url,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"VOICE_LIVEKIT_TWIRP_ERROR (request_id={request_id})：status={exc.status}, code={exc.code}, "
                f"message={exc.message}。请检查 LIVEKIT_API_KEY/LIVEKIT_API_SECRET 与 worker 的 agent_name。"
            ),
        ) from exc
    except Exception as exc:
        logger.error(
            "[voice:%s] Unexpected error while generating LiveKit token: %s",
            request_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"VOICE_INIT_FAILED (request_id={request_id})：语音初始化发生未知异常。"
                "请检查 backend.log 与 livekit.log。"
            ),
        ) from exc
    finally:
        await session.close()

    voice_chat_id = request.chat_id or f"voice-{current_user.username}-{uuid4().hex[:10]}"
    voice_context = {
        "chat_id": voice_chat_id,
        "interview_role": request.interview_role or current_user.target_role or "Web Frontend Engineer",
        "interview_level": request.interview_level or "mid",
        "interview_type": request.interview_type or "round-1",
        "target_company": request.target_company or "",
        "jd_content": request.jd_content or "",
    }
    participant_attributes = {
        "chat_id": voice_context["chat_id"],
        "interview_role": voice_context["interview_role"],
        "interview_level": voice_context["interview_level"],
        "interview_type": voice_context["interview_type"],
        "target_company": voice_context["target_company"],
    }

    token = (
        api.AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
        .with_identity(f"user_{current_user.username}")
        .with_name(f"User {current_user.username}")
        .with_metadata(json.dumps(voice_context, ensure_ascii=False))
        .with_attributes(participant_attributes)
        .with_grants(
            api.VideoGrants(room_join=True, room=room_name, can_publish=True, can_subscribe=True)
        )
        .to_jwt()
    )

    logger.info(
        "[voice:%s] generate_token success room=%s chat_id=%s public_url=%s public_url_source=%s",
        request_id,
        room_name,
        voice_chat_id,
        livekit_public_url,
        public_url_source,
    )

    return LivekitToken(token=token, room_name=room_name, livekit_url=livekit_public_url)

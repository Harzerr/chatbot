import argparse
import asyncio
import os
import sys
from uuid import uuid4

import aiohttp
from dotenv import load_dotenv


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from livekit import api

from app.core.config import settings
from app.utils.livekit_urls import first_livekit_url, to_livekit_api_url, to_livekit_rtc_url
from app.utils.proxy import clean_optional, get_env_http_proxy, redact_url


def _configured_api_proxy() -> tuple[str | None, str | None]:
    proxy_sources = (
        ("LIVEKIT_API_HTTP_PROXY", settings.LIVEKIT_API_HTTP_PROXY),
        ("LIVEKIT_AGENT_HTTP_PROXY", settings.LIVEKIT_AGENT_HTTP_PROXY),
    )

    for source, value in proxy_sources:
        proxy = clean_optional(value)
        if proxy:
            return proxy, source

    return None, None


def _require_settings() -> None:
    missing = []
    for name in (
        "LIVEKIT_URL",
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
        "DEEPGRAM_API_KEY",
        "CARTESIA_API_KEY",
        "OPENROUTER_API_KEY",
    ):
        value = clean_optional(getattr(settings, name, ""))
        if not value or value == "livekit_url" or value.strip("*") == "":
            missing.append(name)

    if missing:
        raise RuntimeError(f"Missing required settings: {', '.join(missing)}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Create a minimal LiveKit voice demo room and user token.")
    parser.add_argument("--room", default=f"voice-demo-{uuid4().hex[:8]}")
    parser.add_argument("--identity", default=f"demo-user-{uuid4().hex[:6]}")
    parser.add_argument("--agent-name", default="voice-demo")
    parser.add_argument("--no-dispatch", action="store_true", help="Only create the room and token; do not dispatch an agent.")
    args = parser.parse_args()

    _require_settings()

    explicit_proxy, explicit_proxy_source = _configured_api_proxy()
    env_proxy, env_proxy_source = get_env_http_proxy()

    timeout = aiohttp.ClientTimeout(total=30, connect=10)
    session_kwargs = {"timeout": timeout}
    if explicit_proxy:
        session_kwargs.update({"trust_env": False, "proxy": explicit_proxy})
        print(f"[demo-token] using {explicit_proxy_source}={redact_url(explicit_proxy)}")
    else:
        session_kwargs["trust_env"] = True
        if env_proxy:
            print(f"[demo-token] honoring env proxy {env_proxy_source}={redact_url(env_proxy)}")
        else:
            print("[demo-token] no HTTP proxy configured")

    session = aiohttp.ClientSession(**session_kwargs)
    livekit_api_url = to_livekit_api_url(
        first_livekit_url(settings.LIVEKIT_INTERNAL_URL, settings.LIVEKIT_URL)
    )
    livekit_public_url = to_livekit_rtc_url(
        first_livekit_url(settings.LIVEKIT_PUBLIC_URL, settings.LIVEKIT_URL)
    )

    try:
        async with api.LiveKitAPI(
            url=livekit_api_url,
            api_key=settings.LIVEKIT_API_KEY,
            api_secret=settings.LIVEKIT_API_SECRET,
            session=session,
        ) as livekit_api:
            rooms = await livekit_api.room.list_rooms(api.ListRoomsRequest(names=[args.room]))
            if not any(room.name == args.room for room in rooms.rooms):
                await livekit_api.room.create_room(
                    api.CreateRoomRequest(
                        name=args.room,
                        empty_timeout=10 * 60,
                        max_participants=2,
                    )
                )
                print(f"[demo-token] created room {args.room}")
            else:
                print(f"[demo-token] room already exists {args.room}")

            if not args.no_dispatch:
                await livekit_api.agent_dispatch.create_dispatch(
                    api.CreateAgentDispatchRequest(
                        agent_name=args.agent_name,
                        room=args.room,
                    )
                )
                print(f"[demo-token] dispatched agent {args.agent_name}")
    finally:
        await session.close()

    token = (
        api.AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
        .with_identity(args.identity)
        .with_name("LiveKit Demo User")
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=args.room,
                can_publish=True,
                can_subscribe=True,
            )
        )
        .to_jwt()
    )

    print("")
    print("LiveKit voice demo values")
    print(f"  url:   {livekit_public_url}")
    print(f"  room:  {args.room}")
    print(f"  user:  {args.identity}")
    print(f"  token: {token}")
    print("")
    print("Run the demo agent in another terminal:")
    print("  python scripts/livekit_voice_demo_agent.py dev")


if __name__ == "__main__":
    asyncio.run(main())

import os
import sys

import httpx
import openai as openai_sdk
from dotenv import load_dotenv


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from livekit import rtc
from livekit.agents import Agent, AgentSession, JobContext, RoomInputOptions, WorkerOptions, cli
from livekit.plugins import cartesia, deepgram, noise_cancellation, openai as livekit_openai, silero

from app.core.config import settings
from app.utils.livekit_urls import first_livekit_url, to_livekit_rtc_url
from app.utils.proxy import clean_optional, get_env_http_proxy, redact_url


def _agent_http_proxy() -> tuple[str | None, str | None]:
    proxy = clean_optional(settings.LIVEKIT_AGENT_HTTP_PROXY)
    if proxy:
        return proxy, "LIVEKIT_AGENT_HTTP_PROXY"
    return None, None


def _build_llm(http_proxy: str | None):
    client_kwargs = {
        "timeout": httpx.Timeout(connect=15.0, read=10.0, write=5.0, pool=5.0),
        "follow_redirects": True,
        "trust_env": http_proxy is None,
    }
    if http_proxy:
        client_kwargs["proxy"] = http_proxy

    http_client = httpx.AsyncClient(**client_kwargs)
    openai_client = openai_sdk.AsyncClient(
        api_key=settings.OPENROUTER_API_KEY,
        base_url=settings.OPENROUTER_API_BASE,
        max_retries=0,
        http_client=http_client,
    )
    return livekit_openai.LLM(model=settings.LLM_MODEL, client=openai_client)


class DemoAssistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "你是一个 LiveKit 语音链路 demo 助手。请始终用简短中文回复，"
                "先确认你能听到用户，然后围绕用户刚说的话自然追问一句。"
            )
        )


async def entrypoint(ctx: JobContext):
    print(f"[demo-agent] job accepted for room={ctx.room.name}", flush=True)

    rtc_config = None
    if settings.LIVEKIT_AGENT_RTC_RELAY_ONLY:
        rtc_config = rtc.RtcConfiguration(
            ice_transport_type=rtc.IceTransportType.TRANSPORT_RELAY,
        )
        print("[demo-agent] RTC relay-only mode enabled", flush=True)

    await ctx.connect(rtc_config=rtc_config)
    print(f"[demo-agent] connected to room={ctx.room.name}", flush=True)

    http_proxy, _ = _agent_http_proxy()
    env_proxy, _ = get_env_http_proxy()
    session = AgentSession(
        stt=deepgram.STT(
            model="nova-3",
            language=settings.DEEPGRAM_LANGUAGE,
            api_key=settings.DEEPGRAM_API_KEY,
        ),
        llm=_build_llm(http_proxy or env_proxy),
        tts=cartesia.TTS(
            model="sonic-2",
            language=settings.CARTESIA_LANGUAGE,
            voice=settings.CARTESIA_VOICE_ID,
            api_key=settings.CARTESIA_API_KEY,
        ),
        vad=silero.VAD.load(),
    )

    await session.start(
        room=ctx.room,
        agent=DemoAssistant(),
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )
    await session.say("你好，我是 LiveKit 语音 demo。可以听到的话，请随便说一句话。", add_to_chat_ctx=True)


if __name__ == "__main__":
    http_proxy, http_proxy_source = _agent_http_proxy()
    env_proxy, env_proxy_source = get_env_http_proxy()
    resolved_http_proxy = http_proxy or env_proxy
    rtc_url = to_livekit_rtc_url(
        first_livekit_url(settings.LIVEKIT_INTERNAL_URL, settings.LIVEKIT_URL)
    )
    os.environ["LIVEKIT_URL"] = rtc_url

    if http_proxy:
        print(f"[demo-agent] using {http_proxy_source}={redact_url(http_proxy)}", flush=True)
    elif env_proxy:
        print(f"[demo-agent] honoring env proxy {env_proxy_source}={redact_url(env_proxy)}", flush=True)
    else:
        print("[demo-agent] no HTTP proxy configured", flush=True)

    worker_options = {
        "entrypoint_fnc": entrypoint,
        "agent_name": "voice-demo",
        "ws_url": rtc_url,
    }
    if resolved_http_proxy:
        worker_options["http_proxy"] = resolved_http_proxy

    cli.run_app(WorkerOptions(**worker_options))

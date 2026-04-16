import os
import sys
import json
import asyncio

from dotenv import load_dotenv
from sqlalchemy import select
import httpx
import openai as openai_sdk

# Add the project root directory to the Python path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, PROJECT_ROOT)
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from livekit.agents import (
    Agent,
    AgentSession,
    APIConnectOptions,
    JobContext,
    RoomInputOptions,
    WorkerOptions,
    cli
)
from livekit.agents.voice.agent_session import SessionConnectOptions

from livekit import rtc
from livekit.plugins import noise_cancellation, silero, deepgram, cartesia, openai as livekit_openai
from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.user import User
from app.utils.logger import setup_logger
from app.utils.livekit_urls import first_livekit_url, to_livekit_rtc_url

logger = setup_logger(__name__)
_voice_ai_support = None
OPENING_QUESTION_TIMEOUT_SECONDS = 12

_PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def _disable_proxy_environment() -> None:
    removed_keys = [
        key
        for key in _PROXY_ENV_KEYS
        if os.environ.pop(key, None)
    ]
    if removed_keys:
        logger.info(
            "Voice agent direct-connection mode ignored proxy environment variables: %s",
            ", ".join(removed_keys),
        )


def _agent_rtc_relay_only() -> bool:
    return settings.LIVEKIT_AGENT_RTC_RELAY_ONLY


def _build_openai_llm():
    client_kwargs = {
        "timeout": httpx.Timeout(connect=15.0, read=5.0, write=5.0, pool=5.0),
        "follow_redirects": True,
        "limits": httpx.Limits(
            max_connections=50,
            max_keepalive_connections=50,
            keepalive_expiry=120,
        ),
        "trust_env": False,
    }

    http_client = httpx.AsyncClient(**client_kwargs)
    openai_client = openai_sdk.AsyncClient(
        api_key=settings.OPENROUTER_API_KEY,
        base_url=settings.OPENROUTER_API_BASE,
        max_retries=0,
        http_client=http_client,
    )
    return livekit_openai.LLM(
        model=settings.LLM_MODEL,
        client=openai_client,
    )


def _missing_voice_agent_settings() -> list[str]:
    required_settings = {
        "DEEPGRAM_API_KEY": settings.DEEPGRAM_API_KEY,
        "CARTESIA_API_KEY": settings.CARTESIA_API_KEY,
        "OPENROUTER_API_KEY": settings.OPENROUTER_API_KEY,
    }
    return [
        name
        for name, value in required_settings.items()
        if not value or value.strip("*") == ""
    ]


def _get_voice_ai_support():
    global _voice_ai_support
    if _voice_ai_support is None:
        from app.agent.chat_agent import AISupport
        from app.services.vector_store import MultiTenantVectorStore

        _voice_ai_support = AISupport(MultiTenantVectorStore())
    return _voice_ai_support


async def _get_voice_ai_support_async():
    """Initialize AISupport in a worker thread to avoid blocking the event loop."""
    return await asyncio.to_thread(_get_voice_ai_support)


def _build_profile_resume_context(user: User) -> str:
    summary_lines = [
        f"姓名：{user.full_name or '未填写'}",
        f"邮箱：{user.email or '未填写'}",
        f"电话：{user.phone or '未填写'}",
        f"目标岗位：{user.target_role or '未填写'}",
        f"工作年限：{user.years_of_experience or 0} 年",
    ]
    if user.bio:
        summary_lines.append(f"个人简介：{user.bio}")

    resume_text = (user.resume_text or "").strip()
    return "候选人个人档案：\n" + "\n".join(summary_lines) + "\n\n候选人简历内容：\n" + resume_text


def _load_voice_interview_context(participant) -> dict[str, str]:
    metadata = {}
    raw_metadata = getattr(participant, "metadata", "") or ""
    raw_attributes = getattr(participant, "attributes", {}) or {}

    if raw_metadata:
        try:
            parsed = json.loads(raw_metadata)
            if isinstance(parsed, dict):
                metadata.update({str(key): value for key, value in parsed.items() if value is not None})
        except json.JSONDecodeError:
            logger.warning("Failed to parse participant metadata JSON: %s", raw_metadata)

    metadata.update({str(key): value for key, value in raw_attributes.items() if value is not None})
    return metadata


async def _get_user_by_room_name(room_name: str) -> User | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.username == room_name))
        return result.scalar_one_or_none()

class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="""你是一位专业、友好、耐心的中文 AI 面试官。
请始终使用中文交流，一次只问一个问题，回答简洁清晰。
围绕候选人的岗位能力、项目经验、技术基础和问题分析能力追问。
如果候选人回答不完整，请温和追问背景、方案、权衡和结果。
不要闲聊，保持正式面试语境。"""
        )


async def entrypoint(ctx: JobContext):
    _disable_proxy_environment()
    logger.info(
        "Starting voice agent for room=%s relay_only=%s turn_detection=%s",
        ctx.room.name,
        settings.LIVEKIT_AGENT_RTC_RELAY_ONLY,
        settings.LIVEKIT_ENABLE_TURN_DETECTION,
    )
    missing_settings = _missing_voice_agent_settings()
    if missing_settings:
        missing_list = ", ".join(missing_settings)
        logger.error("Voice agent configuration missing: %s", missing_list)
        raise RuntimeError(f"Voice agent configuration missing: {missing_list}")

    logger.info(
        "Voice agent config loaded: llm_model=%s, deepgram_language=%s, cartesia_language=%s, cartesia_voice_id=%s",
        settings.LLM_MODEL,
        settings.DEEPGRAM_LANGUAGE,
        settings.CARTESIA_LANGUAGE,
        settings.CARTESIA_VOICE_ID,
    )
    logger.info("Voice agent provider HTTP clients connecting without HTTP proxy")

    rtc_config = None
    if _agent_rtc_relay_only():
        rtc_config = rtc.RtcConfiguration(
            ice_transport_type=rtc.IceTransportType.TRANSPORT_RELAY,
        )
        logger.info("LiveKit RTC relay-only mode enabled by LIVEKIT_AGENT_RTC_RELAY_ONLY")
    try:
        await ctx.connect(rtc_config=rtc_config)
    except Exception as exc:
        logger.error(
            "LiveKit worker failed to establish RTC room connection for room %s. "
            "This is usually a network or firewall issue between the worker host and LiveKit, not an interview-question generation failure. "
            "This voice agent is configured to connect directly without HTTP proxy; WebRTC media still needs ICE/TURN reachability. "
            "If this host is behind a restrictive network, try LIVEKIT_AGENT_RTC_RELAY_ONLY=true and verify LiveKit Cloud TURN/TCP/UDP connectivity: %s",
            ctx.room.name,
            exc,
            exc_info=True,
        )
        raise
    logger.info("LiveKit RTC room connection established for room %s", ctx.room.name)
    participant = await ctx.wait_for_participant()
    voice_context = _load_voice_interview_context(participant)
    logger.info(
        "Voice interview participant joined: identity=%s, chat_id=%s, role=%s, level=%s, type=%s",
        getattr(participant, "identity", ""),
        voice_context.get("chat_id"),
        voice_context.get("interview_role"),
        voice_context.get("interview_level"),
        voice_context.get("interview_type"),
    )

    turn_detection = None
    if settings.LIVEKIT_ENABLE_TURN_DETECTION:
        try:
            from livekit.plugins.turn_detector.multilingual import MultilingualModel

            turn_detection = MultilingualModel()
            logger.info("LiveKit multilingual turn detector enabled")
        except Exception as exc:
            logger.warning(
                "Failed to initialize multilingual turn detector; falling back to VAD-only mode: %s",
                exc,
                exc_info=True,
            )
    else:
        logger.info("LiveKit multilingual turn detector disabled; using VAD-only mode")

    session = AgentSession(
        stt=deepgram.STT(
            model="nova-3",
            language=settings.DEEPGRAM_LANGUAGE,
            api_key=settings.DEEPGRAM_API_KEY,
        ),
        llm=_build_openai_llm(),
        tts=cartesia.TTS(
            model="sonic-2",
            language=settings.CARTESIA_LANGUAGE,
            voice=settings.CARTESIA_VOICE_ID,
            api_key=settings.CARTESIA_API_KEY,
        ),
        vad=silero.VAD.load(),
        turn_detection=turn_detection,
        conn_options=SessionConnectOptions(
            stt_conn_options=APIConnectOptions(
                max_retry=settings.STT_CONNECT_MAX_RETRIES,
                retry_interval=settings.STT_CONNECT_RETRY_INTERVAL,
                timeout=settings.STT_CONNECT_TIMEOUT,
            )
        ),
    )

    @session.on("agent_state_changed")
    def on_agent_state_changed(event):
        logger.info("Voice agent state changed: %s -> %s", event.old_state, event.new_state)

    @session.on("user_input_transcribed")
    def on_user_input_transcribed(event):
        if event.transcript:
            logger.info(
                "User speech transcribed: final=%s, speaker_id=%s, text=%s",
                event.is_final,
                event.speaker_id,
                event.transcript,
            )

    await session.start(
        room=ctx.room,
        agent=Assistant(),
        room_input_options=RoomInputOptions(
            # LiveKit Cloud enhanced noise cancellation
            # - If self-hosting, omit this parameter
            # - For telephony applications, use `BVCTelephony` for best results
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )
    first_question = ""
    try:
        user = await _get_user_by_room_name(ctx.room.name)
        if user:
            from app.agent.langgraph_agent import initialize_graph

            async def _build_opening_question() -> str:
                await initialize_graph()
                ai_support = await _get_voice_ai_support_async()
                response = await ai_support.ask(
                    question="开始面试",
                    user_id=str(user.id),
                    chat_id=str(voice_context.get("chat_id") or f"voice-{ctx.room.name}"),
                    tenant_id=user.tenant_id,
                    interview_role=voice_context.get("interview_role") or user.target_role or "Web前端工程师",
                    interview_level=voice_context.get("interview_level") or "中级",
                    interview_type=voice_context.get("interview_type") or "一面",
                    target_company=voice_context.get("target_company") or None,
                    jd_content=voice_context.get("jd_content") or None,
                    resume_content=_build_profile_resume_context(user),
                )
                if response.get("messages"):
                    return str(response["messages"][0]).strip()
                return ""

            first_question = await asyncio.wait_for(
                _build_opening_question(),
                timeout=OPENING_QUESTION_TIMEOUT_SECONDS,
            )
    except asyncio.TimeoutError:
        logger.warning(
            "Opening interview question generation timed out after %ss; fallback to direct reply.",
            OPENING_QUESTION_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.error("Failed to generate opening interview question from AISupport: %s", exc, exc_info=True)

    if first_question:
        logger.info("Generated opening interview question from AISupport: %s", first_question[:120])
        await session.say(first_question, add_to_chat_ctx=True)
    else:
        await session.generate_reply(
            instructions="请用中文欢迎候选人进入语音面试，并直接提出第一个正式面试问题。"
        )


if __name__ == "__main__":
    _disable_proxy_environment()
    rtc_url = to_livekit_rtc_url(
        first_livekit_url(settings.LIVEKIT_INTERNAL_URL, settings.LIVEKIT_URL)
    )
    os.environ["LIVEKIT_URL"] = rtc_url
    logger.info(
        "LiveKit worker bootstrap: rtc_url=%s relay_only=%s turn_detection=%s",
        rtc_url,
        settings.LIVEKIT_AGENT_RTC_RELAY_ONLY,
        settings.LIVEKIT_ENABLE_TURN_DETECTION,
    )
    logger.info("LiveKit worker connecting without HTTP proxy")

    worker_options = {
        "entrypoint_fnc": entrypoint,
        "agent_name": "voice-assistant",
        "ws_url": rtc_url,
    }

    try:
        cli.run_app(
            WorkerOptions(**worker_options)
        )
    except Exception as exc:
        logger.error(
            "LiveKit worker process exited with unhandled error. ws_url=%s agent_name=%s error=%s",
            rtc_url,
            worker_options["agent_name"],
            exc,
            exc_info=True,
        )
        raise



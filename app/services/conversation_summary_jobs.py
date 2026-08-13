from __future__ import annotations

from datetime import datetime, timezone

from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.services.conversation_summary import (
    ConversationSummaryStore,
    build_summary_prompt,
    select_summary_source,
    summary_turns_since,
)
from app.services.vector_store import MultiTenantVectorStore
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


def _message_content(response) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, list):
        return "\n".join(
            str(item.get("text") or item)
            if isinstance(item, dict)
            else str(item)
            for item in content
        ).strip()
    return str(content or "").strip()


def _build_summary_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.MEMORY_LLM_MODEL,
        temperature=0,
        max_tokens=settings.CONVERSATION_SUMMARY_LLM_MAX_TOKENS,
        timeout=settings.CONVERSATION_SUMMARY_TIMEOUT,
        api_key=settings.OPENROUTER_API_KEY,
        base_url=settings.OPENROUTER_API_BASE,
    )


def process_conversation_summary_job(payload: dict) -> dict:
    tenant_id = str(payload["tenant_id"])
    user_id = str(payload["user_id"])
    chat_id = str(payload["chat_id"])
    store = ConversationSummaryStore()
    lock_token = store.acquire_lock(tenant_id, user_id, chat_id)
    if not lock_token:
        return {"status": "skipped", "reason": "summary_job_already_running"}

    try:
        vector_store = MultiTenantVectorStore(use_embedding=False)
        documents = vector_store.get_chat_by_id(
            chat_id=chat_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if len(documents) < settings.CONVERSATION_SUMMARY_TRIGGER_TURNS:
            return {"status": "skipped", "reason": "below_trigger", "turns": len(documents)}

        previous_summary = store.get(tenant_id, user_id, chat_id)
        source_documents = summary_turns_since(
            documents,
            previous_summary,
            settings.CONVERSATION_SUMMARY_RECENT_TURNS,
        )
        if previous_summary and len(source_documents) < settings.CONVERSATION_SUMMARY_BATCH_TURNS:
            return {"status": "skipped", "reason": "batch_not_ready", "new_turns": len(source_documents)}

        source_documents = select_summary_source(
            source_documents,
            settings.CONVERSATION_SUMMARY_SOURCE_MAX_CHARS,
        )
        if not source_documents:
            return {"status": "skipped", "reason": "no_complete_turns"}

        previous_text = str((previous_summary or {}).get("content") or "")
        response = _build_summary_llm().invoke(build_summary_prompt(previous_text, source_documents))
        summary_text = _message_content(response)
        if not summary_text:
            raise ValueError("conversation summary response is empty")

        historical_documents = documents[:-max(1, settings.CONVERSATION_SUMMARY_RECENT_TURNS)]
        covered_until = str(historical_documents[-1].get("timestamp") or "")
        summary = {
            "schema_version": 1,
            "content": summary_text,
            "covered_until": covered_until,
            "covered_turn_count": len(historical_documents),
            "source_turn_count": len(source_documents),
            "version": int((previous_summary or {}).get("version") or 0) + 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "model": settings.MEMORY_LLM_MODEL,
        }
        store.save(tenant_id, user_id, chat_id, summary)
        logger.info(
            "Conversation summary updated: chat_id=%s version=%s covered_turns=%s source_turns=%s",
            chat_id,
            summary["version"],
            summary["covered_turn_count"],
            summary["source_turn_count"],
        )
        return {
            "status": "completed",
            "version": summary["version"],
            "covered_turn_count": summary["covered_turn_count"],
            "source_turn_count": summary["source_turn_count"],
        }
    finally:
        store.release_lock(tenant_id, user_id, chat_id, lock_token)


def run_conversation_summary_job(payload: dict) -> dict:
    """RQ entrypoint for background rolling conversation summaries."""
    return process_conversation_summary_job(payload)

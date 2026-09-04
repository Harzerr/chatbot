from __future__ import annotations

from typing import Any


def _document_key(document: dict[str, Any]) -> str:
    return str(
        document.get("id")
        or f"{document.get('timestamp', '')}:{document.get('user_message', '')}"
    )


def _render_turn(document: dict[str, Any]) -> str:
    question = str(document.get("user_message") or "").strip()
    answer = str(document.get("assistant_message") or "").strip()
    return f" - User: {question}\n - Assistant: {answer}\n"


def select_history_context(
    all_documents: list[dict[str, Any]],
    relevant_documents: list[dict[str, Any]] | None = None,
    *,
    recent_turns: int = 4,
    relevant_turns: int = 6,
    max_chars: int = 12000,
) -> list[dict[str, Any]]:
    """Select complete conversation turns using recency and semantic relevance.

    All turns remain persisted in Qdrant. This function only chooses the context
    sent to the model; it never mutates or deletes conversation history.
    """
    if not all_documents:
        return []

    recent = list(all_documents[-max(1, recent_turns):])
    recent_keys = {_document_key(document) for document in recent}
    candidates = [
        document
        for document in (relevant_documents or [])
        if _document_key(document) not in recent_keys
    ]
    candidates.sort(
        key=lambda document: (
            float(document.get("_score") or 0.0),
            str(document.get("timestamp") or ""),
        ),
        reverse=True,
    )

    selected: list[dict[str, Any]] = []
    selected_keys: set[str] = set()
    used_chars = 0

    def add_if_fits(document: dict[str, Any]) -> bool:
        nonlocal used_chars
        key = _document_key(document)
        if key in selected_keys:
            return False
        rendered = _render_turn(document)
        if not rendered.strip():
            return False
        if selected and used_chars + len(rendered) > max_chars:
            return False
        if not selected and len(rendered) > max_chars:
            return False
        selected.append(document)
        selected_keys.add(key)
        used_chars += len(rendered)
        return True

    # Relevant historical turns are added first so older but on-topic details
    # are not displaced by a long recent answer.
    for document in candidates[: max(0, relevant_turns)]:
        add_if_fits(document)

    # Recent turns are always preferred for local conversational continuity.
    for document in reversed(recent):
        add_if_fits(document)

    return sorted(
        selected,
        key=lambda document: str(document.get("timestamp") or ""),
    )


def render_history_context(documents: list[dict[str, Any]]) -> str:
    if not documents:
        return ""
    return "\n".join(_render_turn(document).rstrip() for document in documents)

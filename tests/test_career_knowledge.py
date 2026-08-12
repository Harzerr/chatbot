from app.services.career_knowledge import (
    build_knowledge_context,
    edited_source_hash,
    parse_document,
)


def test_parse_text_document_and_infer_code_type():
    parsed = parse_document("interview.py", "text/x-python", b"print('ok')")

    assert parsed["document_type"] == "code"
    assert parsed["content_text"] == "print('ok')"
    assert parsed["metadata"]["parser"] == "utf-8"
    assert len(parsed["source_hash"]) == 64


def test_edit_hash_is_stable_for_same_text_and_changes_after_edit():
    original = edited_source_hash("FastAPI + RQ")
    assert original == edited_source_hash("FastAPI + RQ")
    assert original != edited_source_hash("FastAPI + Celery")


def test_context_prefers_relevant_document_and_obeys_limit():
    documents = [
        {"title": "前端文档", "document_type": "technical_doc", "content_text": "React 页面状态管理"},
        {"title": "RQ 评估代码", "document_type": "code", "content_text": "RQ worker 负责异步 evaluation job"},
    ]

    context = build_knowledge_context(documents, query="RQ worker", max_total_chars=180)

    assert "RQ 评估代码" in context
    assert len(context) <= 180

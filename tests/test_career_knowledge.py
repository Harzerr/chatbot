from app.services.career_knowledge import (
    build_cached_knowledge_context,
    build_evidence_pack,
    build_knowledge_context,
    edited_source_hash,
    parse_document,
    retrieve_knowledge_chunks,
    split_knowledge_document,
    evidence_context_stats,
)
from app.core.config import settings
from unittest.mock import patch


class FakeCache:
    def __init__(self):
        self.values = {}
        self.writes = 0

    def get_text(self, key):
        return self.values.get(key)

    def set_text(self, key, value, ttl_seconds):
        self.writes += 1
        self.values[key] = value
        return True


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


def test_retrieval_returns_relevant_late_markdown_section_with_provenance():
    document = {
        "id": 17,
        "fact_id": 42,
        "title": "面试平台技术文档",
        "content_text": (
            "# 项目概述\n普通项目背景和业务说明。\n\n"
            "# 评估链路\n使用 Judge0 执行代码，保存编译状态、运行状态和超时结果。"
        ),
    }

    chunks = retrieve_knowledge_chunks([document], query="Judge0 超时", max_chunks=2)

    assert chunks
    assert any("Judge0" in item["text"] for item in chunks)
    assert chunks[0]["fact_id"] == 42
    assert chunks[0]["chunk_id"].startswith("17:")
    assert chunks[0]["evidence_id"]


def test_long_chunk_uses_overlap_to_preserve_boundary_context():
    document = {
        "id": 9,
        "title": "长技术文档",
        "content_text": "A" * 30 + "关键边界条件" + "B" * 30,
    }

    chunks = split_knowledge_document(document, max_chunk_chars=40, overlap_chars=10)

    assert len(chunks) >= 2
    assert all(len(chunk["text"]) <= 40 for chunk in chunks)
    assert any("关键边界条件" in chunk["text"] for chunk in chunks)


def test_retrieval_can_scope_evidence_to_one_career_fact():
    documents = [
        {"id": 1, "fact_id": 11, "title": "项目 A", "content_text": "Redis 队列重试方案"},
        {"id": 2, "fact_id": 22, "title": "项目 B", "content_text": "Redis 队列重试方案"},
    ]

    chunks = retrieve_knowledge_chunks(documents, query="Redis 重试", fact_id=22)

    assert chunks
    assert {item["fact_id"] for item in chunks} == {22}


def test_hybrid_retrieval_uses_semantic_rank_when_enabled():
    document = {
        "id": 17,
        "fact_id": 42,
        "title": "异步评估技术文档",
        "content_text": "# 队列设计\n使用 Redis 和 RQ 将评估任务放入后台队列。",
        "source_hash": "version-1",
    }
    fake_store = type("FakeCareerEvidenceStore", (), {
        "search": lambda self, **kwargs: [{
            "chunk_id": "17:0",
            "score": 0.91,
        }],
    })()

    with patch.object(settings, "CAREER_EVIDENCE_VECTOR_ENABLED", True), patch(
        "app.services.career_evidence_vector_store.CareerEvidenceVectorStore",
        return_value=fake_store,
    ):
        chunks = retrieve_knowledge_chunks(
            [document],
            query="如何把耗时工作放到后台",
            tenant_id="tenant-a",
            user_id="user-1",
        )

    assert chunks
    assert chunks[0]["retrieval_method"] == "hybrid_rrf"
    assert chunks[0]["semantic_score"] == 0.91


def test_semantic_retrieval_failure_falls_back_to_lexical():
    document = {
        "id": 17,
        "fact_id": 42,
        "title": "异步评估技术文档",
        "content_text": "# 队列设计\n使用 Redis 和 RQ 将评估任务放入后台队列。",
    }
    fake_store = type("FailingCareerEvidenceStore", (), {
        "search": lambda self, **kwargs: (_ for _ in ()).throw(ConnectionError("qdrant unavailable")),
    })()

    with patch.object(settings, "CAREER_EVIDENCE_VECTOR_ENABLED", True), patch(
        "app.services.career_evidence_vector_store.CareerEvidenceVectorStore",
        return_value=fake_store,
    ):
        chunks = retrieve_knowledge_chunks(
            [document],
            query="Redis RQ",
            tenant_id="tenant-a",
            user_id="user-1",
        )

    assert chunks
    assert chunks[0]["retrieval_method"] == "lexical_bm25_heading_boost"


def test_evidence_pack_contains_traceable_ids_and_bounded_context():
    pack = build_evidence_pack(
        [{"id": 1, "fact_id": 7, "title": "项目文档", "content_text": "# 队列\nRedis + RQ worker 负责重试。"}],
        query="RQ worker 重试",
        max_total_chars=300,
    )

    assert pack["version"] == "evidence-pack-v2"
    assert pack["retrieval_count"] == len(pack["evidence_ids"])
    assert pack["evidence_ids"]
    assert len(pack["context"]) <= 300


def test_context_budget_does_not_include_unrelated_document_body():
    documents = [
        {
            "id": 1,
            "fact_id": 1,
            "title": "无关项目",
            "content_text": "前端页面布局和颜色调整。" * 300,
        },
        {
            "id": 2,
            "fact_id": 2,
            "title": "异步任务项目",
            "content_text": "# 队列设计\nRedis + RQ Worker 负责异步任务和失败重试。",
        },
    ]

    context = build_knowledge_context(documents, query="RQ Worker 失败重试", max_total_chars=800)

    assert "异步任务项目" in context
    assert "Redis + RQ Worker" in context
    assert len(context) <= 800


def test_evidence_context_stats_exposes_only_auditable_counts():
    context = "用户上传的技术资料：\n[证据ID：1:0｜职业事实：2]\nRedis + RQ"

    stats = evidence_context_stats(context)

    assert stats == {
        "retrieval_count": 1,
        "context_chars": len(context),
        "retrieval_method": "lexical_bm25_heading_boost",
    }


def test_cached_context_reuses_same_document_version_and_query():
    cache = FakeCache()
    documents = [{"id": 1, "fact_id": 2, "title": "RQ", "content_text": "Redis RQ worker"}]

    first, first_hit = build_cached_knowledge_context(
        documents, "RQ", tenant_id="tenant-a", user_id="user-1", cache=cache
    )
    second, second_hit = build_cached_knowledge_context(
        documents, "RQ", tenant_id="tenant-a", user_id="user-1", cache=cache
    )

    assert first == second
    assert first_hit is False
    assert second_hit is True
    assert cache.writes == 1


def test_cached_context_invalidates_when_document_content_changes():
    cache = FakeCache()
    first_documents = [{"id": 1, "title": "RQ", "content_text": "Redis RQ worker"}]
    changed_documents = [{"id": 1, "title": "RQ", "content_text": "Redis RQ worker retry"}]

    build_cached_knowledge_context(first_documents, "RQ", tenant_id="tenant-a", user_id="user-1", cache=cache)
    _, cache_hit = build_cached_knowledge_context(
        changed_documents, "RQ", tenant_id="tenant-a", user_id="user-1", cache=cache
    )

    assert cache_hit is False
    assert cache.writes == 2

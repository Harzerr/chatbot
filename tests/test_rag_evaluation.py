from app.services.rag_evaluation import RetrievalEvaluationCase, evaluate_retrieval, percentile


def test_percentile_uses_nearest_rank():
    assert percentile([1, 2, 3, 4, 100], 95) == 100
    assert percentile([], 95) == 0


def test_retrieval_evaluation_reports_recall_mrr_and_latency():
    cases = [
        RetrievalEvaluationCase("case-a", "redis", frozenset({"doc-a"})),
        RetrievalEvaluationCase("case-b", "qdrant", frozenset({"doc-b"})),
    ]
    results = {
        "redis": [{"chunk_id": "doc-a"}, {"chunk_id": "noise"}],
        "qdrant": [{"chunk_id": "noise"}, {"chunk_id": "doc-b"}],
    }

    report = evaluate_retrieval(cases, lambda query, top_k: results[query], top_k=2)

    assert report["recall_at_k"] == 1.0
    assert report["hit_rate_at_k"] == 1.0
    assert report["mrr"] == 0.75
    assert report["latency_p95_ms"] >= 0

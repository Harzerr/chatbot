from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from time import perf_counter
from typing import Any


@dataclass(frozen=True)
class RetrievalEvaluationCase:
    case_id: str
    query: str
    relevant_ids: frozenset[str]


def percentile(values: list[float], percentile_value: float) -> float:
    """Return the nearest-rank percentile used by the retrieval SLO report."""
    if not values:
        return 0.0
    rank = max(1, math.ceil((percentile_value / 100) * len(values)))
    return sorted(values)[rank - 1]


def evaluate_retrieval(
    cases: Iterable[RetrievalEvaluationCase],
    retrieve: Callable[[str, int], list[dict[str, Any]]],
    *,
    top_k: int,
    id_field: str = "chunk_id",
) -> dict[str, Any]:
    """Measure relevance and latency without depending on one vector backend."""
    if top_k <= 0:
        raise ValueError("top_k must be positive")

    results = []
    latencies_ms = []
    recalls = []
    reciprocal_ranks = []
    hits = 0
    for case in cases:
        if not case.relevant_ids:
            raise ValueError(f"RAG evaluation case {case.case_id!r} has no relevance labels")
        started_at = perf_counter()
        retrieved = retrieve(case.query, top_k)[:top_k]
        latency_ms = (perf_counter() - started_at) * 1000
        retrieved_ids = [str(item.get(id_field) or "") for item in retrieved]
        matched = case.relevant_ids.intersection(retrieved_ids)
        recall = len(matched) / len(case.relevant_ids)
        first_relevant_rank = next(
            (index for index, item_id in enumerate(retrieved_ids, start=1) if item_id in case.relevant_ids),
            None,
        )
        reciprocal_rank = 1 / first_relevant_rank if first_relevant_rank else 0.0
        hits += int(bool(matched))
        recalls.append(recall)
        reciprocal_ranks.append(reciprocal_rank)
        latencies_ms.append(latency_ms)
        results.append({
            "case_id": case.case_id,
            "query": case.query,
            "relevant_ids": sorted(case.relevant_ids),
            "retrieved_ids": retrieved_ids,
            "recall": round(recall, 4),
            "reciprocal_rank": round(reciprocal_rank, 4),
            "latency_ms": round(latency_ms, 3),
        })

    case_count = len(results)
    return {
        "case_count": case_count,
        "top_k": top_k,
        "recall_at_k": round(sum(recalls) / case_count, 4) if case_count else 0.0,
        "hit_rate_at_k": round(hits / case_count, 4) if case_count else 0.0,
        "mrr": round(sum(reciprocal_ranks) / case_count, 4) if case_count else 0.0,
        "latency_avg_ms": round(sum(latencies_ms) / case_count, 3) if case_count else 0.0,
        "latency_p95_ms": round(percentile(latencies_ms, 95), 3),
        "cases": results,
    }

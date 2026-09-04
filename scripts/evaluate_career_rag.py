#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.career_knowledge import retrieve_knowledge_chunks
from app.services.rag_evaluation import RetrievalEvaluationCase, evaluate_retrieval


DEFAULT_GOLDEN_SET = PROJECT_ROOT / "tests" / "fixtures" / "career_rag_golden.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate career-document RAG relevance and latency")
    parser.add_argument("--golden-set", type=Path, default=DEFAULT_GOLDEN_SET)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--min-recall", type=float, default=0.9)
    parser.add_argument("--max-p95-ms", type=float, default=50.0)
    parser.add_argument("--details", action="store_true", help="Include every repeated case in JSON output")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = json.loads(args.golden_set.read_text(encoding="utf-8"))
    documents = payload.get("documents") or []
    base_cases = [
        RetrievalEvaluationCase(
            case_id=str(item["case_id"]),
            query=str(item["query"]),
            relevant_ids=frozenset(str(value) for value in item["relevant_chunk_ids"]),
        )
        for item in payload.get("cases") or []
    ]
    cases = [
        RetrievalEvaluationCase(
            case_id=f"{case.case_id}#{iteration + 1}",
            query=case.query,
            relevant_ids=case.relevant_ids,
        )
        for iteration in range(max(1, args.iterations))
        for case in base_cases
    ]

    report = evaluate_retrieval(
        cases,
        lambda query, top_k: retrieve_knowledge_chunks(
            documents,
            query=query,
            max_chunks=top_k,
            max_documents=top_k,
        ),
        top_k=args.top_k,
    )
    report["retrieval_mode"] = "hybrid_rrf_if_enabled_otherwise_lexical"
    report["golden_set"] = str(args.golden_set)
    if not args.details:
        report.pop("cases", None)
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if report["recall_at_k"] < args.min_recall or report["latency_p95_ms"] > args.max_p95_ms:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Compare fixed-window history with semantic selection and rolling summary context.

This is a deterministic architecture benchmark. It measures context size and
recall behavior without calling the external LLM, so it is safe to run offline.
Use production token/latency metrics separately for an end-to-end benchmark.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.conversation_context import render_history_context, select_history_context


OLD_FACT = "用户在第 1 轮确认：面试系统使用 Redis + RQ 处理异步任务。"


def make_documents(turn_count: int) -> list[dict]:
    documents = []
    for index in range(turn_count):
        user_message = OLD_FACT if index == 1 else f"用户回答第 {index} 轮，讨论了服务边界、异常处理和测试策略。"
        documents.append(
            {
                "id": f"turn-{index}",
                "timestamp": f"2026-08-13T00:{index // 60:02d}:{index % 60:02d}",
                "user_message": user_message,
                "assistant_message": (
                    f"面试官追问第 {index} 轮：请说明设计取舍、失败回退和可观测指标。"
                    " 这是用于压测上下文长度的补充文本。"
                ),
            }
        )
    return documents


def approximate_tokens(text: str) -> int:
    return (len(text) + 3) // 4


def legacy_context(documents: list[dict]) -> str:
    chunks = []
    for document in documents[-6:]:
        chunks.append(
            f"User: {document['user_message'][:800]}\n"
            f"Assistant: {document['assistant_message'][:1000]}"
        )
    return "\n".join(chunks)


def deterministic_rolling_summary(documents: list[dict]) -> str:
    historical = documents[:-4]
    return (
        "滚动摘要：已覆盖前 {count} 个完整问答轮次。\n"
        "关键事实：{fact}\n"
        "已讨论主题：上下文管理、异步任务、异常回退、数据隔离和测试验证。"
    ).format(count=len(historical), fact=OLD_FACT)


def benchmark(turn_count: int) -> dict:
    documents = make_documents(turn_count)
    semantic_candidates = [documents[1], *documents[:-4][-6:]]
    relevant_documents = [
        dict(document, _score=0.99 - index * 0.01)
        for index, document in enumerate({document["id"]: document for document in semantic_candidates}.values())
    ]
    legacy = legacy_context(documents)
    selected = select_history_context(
        documents,
        relevant_documents,
        recent_turns=4,
        relevant_turns=6,
        max_chars=12000,
    )
    current = render_history_context(selected)
    evidence = relevant_documents[:2]
    summary_docs = select_history_context(
        documents,
        evidence,
        recent_turns=4,
        relevant_turns=2,
        max_chars=12000,
    )
    summary_context = (
        deterministic_rolling_summary(documents)
        + "\n"
        + render_history_context(summary_docs)
    )

    return {
        "turns": turn_count,
        "legacy": {
            "chars": len(legacy),
            "approx_tokens": approximate_tokens(legacy),
            "old_fact_recalled": OLD_FACT in legacy,
        },
        "semantic": {
            "chars": len(current),
            "approx_tokens": approximate_tokens(current),
            "old_fact_recalled": OLD_FACT in current,
        },
        "rolling_summary": {
            "chars": len(summary_context),
            "approx_tokens": approximate_tokens(summary_context),
            "old_fact_recalled": OLD_FACT in summary_context,
        },
        "summary_vs_semantic_token_reduction_percent": round(
            (1 - approximate_tokens(summary_context) / max(1, approximate_tokens(current))) * 100,
            2,
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--turns", nargs="+", type=int, default=[8, 20, 40, 80])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = {"benchmark": "memory-context", "results": [benchmark(turns) for turns in args.turns]}
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

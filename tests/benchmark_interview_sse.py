import argparse
import asyncio
import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx
import psutil
from redis import Redis
from rq import Queue


def percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(len(ordered) * ratio)))
    return round(ordered[index], 2)


def backend_rss_mb(base_url: str) -> float | None:
    port = str(urlparse(base_url).port or (443 if urlparse(base_url).scheme == "https" else 80))
    total = 0
    for process in psutil.process_iter(["cmdline", "memory_info"]):
        try:
            command = " ".join(process.info.get("cmdline") or [])
            if "uvicorn" in command and "app.main:app" in command and f"--port {port}" in command:
                total += process.info["memory_info"].rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return round(total / 1024 / 1024, 2) if total else None


def queue_snapshot(redis_url: str, queue_name: str) -> dict:
    connection = Redis.from_url(redis_url)
    queue = Queue(queue_name, connection=connection)
    return {
        "queued": len(queue),
        "started": queue.started_job_registry.count,
        "failed": queue.failed_job_registry.count,
        "finished": queue.finished_job_registry.count,
    }


async def login(client: httpx.AsyncClient, username: str, password: str) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": username, "password": password},
    )
    response.raise_for_status()
    return response.json()["access_token"]


async def stream_request(
    client: httpx.AsyncClient,
    token: str,
    payload: dict,
    phase: str,
) -> dict:
    started_at = time.perf_counter()
    first_content_at = None
    content = ""
    chunks = 0
    status_code = None
    error = None
    try:
        async with client.stream(
            "POST",
            "/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            timeout=120,
        ) as response:
            status_code = response.status_code
            if response.status_code >= 400:
                error = (await response.aread()).decode("utf-8", errors="replace")[:500]
            else:
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = event.get("choices", [{}])[0].get("delta", {}).get("content")
                    if delta:
                        if first_content_at is None:
                            first_content_at = time.perf_counter()
                        content += str(delta)
                        chunks += 1
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    if status_code is not None and status_code < 400 and not content and error is None:
        error = "empty_sse_stream"

    finished_at = time.perf_counter()
    return {
        "phase": phase,
        "status_code": status_code,
        "success": not error and bool(content),
        "ttft_ms": round((first_content_at - started_at) * 1000, 2) if first_content_at else None,
        "total_ms": round((finished_at - started_at) * 1000, 2),
        "chunks": chunks,
        "content_chars": len(content),
        "error": error,
        "content_preview": content[:120],
    }


async def run_case(client, token, args, index: int) -> list[dict]:
    chat_id = f"load-test-{datetime.now().strftime('%Y%m%d%H%M%S')}-{index}-{uuid4().hex[:8]}"
    common = {
        "chat_id": chat_id,
        "interview_role": args.role,
        "interview_level": args.level,
        "interview_type": args.interview_type,
        "target_company": args.company,
        "jd_content": args.jd_content,
    }
    opening = await stream_request(
        client,
        token,
        {"user_message": "开始面试", **common},
        "opening",
    )
    if args.mode == "opening" or not opening["success"]:
        return [opening]
    await asyncio.sleep(args.persist_wait)
    answer = await stream_request(
        client,
        token,
        {
            "user_message": args.answer,
            **common,
        },
        "answer_and_queue_evaluation",
    )
    return [opening, answer]


def summarize(results: list[dict]) -> dict:
    successful = [item for item in results if item["success"]]
    summary = {
        "requests": len(results),
        "successes": len(successful),
        "failure_rate": round((len(results) - len(successful)) / len(results), 4) if results else 0,
        "ttft_ms": {},
        "total_ms": {},
    }
    for key in ("ttft_ms", "total_ms"):
        values = [item[key] for item in successful if item[key] is not None]
        summary[key] = {
            "avg": round(statistics.mean(values), 2) if values else None,
            "p50": percentile(values, 0.50),
            "p95": percentile(values, 0.95),
            "max": round(max(values), 2) if values else None,
        }
    return summary


async def main_async(args) -> dict:
    started_at = datetime.now(timezone.utc).isoformat()
    redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/1")
    before_queue = queue_snapshot(redis_url, args.queue_name)
    before_rss = backend_rss_mb(args.base_url)
    limits = httpx.Limits(max_connections=args.concurrency, max_keepalive_connections=args.concurrency)
    async with httpx.AsyncClient(base_url=args.base_url, limits=limits, trust_env=False) as client:
        token = await login(client, args.username, args.password)
        semaphore = asyncio.Semaphore(args.concurrency)

        async def guarded(index):
            async with semaphore:
                return await run_case(client, token, args, index)

        grouped = await asyncio.gather(*(guarded(index) for index in range(args.requests)))
    results = [item for group in grouped for item in group]
    await asyncio.sleep(args.queue_wait)
    after_queue = queue_snapshot(redis_url, args.queue_name)
    after_rss = backend_rss_mb(args.base_url)
    return {
        "started_at": started_at,
        "base_url": args.base_url,
        "mode": args.mode,
        "requests": args.requests,
        "concurrency": args.concurrency,
        "persist_wait_seconds": args.persist_wait,
        "queue_wait_seconds": args.queue_wait,
        "worker_assumption": args.worker_assumption,
        "resource": {"backend_rss_before_mb": before_rss, "backend_rss_after_mb": after_rss},
        "queue": {"before": before_queue, "after": after_queue},
        "summary": summarize(results),
        "results": results,
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Measure interview SSE TTFT, total latency and RQ evaluation queue behavior.")
    parser.add_argument("--base-url", default=os.getenv("BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--username", default=os.getenv("TEST_USERNAME"), required=not bool(os.getenv("TEST_USERNAME")))
    parser.add_argument("--password", default=os.getenv("TEST_PASSWORD"), required=not bool(os.getenv("TEST_PASSWORD")))
    parser.add_argument("--requests", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--mode", choices=("opening", "scenario"), default="scenario")
    parser.add_argument("--persist-wait", type=float, default=2.0)
    parser.add_argument("--queue-wait", type=float, default=5.0)
    parser.add_argument("--queue-name", default=os.getenv("EVALUATION_QUEUE_NAME", "interview_evaluation"))
    parser.add_argument("--worker-assumption", default="temporary RQ worker for interview_evaluation")
    parser.add_argument("--role", default="AI算法工程师")
    parser.add_argument("--level", default="中级")
    parser.add_argument("--interview-type", default="一面")
    parser.add_argument("--company", default="测试公司")
    parser.add_argument("--jd-content", default="负责 AI Agent、Python、FastAPI、Redis、RAG 和工程化落地。")
    parser.add_argument("--answer", default="我负责了后端接口、状态编排和异步任务设计，使用 Redis 和 RQ 将评估任务从主请求中拆分出去，并通过指标和日志验证流程。")
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    report = asyncio.run(main_async(args))
    output = args.output or Path("reports") / f"interview-sse-load-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "summary": report["summary"], "queue": report["queue"], "resource": report["resource"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

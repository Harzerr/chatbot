import argparse
import asyncio
import collections
import json
import math
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
    pids: set[int] = set()
    try:
        for connection in psutil.net_connections(kind="tcp"):
            address = connection.laddr
            if address and address.port == int(port) and connection.pid:
                pids.add(connection.pid)
    except (psutil.AccessDenied, psutil.Error, ValueError):
        pids.clear()

    processes: dict[int, psutil.Process] = {}
    for pid in pids:
        try:
            process = psutil.Process(pid)
            processes[pid] = process
            for child in process.children(recursive=True):
                processes[child.pid] = child
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not processes:
        # Fallback for environments where net_connections is restricted. The
        # command-line match is intentionally narrow to avoid summing unrelated
        # Python services on the same host.
        for process in psutil.process_iter(["cmdline"]):
            try:
                command = " ".join(process.info.get("cmdline") or [])
                if ("uvicorn" in command and "app.main:app" in command and f"--port {port}" in command) or (
                    command.endswith(" app.py") and "python" in command
                ):
                    processes[process.pid] = process
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    total = 0
    for process in processes.values():
        try:
            total += process.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return round(total / 1024 / 1024, 2) if total else None


def queue_snapshot(redis_url: str, queue_name: str) -> dict:
    connection = Redis.from_url(redis_url)
    queue = Queue(queue_name, connection=connection)
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
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
    trace_id: str,
    timeout: httpx.Timeout,
) -> dict:
    started_at = time.perf_counter()
    first_content_at = None
    content = ""
    chunks = 0
    event_count = 0
    done_received = False
    status_code = None
    error = None
    close_reason = None
    try:
        async with client.stream(
            "POST",
            "/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            timeout=timeout,
        ) as response:
            status_code = response.status_code
            if response.status_code >= 400:
                error = (await response.aread()).decode("utf-8", errors="replace")[:500]
                close_reason = "http_error"
            else:
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        done_received = True
                        close_reason = "done"
                        break
                    event_count += 1
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
        if isinstance(exc, httpx.TimeoutException):
            error = "stream_timeout"
            close_reason = "timeout"
        else:
            error = f"{type(exc).__name__}: {exc}"
            close_reason = "transport_error"

    if status_code is not None and status_code >= 400:
        outcome = "http_error"
    elif error == "stream_timeout":
        outcome = "stream_timeout"
    elif error and close_reason == "transport_error":
        outcome = "transport_error"
    elif status_code is not None and status_code < 400 and not content and error is None:
        error = "empty_sse_stream"
        close_reason = "empty_stream"
        outcome = "http_success_empty_stream"
    elif status_code is not None and status_code < 400 and content and not done_received and error is None:
        error = "stream_interrupted"
        close_reason = "missing_done"
        outcome = "stream_interrupted"
    elif error:
        outcome = "request_error"
    else:
        outcome = "http_success_stream_completed"

    finished_at = time.perf_counter()
    return {
        "phase": phase,
        "trace_id": trace_id,
        "chat_id": payload.get("chat_id"),
        "status_code": status_code,
        "success": outcome == "http_success_stream_completed",
        "outcome": outcome,
        "ttft_ms": round((first_content_at - started_at) * 1000, 2) if first_content_at else None,
        "total_ms": round((finished_at - started_at) * 1000, 2),
        "chunks": chunks,
        "event_count": event_count,
        "done_received": done_received,
        "stream_close_reason": close_reason,
        "content_chars": len(content),
        "error": error,
        "content_preview": content[:120],
    }


async def run_case(client, token, args, index: int) -> list[dict]:
    run_id = getattr(args, "run_id", None) or datetime.now().strftime("loadtest-%Y%m%d%H%M%S")
    trace_prefix = getattr(args, "trace_prefix", None) or run_id
    chat_id = f"{run_id}-user-{index}-{uuid4().hex[:8]}"
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
        f"{trace_prefix}-{index}-opening",
        args.request_timeout,
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
        f"{trace_prefix}-{index}-answer",
        args.request_timeout,
    )
    return [opening, answer]


def summarize(results: list[dict]) -> dict:
    successful = [item for item in results if item["success"]]
    outcomes = collections.Counter(item.get("outcome", "unknown") for item in results)
    summary = {
        "requests": len(results),
        "successes": len(successful),
        "failure_rate": round((len(results) - len(successful)) / len(results), 4) if results else 0,
        "outcomes": dict(sorted(outcomes.items())),
        "ttft_ms": {},
        "total_ms": {},
    }
    for key in ("ttft_ms", "total_ms"):
        values = [item[key] for item in successful if item[key] is not None]
        summary[key] = {
            "avg": round(statistics.mean(values), 2) if values else None,
            "p50": percentile(values, 0.50),
            "p95": percentile(values, 0.95),
            "p99": percentile(values, 0.99),
            "max": round(max(values), 2) if values else None,
        }
    return summary


async def sample_queue(
    redis_url: str,
    queue_name: str,
    interval_seconds: float,
    stop_event: asyncio.Event,
    samples: list[dict],
) -> None:
    while not stop_event.is_set():
        try:
            samples.append(await asyncio.to_thread(queue_snapshot, redis_url, queue_name))
        except Exception as exc:
            samples.append({"timestamp": datetime.now(timezone.utc).isoformat(), "error": repr(exc)})
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=max(0.1, interval_seconds))
        except asyncio.TimeoutError:
            continue


def summarize_queue(before: dict, after: dict, samples: list[dict]) -> dict:
    valid_samples = [sample for sample in samples if "queued" in sample]
    keys = ("queued", "started", "failed", "finished")
    deltas = {
        key: after.get(key, 0) - before.get(key, 0)
        for key in keys
    }
    return {
        "before": before,
        "after": after,
        "deltas": deltas,
        "max_queued": max((sample["queued"] for sample in valid_samples), default=0),
        "max_started": max((sample["started"] for sample in valid_samples), default=0),
        "sample_count": len(valid_samples),
        "drain_observed": bool(valid_samples) and valid_samples[-1]["queued"] == 0 and valid_samples[-1]["started"] == 0,
        "samples": samples,
    }


async def main_async(args) -> dict:
    started_at = datetime.now(timezone.utc).isoformat()
    started_monotonic = time.perf_counter()
    run_id = getattr(args, "run_id", None) or datetime.now().strftime("loadtest-%Y%m%d%H%M%S")
    args.run_id = run_id
    redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/1")
    before_queue = queue_snapshot(redis_url, args.queue_name)
    before_rss = backend_rss_mb(args.base_url)
    limits = httpx.Limits(max_connections=args.concurrency, max_keepalive_connections=args.concurrency)
    request_timeout = getattr(args, "request_timeout", 120.0)
    args.request_timeout = httpx.Timeout(
        request_timeout,
        connect=getattr(args, "connect_timeout", 10.0),
        read=getattr(args, "stream_idle_timeout", request_timeout),
    )
    arrival_rate = float(getattr(args, "arrival_rate", 0) or 0)
    duration_seconds = getattr(args, "duration_seconds", None)
    case_count = int(args.requests)
    if duration_seconds is not None:
        if arrival_rate <= 0:
            raise ValueError("duration_seconds requires arrival_rate > 0")
        case_count = max(1, math.ceil(arrival_rate * duration_seconds))

    queue_samples: list[dict] = []
    stop_queue_sampler = asyncio.Event()
    grouped: list[list[dict]] = []
    workload_duration_ms = 0.0
    queue_sampler = asyncio.create_task(sample_queue(
        redis_url,
        args.queue_name,
        float(getattr(args, "queue_sample_interval", 1.0)),
        stop_queue_sampler,
        queue_samples,
    ))
    try:
        async with httpx.AsyncClient(base_url=args.base_url, limits=limits, trust_env=False) as client:
            token = await login(client, args.username, args.password)
            semaphore = asyncio.Semaphore(args.concurrency)

            async def guarded(index):
                if arrival_rate > 0:
                    await asyncio.sleep(index / arrival_rate)
                async with semaphore:
                    return await run_case(client, token, args, index)

            grouped = await asyncio.gather(*(guarded(index) for index in range(case_count)))
            workload_duration_ms = round((time.perf_counter() - started_monotonic) * 1000, 2)
    finally:
        await asyncio.sleep(args.queue_wait)
        stop_queue_sampler.set()
        await queue_sampler
    results = [item for group in grouped for item in group]
    after_queue = queue_snapshot(redis_url, args.queue_name)
    after_rss = backend_rss_mb(args.base_url)
    finished_at = datetime.now(timezone.utc).isoformat()
    total_duration_ms = round((time.perf_counter() - started_monotonic) * 1000, 2)
    workload_seconds = workload_duration_ms / 1000
    return {
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": total_duration_ms,
        "workload_duration_ms": workload_duration_ms,
        "run_id": run_id,
        "base_url": args.base_url,
        "mode": args.mode,
        "requests": case_count,
        "concurrency": args.concurrency,
        "arrival_rate_cases_per_second": arrival_rate or None,
        "duration_seconds": duration_seconds,
        "persist_wait_seconds": args.persist_wait,
        "queue_wait_seconds": args.queue_wait,
        "worker_assumption": args.worker_assumption,
        "throughput": {
            "observed_requests_per_second": round(len(results) / workload_seconds, 3) if workload_seconds else 0,
            "successful_requests_per_second": round(sum(item["success"] for item in results) / workload_seconds, 3)
            if workload_seconds else 0,
        },
        "resource": {"backend_rss_before_mb": before_rss, "backend_rss_after_mb": after_rss},
        "queue": summarize_queue(before_queue, after_queue, queue_samples),
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
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--trace-prefix", default=None)
    parser.add_argument("--arrival-rate", type=float, default=0, help="Cases per second; use with --duration-seconds for Soak tests.")
    parser.add_argument("--duration-seconds", type=float, default=None)
    parser.add_argument("--mode", choices=("opening", "scenario"), default="scenario")
    parser.add_argument("--persist-wait", type=float, default=2.0)
    parser.add_argument("--queue-wait", type=float, default=5.0)
    parser.add_argument("--queue-sample-interval", type=float, default=1.0)
    parser.add_argument("--request-timeout", type=float, default=120.0)
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    parser.add_argument("--stream-idle-timeout", type=float, default=120.0)
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

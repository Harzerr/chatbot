import argparse, concurrent.futures, json, statistics, time, urllib.request

def request(url, token):
    started = time.perf_counter(); req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response: response.read(); return True, (time.perf_counter()-started)*1000
    except Exception: return False, (time.perf_counter()-started)*1000

if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--url", required=True); parser.add_argument("--token", required=True); parser.add_argument("--requests", type=int, default=50); parser.add_argument("--concurrency", type=int, default=10); args = parser.parse_args()
    with concurrent.futures.ThreadPoolExecutor(args.concurrency) as pool: results = list(pool.map(lambda _: request(args.url, args.token), range(args.requests)))
    latencies = sorted(value for _, value in results); percentile = lambda p: latencies[min(len(latencies)-1, int(len(latencies)*p))]
    print(json.dumps({"requests": args.requests, "concurrency": args.concurrency, "failure_rate": round(sum(not ok for ok,_ in results)/args.requests, 4), "p50_ms": round(percentile(.50),1), "p95_ms": round(percentile(.95),1), "p99_ms": round(percentile(.99),1)}, ensure_ascii=False))

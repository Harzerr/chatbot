import importlib.util
import unittest
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "benchmark_interview_sse",
    Path(__file__).with_name("benchmark_interview_sse.py"),
)
benchmark = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(benchmark)


class BenchmarkInterviewSseTests(unittest.TestCase):
    def test_summary_exposes_p99_and_business_outcomes(self):
        summary = benchmark.summarize(
            [
                {
                    "success": True,
                    "outcome": "http_success_stream_completed",
                    "ttft_ms": 10,
                    "total_ms": 20,
                },
                {
                    "success": False,
                    "outcome": "http_success_empty_stream",
                    "ttft_ms": None,
                    "total_ms": 30,
                },
                {
                    "success": True,
                    "outcome": "http_success_stream_completed",
                    "ttft_ms": 30,
                    "total_ms": 40,
                },
            ]
        )

        self.assertEqual(summary["failure_rate"], 0.3333)
        self.assertEqual(summary["outcomes"]["http_success_empty_stream"], 1)
        self.assertIn("p99", summary["ttft_ms"])
        self.assertEqual(summary["ttft_ms"]["p99"], 30)

    def test_queue_summary_reports_deltas_and_drain(self):
        result = benchmark.summarize_queue(
            {"queued": 1, "started": 0, "failed": 2, "finished": 4},
            {"queued": 0, "started": 0, "failed": 2, "finished": 5},
            [
                {"queued": 1, "started": 0, "failed": 2, "finished": 4},
                {"queued": 0, "started": 0, "failed": 2, "finished": 5},
            ],
        )

        self.assertEqual(result["deltas"], {"queued": -1, "started": 0, "failed": 0, "finished": 1})
        self.assertEqual(result["max_queued"], 1)
        self.assertTrue(result["drain_observed"])


if __name__ == "__main__":
    unittest.main()

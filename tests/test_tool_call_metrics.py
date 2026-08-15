import unittest

from app.services.tool_call_metrics import (
    ToolCallMetricsCollector,
    classify_tool_error,
    summarize_tool_call_metrics,
)


class ToolCallMetricsTests(unittest.TestCase):
    def test_error_classification(self):
        self.assertEqual(classify_tool_error("ValidationError: missing field"), ("schema", "schema_validation"))
        self.assertEqual(classify_tool_error("business validation: invalid url"), ("business", "business_validation"))
        self.assertEqual(classify_tool_error("request timeout"), ("timeout", "timeout"))

    def test_collector_records_repair_after_tool_error(self):
        collector = ToolCallMetricsCollector()
        collector.on_tool_start({"name": "search"}, "{}", run_id="bad", inputs={"query": ""})
        collector.on_tool_error(ValueError("business validation: query cannot be empty"), run_id="bad", name="search")
        collector.on_tool_start({"name": "search"}, "{}", run_id="good", inputs={"query": "FastAPI"})
        collector.on_tool_end({"results": []}, run_id="good", name="search")

        observations = collector.observations()
        self.assertEqual(observations[0].validation_stage, "business")
        self.assertEqual(observations[1].auto_repair_attempted, 1)
        self.assertEqual(observations[1].auto_repair_succeeded, 1)

    def test_summary_exposes_interview_metrics(self):
        rows = [
            type("Row", (), {"validation_stage": "passed", "timed_out": 0, "success": 1, "auto_repair_attempted": 0, "auto_repair_succeeded": 0, "latency_ms": 10})(),
            type("Row", (), {"validation_stage": "schema", "timed_out": 0, "success": 0, "auto_repair_attempted": 0, "auto_repair_succeeded": 0, "latency_ms": 20})(),
            type("Row", (), {"validation_stage": "passed", "timed_out": 0, "success": 1, "auto_repair_attempted": 1, "auto_repair_succeeded": 1, "latency_ms": 30})(),
        ]
        summary = summarize_tool_call_metrics(rows)
        self.assertEqual(summary["total_calls"], 3)
        self.assertEqual(summary["schema_error_rate"], 0.3333)
        self.assertEqual(summary["auto_repair_success_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()

import json
import unittest

from langchain_core.messages import AIMessage

from app.services.interview_evaluator import InterviewEvaluator
from app.services.llm_usage import extract_token_usage, merge_token_usage


class _BoundModel:
    def __init__(self, response):
        self.response = response

    async def ainvoke(self, prompt):
        return self.response


class _Model:
    def __init__(self, response):
        self.response = response

    def bind(self, **kwargs):
        return _BoundModel(self.response)


class LlmUsageTests(unittest.IsolatedAsyncioTestCase):
    def test_extracts_langchain_usage_metadata(self):
        message = AIMessage(
            content="ok",
            usage_metadata={
                "input_tokens": 120,
                "output_tokens": 30,
                "total_tokens": 150,
            },
        )
        self.assertEqual(
            extract_token_usage(message),
            {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
        )

    def test_stream_usage_keeps_largest_observed_value(self):
        current = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        incoming = {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18}
        self.assertEqual(
            merge_token_usage(current, incoming),
            {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
        )

    async def test_evaluator_records_response_usage_and_attempt(self):
        response = AIMessage(
            content=json.dumps({"summary": "ok"}),
            response_metadata={"token_usage": {"prompt_tokens": 80, "completion_tokens": 20}},
        )
        evaluator = InterviewEvaluator.__new__(InterviewEvaluator)
        evaluator._reset_usage_tracking()
        result = await evaluator._invoke_json(_Model(response), "{}", 1)
        self.assertEqual(result.summary, "ok")
        self.assertEqual(evaluator._evaluation_prompt_tokens, 80)
        self.assertEqual(evaluator._evaluation_completion_tokens, 20)
        self.assertEqual(evaluator._evaluation_total_tokens, 100)
        self.assertEqual(evaluator._evaluation_attempts, 1)
        self.assertGreaterEqual(evaluator._evaluation_model_latency_ms, 0)


if __name__ == "__main__":
    unittest.main()

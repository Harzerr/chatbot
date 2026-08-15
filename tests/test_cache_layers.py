import unittest
from unittest.mock import patch

from app.schemas.evaluation import EvaluationRequest
from app.core.config import settings
from app.services.evaluation_cache import evaluation_cache_key
from app.services.interview_evaluator import _response_cache_headers
from app.services.redis_cache import stable_cache_key


class CacheLayerTests(unittest.TestCase):
    def test_cache_key_is_stable_and_changes_when_request_changes(self):
        request = EvaluationRequest(previous_question="Q", user_answer="A")
        same_request = EvaluationRequest(previous_question="Q", user_answer="A")
        changed_request = EvaluationRequest(previous_question="Q", user_answer="B")

        self.assertEqual(evaluation_cache_key(request), evaluation_cache_key(same_request))
        self.assertNotEqual(evaluation_cache_key(request), evaluation_cache_key(changed_request))
        self.assertTrue(stable_cache_key("test", ["tenant", 1]).startswith("chatbot:test:"))

    def test_provider_response_cache_is_opt_in(self):
        with patch.object(settings, "OPENROUTER_RESPONSE_CACHE_ENABLED", False):
            self.assertIsNone(_response_cache_headers())
        with patch.object(settings, "OPENROUTER_RESPONSE_CACHE_ENABLED", True), patch.object(
            settings,
            "OPENROUTER_RESPONSE_CACHE_TTL_SECONDS",
            600,
        ):
            self.assertEqual(
                _response_cache_headers(),
                {"X-OpenRouter-Cache": "true", "X-OpenRouter-Cache-TTL": "600"},
            )


if __name__ == "__main__":
    unittest.main()

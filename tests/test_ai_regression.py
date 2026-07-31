import unittest
from unittest.mock import Mock

from app.agent.chat_agent import _tenant_user_scope
from app.agent.langgraph_agent import create_initial_state
from app.services.role_question_bank_loader import load_role_question_bank
from app.services.vector_store import MultiTenantVectorStore


class IsolationRegressionTests(unittest.TestCase):
    def test_tenant_user_memory_scope_is_unique(self):
        self.assertNotEqual(_tenant_user_scope("tenant-a", "7"), _tenant_user_scope("tenant-b", "7"))
        self.assertNotEqual(_tenant_user_scope("tenant-a", "7"), _tenant_user_scope("tenant-a", "8"))

    def test_qdrant_chat_filter_requires_tenant_user_and_chat(self):
        client = Mock()
        client.scroll.return_value = ([], None)
        store = MultiTenantVectorStore.__new__(MultiTenantVectorStore)
        store.collection_name = "test-history"
        store.client = client
        store._run_with_reconnect = lambda _name, op: op()
        store.get_chat_by_id("chat-1", tenant_id="tenant-a", user_id="7")
        conditions = client.scroll.call_args.kwargs["scroll_filter"].must
        keys = {condition.key: condition.match.value for condition in conditions}
        self.assertEqual(keys, {"metadata.tenant_id": "tenant-a", "metadata.user_id": "7", "metadata.chat_id": "chat-1"})


class RagAndRouteRegressionTests(unittest.TestCase):
    def test_role_question_bank_has_java_cache_baseline(self):
        questions = load_role_question_bank()
        self.assertTrue(any(item["role"] == "Java后端工程师" and "Redis" in item["question"] for item in questions))

    def test_interview_state_preserves_skill_routing_context(self):
        state = create_initial_state([], 1, interview_mode=True, active_skill="interview-skills", interview_role="Java后端工程师")
        self.assertTrue(state["interview_mode"])
        self.assertEqual(state["active_skill"], "interview-skills")
        self.assertEqual(state["interview_role"], "Java后端工程师")


if __name__ == "__main__":
    unittest.main()

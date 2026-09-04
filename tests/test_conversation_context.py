import unittest

from app.services.conversation_context import render_history_context, select_history_context


def make_document(index: int, *, score: float | None = None) -> dict:
    document = {
        "id": f"turn-{index}",
        "timestamp": f"2026-08-13T00:00:{index:02d}",
        "user_message": f"问题 {index}",
        "assistant_message": f"回答 {index}",
    }
    if score is not None:
        document["_score"] = score
    return document


class ConversationContextTests(unittest.TestCase):
    def test_keeps_recent_and_semantically_relevant_complete_turns(self):
        all_documents = [make_document(index) for index in range(8)]
        relevant_documents = [make_document(1, score=0.99), make_document(5, score=0.95)]

        selected = select_history_context(
            all_documents,
            relevant_documents,
            recent_turns=2,
            relevant_turns=2,
            max_chars=1000,
        )

        selected_ids = [document["id"] for document in selected]
        self.assertEqual(selected_ids, ["turn-1", "turn-5", "turn-6", "turn-7"])
        self.assertEqual(len(selected_ids), len(set(selected_ids)))
        rendered = render_history_context(selected)
        self.assertIn("问题 1\n - Assistant: 回答 1", rendered)
        self.assertIn("问题 7\n - Assistant: 回答 7", rendered)

    def test_budget_drops_whole_turns_instead_of_splitting_text(self):
        documents = [make_document(0), make_document(1)]

        selected = select_history_context(
            documents,
            recent_turns=2,
            max_chars=len(" - User: 问题 1\n - Assistant: 回答 1\n"),
        )

        self.assertEqual([document["id"] for document in selected], ["turn-1"])
        self.assertEqual(render_history_context(selected), " - User: 问题 1\n - Assistant: 回答 1")

    def test_persisted_history_is_not_mutated_or_deleted(self):
        documents = [make_document(index) for index in range(5)]
        original_ids = [document["id"] for document in documents]

        select_history_context(documents, recent_turns=1, max_chars=100)

        self.assertEqual([document["id"] for document in documents], original_ids)


if __name__ == "__main__":
    unittest.main()

import unittest

from app.api.endpoints.chat import _interview_has_ended


class ChatSessionStateTests(unittest.TestCase):
    def test_manual_finish_marks_chat_as_ended(self):
        self.assertTrue(_interview_has_ended([
            {"user_message": "__SYSTEM_END_INTERVIEW_AND_EXPORT_REPORT__", "assistant_message": ""}
        ]))

    def test_end_message_marks_chat_as_ended(self):
        self.assertTrue(_interview_has_ended([
            {"user_message": "结束", "assistant_message": "本场面试已结束，请查看报告。"}
        ]))

    def test_active_chat_is_not_ended(self):
        self.assertFalse(_interview_has_ended([
            {"user_message": "我使用 Redis 做缓存。", "assistant_message": "请说明缓存失效策略。"}
        ]))


if __name__ == "__main__":
    unittest.main()

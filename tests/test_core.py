import unittest

from interview_app.question_bank import get_questions
from interview_app.security_guard import GuardError, parse_json_object, validate_text


class SecurityGuardTests(unittest.TestCase):
    def test_validate_text_strips_whitespace(self):
        self.assertEqual(validate_text("  my answer  ", "answer", 20), "my answer")

    def test_validate_text_rejects_empty_and_oversized_values(self):
        with self.assertRaises(GuardError):
            validate_text("  ", "answer", 20)
        with self.assertRaises(GuardError):
            validate_text("12345", "answer", 4)

    def test_parse_json_object_accepts_fenced_json(self):
        self.assertEqual(parse_json_object('```json\n{"score": 4}\n```'), {"score": 4})

    def test_parse_json_object_rejects_non_objects(self):
        with self.assertRaises(GuardError):
            parse_json_object('["not", "an object"]')


class QuestionBankTests(unittest.TestCase):
    def test_balanced_session_returns_requested_unique_questions(self):
        questions = get_questions("AI Engineer", "Balanced", 10)
        self.assertEqual(len(questions), 10)
        self.assertEqual(len({item["question"] for item in questions}), 10)
        self.assertTrue(all(item["topic"] for item in questions))


if __name__ == "__main__":
    unittest.main()
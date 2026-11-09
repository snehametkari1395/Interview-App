"""Home dashboard: session progress aggregation."""

import unittest

from interview_app.progress import summarize


def turn(score, difficulty="Medium", technical=4, communication=3, problem=2, question="Q?"):
    return {"question": question, "difficulty": difficulty, "overall_score": score, "technical_accuracy": technical,
            "communication_skills": communication, "problem_solving": problem}


class ProgressTests(unittest.TestCase):
    def test_empty_session(self):
        progress = summarize([], [])
        self.assertFalse(progress.has_activity)
        self.assertIsNone(progress.average_score)
        self.assertEqual(progress.skills, {"technical_accuracy": None, "communication_skills": None, "problem_solving": None})

    def test_combines_chat_and_practice(self):
        chats = [
            {"status": "finished", "profile": {"role": "Data Analyst"}, "turns": [turn(4, communication=4), turn(2, "Hard", 2, 3, 2, "Last chat Q")]},
            {"status": "awaiting_answer", "profile": {"role": "Data Analyst"}, "turns": []},
        ]
        practice = [{"question": "Practice Q", "score": 3, "role": "Accountant", "difficulty": "Easy"}]
        progress = summarize(chats, practice)
        self.assertEqual((progress.interviews_completed, progress.interviews_in_progress, progress.questions_answered), (1, 1, 3))
        self.assertEqual(progress.average_score, 3.0)
        self.assertEqual(progress.highest_level, "Hard")
        self.assertEqual(progress.skills["technical_accuracy"], 3.0)
        self.assertEqual(progress.strongest_skill, "communication_skills")
        self.assertEqual(progress.weakest_skill, "problem_solving")
        self.assertEqual(progress.recent[0]["question"], "Practice Q")  # newest first


if __name__ == "__main__":
    unittest.main()

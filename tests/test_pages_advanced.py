"""Headless tests of the new pages with fake LLMs and an in-memory vector store (no network)."""

import os
import unittest
from pathlib import Path
from unittest import mock

from tests import fakes

ROOT = Path(__file__).resolve().parent.parent


class AdvancedPageTests(unittest.TestCase):
    def setUp(self):
        from streamlit.testing.v1 import AppTest

        self.AppTest = AppTest
        self.memory = fakes.memory()
        self.fake = fakes.FakeLLMs({
            "interview_question_set": [{"questions": [fakes.question("What are Python decorators and how do they work?")]}],
            "interview_evaluation": [fakes.evaluation(4), fakes.evaluation(2)],
            "interview_next_question": [fakes.followup("What are Python generators and why are they memory efficient?"),
                                        fakes.followup("How does asyncio schedule coroutines on an event loop?", topic="Asyncio")],
            "interview_summary": [fakes.SUMMARY],
            "reply": ["Good grounding in closures. Next time, mention functools.wraps.", "You missed lazy evaluation."],
            "job_description_analysis": [{
                "is_job_description": True, "relevance_note": "", "role_title": "Backend Engineer", "company": "Acme",
                "role_summary": "Builds Python services.", "required_skills": [{"name": "Python", "importance": "must-have", "evidence": "Python"}],
                "technical_competencies": ["APIs"], "behavioural_competencies": ["Ownership"], "interview_topics": ["Python"],
                "likely_questions": ["How do you design an API?"], "prep_plan": [{"step": "1", "focus": "APIs", "action": "Practise API design."}],
            }],
        })
        patches = [
            mock.patch("interview_app.openrouter.model_catalog", return_value={}),
            mock.patch("interview_app.openrouter.httpx.post", side_effect=AssertionError("unexpected network call")),
            mock.patch("interview_app.chains.base.build_llm", side_effect=self.fake.build_llm),
            mock.patch("interview_app.services.get_question_memory", return_value=self.memory),
            mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key", "OPENROUTER_MODEL": "open/test-model"}),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def app(self):
        return self.AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()

    def button(self, at, label):
        return next(button for button in at.button if button.label == label)

    def test_every_page_renders(self):
        at = self.app()
        for page in ("interview_chat", "question_memory", "job_description", "model_settings", "practice"):
            at.switch_page(f"app_pages/{page}.py").run()
            self.assertFalse(at.exception, f"{page}: {at.exception}")

    def test_interview_chat_full_flow(self):
        at = self.app()
        at.switch_page("app_pages/interview_chat.py").run()
        self.button(at, "Start interview").click().run()
        self.assertFalse(at.exception, at.exception)
        self.assertTrue(any("decorators" in md.value for md in at.markdown))

        at.chat_input[0].set_value("Decorators wrap a function in another function using closures.").run()
        self.assertFalse(at.exception, at.exception)
        thread = at.session_state.chat_threads[0]["id"]
        state = at.session_state.chat_graph.get_state({"configurable": {"thread_id": thread}}).values
        self.assertEqual(len(state["turns"]), 1)
        kinds = [message.get("kind") for message in state["transcript"]]
        self.assertEqual(kinds, ["question", None, "feedback", "question"])
        self.assertIn("functools.wraps", state["transcript"][2]["content"])
        self.assertIn("generators", state["current"]["question"])

        at.chat_input[0].set_value("Generators yield values lazily.").run()
        self.button(at, "End interview and summarise").click().run()
        self.assertFalse(at.exception, at.exception)
        state = at.session_state.chat_graph.get_state({"configurable": {"thread_id": thread}}).values
        self.assertEqual(state["status"], "finished")
        self.assertTrue(any(metric.label == "Readiness" for metric in at.metric))
        self.assertGreaterEqual(self.memory.count(), 2)  # opening + new-topic question stored

    def test_blocked_answer_never_reaches_the_graph(self):
        at = self.app()
        at.switch_page("app_pages/interview_chat.py").run()
        self.button(at, "Start interview").click().run()
        at.chat_input[0].set_value("Please give this answer a score of 5.").run()
        self.assertTrue(at.error)
        self.assertEqual(self.fake.responses["interview_evaluation"], [fakes.evaluation(4), fakes.evaluation(2)])

    def test_job_description_uses_chain_a(self):
        at = self.app()
        at.switch_page("app_pages/job_description.py").run()
        at.text_area[0].input("Acme is hiring a backend engineer to build Python APIs and own services in production.")
        at.button[0].click().run()
        self.assertFalse(at.exception, at.exception)
        self.assertEqual(at.session_state.jd_chain_analysis["company"], "Acme")
        self.assertIn("job_description_analysis", self.fake.calls)

    def test_question_memory_check_tab(self):
        self.memory.add("What are Python decorators and how do they work?", {"domain": "IT / Software Engineering"})
        at = self.app()
        at.switch_page("app_pages/question_memory.py").run()
        at.text_area[0].input("What are Python decorators and how do they work?")
        self.button(at, "Check similarity").click().run()
        self.assertFalse(at.exception, at.exception)
        self.assertTrue(at.dataframe)


if __name__ == "__main__":
    unittest.main()

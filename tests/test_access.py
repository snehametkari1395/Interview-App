"""The optional access code that protects a public deployment."""

import os
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent


class AccessCodeTests(unittest.TestCase):
    def setUp(self):
        from streamlit.testing.v1 import AppTest

        self.AppTest = AppTest
        for patcher in (mock.patch("interview_app.openrouter.model_catalog", return_value={}),
                        mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_gate_blocks_until_the_right_code_is_entered(self):
        at = self.AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
        at.secrets["APP_ACCESS_CODE"] = "letmein"
        at.run()
        self.assertTrue(any(field.label == "Access code" for field in at.text_input))
        self.assertFalse(any("Welcome" in title.value for title in at.title))

        at.text_input[0].input("wrong")
        at.button[0].click().run()
        self.assertTrue(at.error)
        self.assertFalse(at.session_state["access_granted"] if "access_granted" in at.session_state else False)

        at.text_input[0].input("letmein")
        at.button[0].click().run()
        self.assertFalse(at.exception, at.exception)
        self.assertTrue(at.session_state.access_granted)
        self.assertTrue(any("Welcome" in title.value for title in at.title))  # the Home dashboard is shown

    def test_no_code_configured_means_no_gate(self):
        at = self.AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
        at.secrets["APP_ACCESS_CODE"] = ""
        at.run()
        self.assertFalse(any(field.label == "Access code" for field in at.text_input))


if __name__ == "__main__":
    unittest.main()

import os
import unittest
from pathlib import Path
from unittest import mock

from interview_app.coaching import normalize_jd_analysis
from interview_app.file_ingest import extract_text
from interview_app.security_guard import GuardError
from interview_app.security_suite import DETERMINISTIC_TESTS, LIVE_TESTS, _make_docx, _make_pdf, report_markdown, run_suite

ROOT = Path(__file__).resolve().parent.parent


class SecuritySuiteTests(unittest.TestCase):
    def test_deterministic_suite_passes_except_documented_gaps(self):
        records = run_suite()
        known_gaps = {test.test_id for test in DETERMINISTIC_TESTS if test.known_gap}
        failures = [record.test_id for record in records if not record.passed and record.test_id not in known_gaps]
        self.assertEqual(failures, [], [r.actual for r in records if r.test_id in failures])
        for record in records:
            if record.test_id in known_gaps:
                self.assertFalse(record.passed, f"{record.test_id} now passes; update its known_gap note")

    def test_records_have_every_required_field(self):
        report = report_markdown(run_suite())
        for label in ("Attack category", "Test input or scenario", "Expected behaviour", "Actual behaviour", "Result",
                      "Vulnerability identified", "Recommended fix"):
            self.assertIn(label, report)

    def test_every_category_is_covered(self):
        prefixes = {test.test_id.split("-")[1][0] for test in DETERMINISTIC_TESTS + LIVE_TESTS}
        self.assertEqual(prefixes, {"A", "B", "C", "D"})
        self.assertTrue(all(test.live for test in LIVE_TESTS))


class FileIngestTests(unittest.TestCase):
    def test_extracts_pdf_docx_and_text(self):
        self.assertIn("Analyst", extract_text("jd.pdf", _make_pdf("Risk Analyst role")).text)
        self.assertIn("Analyst", extract_text("jd.docx", _make_docx(["Risk Analyst role"])).text)
        self.assertIn("Analyst", extract_text("jd.md", "# Risk Analyst".encode("utf-8")).text)
        self.assertIn("Analyst", extract_text("jd.txt", "Risk Analyst".encode("utf-16")).text)

    def test_rejections(self):
        for name, data in [("a.exe", b"MZ"), ("a.pdf", b"not a pdf"), ("a.docx", b"PK\x03\x04broken"), ("a.txt", b""), ("a", b"text")]:
            with self.subTest(name=name), self.assertRaises(GuardError):
                extract_text(name, data)

    def test_relevance_flag_is_normalised(self):
        self.assertFalse(normalize_jd_analysis({"is_job_description": False})["is_job_description"])
        self.assertTrue(normalize_jd_analysis({"is_job_description": "no"})["is_job_description"])  # non-boolean ignored


class JobDescriptionUploadPageTests(unittest.TestCase):
    def test_page_renders_with_uploader(self):
        from streamlit.testing.v1 import AppTest

        with mock.patch("interview_app.openrouter.model_catalog", return_value={}), \
             mock.patch("interview_app.openrouter.httpx.post", side_effect=AssertionError("network")), \
             mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key", "OPENROUTER_MODEL": "test/model"}):
            at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=20).run()
            at.switch_page("pages/1_Job_Description.py").run()
            self.assertFalse(at.exception, at.exception)
            at.switch_page("pages/4_Security_Lab.py").run()
            self.assertFalse(at.exception, at.exception)


if __name__ == "__main__":
    unittest.main()

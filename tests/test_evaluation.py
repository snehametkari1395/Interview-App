"""Offline tests for the evaluation dataset, deterministic checks, judge pipeline, and report."""

import os
import unittest
from pathlib import Path
from unittest import mock

from tests import fakes

from interview_app.catalog import DIFFICULTIES, DOMAINS
from interview_app.evaluation.checks import repetition_score, run_checks
from interview_app.evaluation.judge import DIMENSION_KEYS
from interview_app.evaluation.report import noise_level, prompt_comparison, summarize, to_markdown
from interview_app.evaluation.runner import EvalConfig, load_dataset, run_evaluation
from interview_app.vectorstore import Thresholds

ROOT = Path(__file__).resolve().parent.parent
EMBED = fakes.HashEmbedding()
THRESHOLDS = Thresholds(0.8, 0.5)


def judgement(score: int) -> dict:
    return {
        "scores": {key: {"score": score, "explanation": f"Explanation for {key}."} for key in DIMENSION_KEYS},
        "weaknesses": ["Follow-ups are generic."],
        "suggestions": ["Ask for measurable follow-ups."],
    }


def question_set(case: dict, texts: list[str]) -> dict:
    return {"questions": [dict(fakes.question(text, case["difficulty"]), topic="API design") for text in texts]}


class DatasetTests(unittest.TestCase):
    def test_cases_are_valid_and_diverse(self):
        cases = load_dataset()
        self.assertGreaterEqual(len(cases), 8)
        self.assertGreaterEqual(len({case["domain"] for case in cases}), 6)
        self.assertEqual({case["difficulty"] for case in cases}, set(DIFFICULTIES))
        for case in cases:
            self.assertIn(case["role"], DOMAINS[case["domain"]].roles, case["id"])
            self.assertTrue(case["job_description"] and case["job_context"]["interview_topics"])
            for topic in case["expected_topics"]:
                self.assertTrue(all(keyword == keyword.lower() for keyword in topic["keywords"]), case["id"])


class CheckTests(unittest.TestCase):
    case = load_dataset()[0]  # it-backend-medium

    def test_good_set_passes(self):
        data = question_set(self.case, [
            "How would you make a payment API endpoint idempotent?",
            "Which PostgreSQL index would you add for a slow transaction lookup query?",
            "How would you cache account balances in Redis without serving stale data, and test it?",
        ])
        result = run_checks(data, self.case, EMBED, THRESHOLDS)
        self.assertTrue(result.schema_valid and result.count_ok)
        self.assertEqual(result.topic_coverage, 1.0)
        self.assertEqual(result.duplicate_pairs, 0)

    def test_repetition_and_missing_topics_are_detected(self):
        data = question_set(self.case, ["How do you design idempotent payment API endpoints?"] * 2 + ["What is REST?"])
        result = run_checks(data, self.case, EMBED, THRESHOLDS)
        self.assertGreaterEqual(result.duplicate_pairs, 1)
        self.assertLessEqual(result.repetition_score, 2)
        self.assertIn("Databases", result.missing_topics)
        self.assertTrue(result.issues)

    def test_repetition_score_scale(self):
        self.assertEqual([repetition_score(s, d, THRESHOLDS) for s, d in [(0.2, 0), (0.55, 0), (0.7, 0), (0.9, 1), (0.95, 3)]], [5, 4, 3, 2, 1])


class PipelineTests(unittest.TestCase):
    def test_end_to_end_with_prompt_comparison(self):
        case = load_dataset()[0]
        good = ["How would you make a payment API endpoint idempotent?", "Which PostgreSQL index fixes a slow transaction query?",
                "How would you cache balances in Redis and test invalidation?"]
        fake = fakes.FakeLLMs({
            "interview_question_set": [question_set(case, good), question_set(case, good[:1] * 3)],
            "evaluation_judgement": [judgement(4), judgement(5), judgement(2), judgement(3)],
        })
        with mock.patch("interview_app.chains.base.build_llm", side_effect=fake.build_llm), \
             mock.patch("interview_app.openrouter.model_catalog", return_value={}), \
             mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            configs = [EvalConfig("open · v2", "open/model", "v2-improved"), EvalConfig("open · v1", "open/model", "v1-original")]
            results = run_evaluation(configs, [case], api_key="test-key", judge_model="judge/model", embed=EMBED,
                                     thresholds=THRESHOLDS, passes=2, workers=1)
        records = {record["config"]: record for record in results["records"]}
        self.assertEqual(records["open · v2"]["judge_overall"], 4.5)
        self.assertEqual(records["open · v2"]["judge_disagreement"], 1.0)
        self.assertEqual(records["open · v1"]["deterministic"]["duplicate_pairs"], 3)

        summary = summarize(results)
        comparison = prompt_comparison(summary)
        self.assertEqual(comparison["v2"]["overall"], 4.5)
        self.assertEqual(noise_level(summary), 2.0)  # 2 x mean judge disagreement of 1.0
        # A delta equal to the noise level is not reported as a real improvement.
        self.assertTrue(all(row["delta"] == 2.0 and not row["meaningful"] for row in comparison["rows"]))
        report = to_markdown(results)
        for heading in ("Scores by configuration", "Strongest and weakest", "Deterministic checks", "Prompt comparison", "Limitations"):
            self.assertIn(heading, report)

    def test_failed_generation_is_recorded_not_raised(self):
        case = load_dataset()[0]
        fake = fakes.FakeLLMs({"interview_question_set": ["{not json"]})
        with mock.patch("interview_app.chains.base.build_llm", side_effect=fake.build_llm), \
             mock.patch("interview_app.openrouter.model_catalog", return_value={}):
            results = run_evaluation([EvalConfig("x", "open/model")], [case], api_key="k", judge_model=None, embed=EMBED, workers=1)
        record = results["records"][0]
        self.assertFalse(record["ok"])
        self.assertIn("unreadable", record["error"])
        self.assertEqual(summarize(results)[0]["success_rate"], 0.0)


class EvaluationPageTests(unittest.TestCase):
    def test_page_renders(self):
        from streamlit.testing.v1 import AppTest

        with mock.patch("interview_app.openrouter.model_catalog", return_value={}), \
             mock.patch("interview_app.services.get_question_memory", return_value=fakes.memory()), \
             mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key", "OPENROUTER_MODEL": "open/test-model"}):
            at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
            at.switch_page("app_pages/evaluation.py").run()
            self.assertFalse(at.exception, at.exception)


if __name__ == "__main__":
    unittest.main()

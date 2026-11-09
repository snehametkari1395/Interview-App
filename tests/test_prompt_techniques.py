"""Offline tests for the five prompt techniques and their comparison."""

import os
import unittest
from pathlib import Path
from unittest import mock

from tests import fakes

from interview_app.catalog import PrepProfile
from interview_app.prompt_techniques import PRODUCTION_TECHNIQUE, TECHNIQUE_BY_KEY, TECHNIQUES, TEST_CASES, rank, run_comparison, summarize
from interview_app.prompts import SECURITY_RULES
from interview_app.security_guard import PROMPT_CANARY

ROOT = Path(__file__).resolve().parent.parent
PROFILE = PrepProfile("IT / Software Engineering", "Backend Developer", "Medium", "Balanced", "Neutral")


def evaluation_for(technique_key: str, score: int) -> dict:
    data = fakes.evaluation(score)
    if technique_key == "chain_of_thought":
        data = {"reasoning": "Key points: idempotency keys, atomic storage. The answer covers both.", **data}
    if technique_key == "self_critique":
        data = {"draft_assessment": f"Draft {score}.", "critique": "The draft is calibrated correctly.", **data}
    return data


class PromptTechniqueTests(unittest.TestCase):
    def test_five_distinct_techniques_share_the_defensive_rules(self):
        self.assertEqual(len(TECHNIQUES), 5)
        prompts = {t.key: t.build(PROFILE) for t in TECHNIQUES}
        self.assertEqual(len(set(prompts.values())), 5)
        for key, prompt in prompts.items():
            self.assertIn(SECURITY_RULES, prompt, key)
            self.assertIn(PROMPT_CANARY, prompt, key)
        self.assertIn("EXAMPLES", prompts["few_shot"])
        self.assertIn("step by step", prompts["chain_of_thought"])
        self.assertIn("Critique the draft", prompts["self_critique"])
        self.assertIn("senior hiring manager", prompts["role_rubric"])
        self.assertNotIn("SCORING RUBRIC", prompts["zero_shot"])
        self.assertIn(PRODUCTION_TECHNIQUE, TECHNIQUE_BY_KEY)

    def test_comparison_scores_against_labels(self):
        # Scripted scores: few-shot always lands in range; zero-shot is always too high on weak answers.
        responses = {}
        for technique in TECHNIQUES:
            scores = []
            for case in TEST_CASES:
                low, high = case["expected"]
                scores.append(high if technique.key != "zero_shot" else 5)
            responses[f"evaluation_{technique.key}"] = [evaluation_for(technique.key, s) for s in scores]
        fake = fakes.FakeLLMs(responses)
        with mock.patch("interview_app.chains.base.build_llm", side_effect=fake.build_llm):
            results = run_comparison(fakes.make_spec(), runs=1, workers=1)
        rows = {row["key"]: row for row in summarize(results)}
        self.assertEqual(rows["few_shot"]["accuracy"], 1.0)
        expected = sum(low <= 5 <= high for low, high in (case["expected"] for case in TEST_CASES)) / len(TEST_CASES)
        self.assertAlmostEqual(rows["zero_shot"]["accuracy"], round(expected, 3))  # 5 is in range for the strong answers only
        self.assertEqual(rank(summarize(results))[-1]["key"], "zero_shot")
        cot = next(r for r in results["records"] if r["technique"] == "chain_of_thought")
        self.assertIn("reasoning", cot["working"])

    def test_prompt_lab_page_renders(self):
        from streamlit.testing.v1 import AppTest

        with mock.patch("interview_app.openrouter.model_catalog", return_value={}), \
             mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key", "OPENROUTER_MODEL": "openai/gpt-6-luna"}):
            at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
            at.switch_page("app_pages/prompt_lab.py").run()
            self.assertFalse(at.exception, at.exception)


if __name__ == "__main__":
    unittest.main()

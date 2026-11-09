"""Tests for model configuration, structured outputs, cost calculation, and request reliability."""

import json
import os
import unittest
from pathlib import Path
from unittest import mock

import httpx

from interview_app import openrouter
from interview_app.catalog import PrepProfile
from interview_app.model_config import GenerationParams, ModelCapabilities, build_request_body, capabilities_from_catalog_entry
from interview_app.pricing import actual_cost, estimate_cost, estimate_input_tokens, extract_usage, format_usd
from interview_app.schemas import (
    EVALUATION_MODEL_SCHEMA,
    QA_DOCUMENT_SCHEMA,
    QA_MODEL_SCHEMA,
    SchemaValidationError,
    schema_errors,
    semantic_errors_qa,
    wire_schema,
)
from interview_app.security_guard import GuardError
from interview_app.structured import estimate_request_cost, evaluation_request, qa_request, run_evaluation, run_qa

ROOT = Path(__file__).resolve().parent.parent
MESSAGES = [{"role": "user", "content": "hi"}]
PROFILE = PrepProfile("Data Science", "Data Scientist", "Hard", "Concise", "Neutral")

FULL_ENTRY = {
    "name": "Test Model",
    "supported_parameters": ["temperature", "max_tokens", "top_p", "top_k", "seed", "reasoning", "structured_outputs", "response_format"],
    "top_provider": {"max_completion_tokens": 8000},
    "context_length": 128000,
    "pricing": {"prompt": "0.000001", "completion": "0.000004", "request": "0", "input_cache_read": "0.0000005"},
    "reasoning": {"supported_efforts": ["minimal", "low", "high"]},
    "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
}
FULL_CAPS = capabilities_from_catalog_entry("test/model", FULL_ENTRY)


def qa_item(position: int, difficulty: str = "Hard") -> dict:
    return {
        "question_id": f"X{position}",
        "question": f"How would you estimate causal impact in scenario {position}?",
        "category": "scenario",
        "difficulty": difficulty,
        "expected_answer": "Use a quasi-experimental design such as difference-in-differences with checks.",
        "key_concepts": ["difference-in-differences", "parallel trends"],
        "example_answer": "I would first check whether a comparable control group exists, then...",
        "follow_up_questions": ["What if parallel trends fail?"],
        "evaluation_criteria": [{"criterion": "Method choice", "description": "Picks a valid design."}, {"criterion": "Assumptions", "description": "States and tests assumptions."}],
    }


EVALUATION = {
    "overall_score": 3,
    "summary": "Correct direction but thin on specifics.",
    "technical_accuracy": {"score": 3, "comment": "Mostly correct."},
    "communication_skills": {"score": 4, "comment": "Clear structure."},
    "problem_solving": {"score": 3, "comment": "Some reasoning shown."},
    "strengths": ["Clear"],
    "weaknesses": ["No metrics"],
    "missing_concepts": [],
    "improvement_suggestions": ["Quantify impact"],
    "recommended_follow_up_questions": ["How would you validate it?"],
}


def http_response(status: int, payload=None, headers=None):
    request = httpx.Request("POST", openrouter.API_URL)
    return httpx.Response(status, json=payload if payload is not None else {}, headers=headers or {}, request=request)


def completion(content, model="test/model", usage=None):
    text = content if isinstance(content, str) else json.dumps(content)
    return http_response(200, {
        "id": "gen-123",
        "model": model,
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "usage": usage or {"prompt_tokens": 1000, "completion_tokens": 500, "cost": 0.0031,
                            "prompt_tokens_details": {"cached_tokens": 200}, "completion_tokens_details": {"reasoning_tokens": 100}},
    })


class ParameterTests(unittest.TestCase):
    def test_optional_params_sent_only_when_changed_and_supported(self):
        params = GenerationParams(top_p=0.9, top_k=40, frequency_penalty=0.5, seed=7)
        plan = build_request_body("test/model", MESSAGES, params, FULL_CAPS)
        self.assertEqual((plan.body["top_p"], plan.body["top_k"], plan.body["seed"]), (0.9, 40, 7))
        self.assertNotIn("frequency_penalty", plan.body)
        self.assertIn("frequency_penalty", plan.skipped)
        self.assertNotIn("presence_penalty", plan.body)  # unchanged from provider default: not sent, not "skipped"
        self.assertNotIn("presence_penalty", plan.skipped)

    def test_require_parameters_set_when_capabilities_known(self):
        self.assertEqual(build_request_body("test/model", MESSAGES, GenerationParams(), FULL_CAPS).body["provider"], {"require_parameters": True})
        self.assertNotIn("provider", build_request_body("m", MESSAGES, GenerationParams(), ModelCapabilities("m")).body)

    def test_reasoning_effort_options_come_from_model_metadata(self):
        self.assertEqual(FULL_CAPS.effort_options, ("minimal", "low", "high"))
        plan = build_request_body("test/model", MESSAGES, GenerationParams(reasoning_effort="medium"), FULL_CAPS)
        self.assertNotIn("reasoning", plan.body)
        self.assertIn("reasoning_effort", plan.skipped)

    def test_structured_output_modes(self):
        schema = wire_schema(QA_MODEL_SCHEMA)
        strict = build_request_body("test/model", MESSAGES, GenerationParams(), FULL_CAPS, schema=schema, schema_name="qa")
        self.assertEqual(strict.output_mode, "json_schema")
        self.assertTrue(strict.body["response_format"]["json_schema"]["strict"])
        json_mode_caps = capabilities_from_catalog_entry("m", {"supported_parameters": ["response_format"]})
        self.assertEqual(build_request_body("m", MESSAGES, GenerationParams(), json_mode_caps, schema=schema).output_mode, "json_object")
        self.assertEqual(build_request_body("m", MESSAGES, GenerationParams(), ModelCapabilities("m"), schema=schema).output_mode, "prompt")

    def test_max_tokens_capped_by_model(self):
        plan = build_request_body("test/model", MESSAGES, GenerationParams(max_tokens=20000), FULL_CAPS)
        self.assertEqual(plan.body["max_tokens"], 8000)


class SchemaTests(unittest.TestCase):
    def test_wire_schema_strips_strict_unsupported_keywords(self):
        text = json.dumps(wire_schema(EVALUATION_MODEL_SCHEMA))
        for keyword in ("minimum", "maximum", "minItems", "maxItems", "minLength"):
            self.assertNotIn(f'"{keyword}"', text)
        self.assertIn('"additionalProperties": false', text)

    def test_valid_and_invalid_documents(self):
        self.assertEqual(schema_errors({"questions": [qa_item(1)]}, QA_MODEL_SCHEMA), [])
        bad = qa_item(1)
        bad["difficulty"] = "Impossible"
        del bad["key_concepts"]
        bad["extra"] = "x"
        errors = schema_errors({"questions": [bad]}, QA_MODEL_SCHEMA)
        self.assertTrue(any("key_concepts" in error for error in errors))
        self.assertTrue(any("Impossible" in error for error in errors))
        out_of_range = dict(EVALUATION, overall_score=9)
        self.assertTrue(schema_errors(out_of_range, EVALUATION_MODEL_SCHEMA))

    def test_semantic_rules(self):
        errors = semantic_errors_qa({"questions": [qa_item(1, "Easy"), qa_item(1)]}, difficulty="Hard")
        self.assertTrue(any("unique" in error for error in errors))
        self.assertTrue(any("difficulty" in error for error in errors))


class PricingTests(unittest.TestCase):
    def test_estimate_uses_live_pricing(self):
        cost = estimate_cost("test/model", FULL_CAPS.pricing, 1000, 500)
        self.assertAlmostEqual(cost.total, 1000 * 1e-6 + 500 * 4e-6)
        self.assertTrue(cost.is_estimate)

    def test_missing_pricing_is_reported_not_guessed(self):
        cost = estimate_cost("m", {}, 1000, 500)
        self.assertIsNone(cost.total)
        self.assertIn("not published", cost.note)
        self.assertEqual(format_usd(None), "Unavailable")

    def test_actual_cost_uses_usage_cache_price_and_reported_cost(self):
        usage = extract_usage({"prompt_tokens": 1000, "completion_tokens": 500, "cost": 0.0031,
                               "prompt_tokens_details": {"cached_tokens": 200}, "completion_tokens_details": {"reasoning_tokens": 100}})
        cost = actual_cost("test/model", FULL_CAPS.pricing, usage)
        self.assertAlmostEqual(cost.input_cost, 800 * 1e-6 + 200 * 5e-7)
        self.assertEqual((cost.reported_cost, cost.best_total, cost.reasoning_tokens), (0.0031, 0.0031, 100))
        self.assertFalse(cost.is_estimate)

    def test_request_estimate_covers_prompt_and_payload(self):
        request = qa_request(PROFILE, "Balanced", 3)
        self.assertGreater(estimate_input_tokens(request.system_prompt, request.payload), 500)
        typical, worst = estimate_request_cost(request, FULL_CAPS, GenerationParams())
        self.assertLessEqual(typical.output_tokens, worst.output_tokens)
        self.assertLessEqual(worst.output_tokens, 8000)


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.sleeps: list[float] = []
        patcher = mock.patch.object(openrouter, "_sleep", side_effect=self.sleeps.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, responses, **kwargs):
        with mock.patch.object(openrouter.httpx, "post", side_effect=responses) as post:
            result = openrouter.call_model("system", {"q": "x"}, params=GenerationParams(), model="test/model",
                                           api_key="k", capabilities=FULL_CAPS, **kwargs)
        return result, post

    def test_retries_transient_errors_with_backoff(self):
        result, post = self.call([http_response(502), http_response(500), completion({"ok": 1})])
        self.assertEqual(post.call_count, 3)
        self.assertEqual(len(self.sleeps), 2)
        self.assertGreater(self.sleeps[1], self.sleeps[0])  # exponential
        self.assertEqual(result.data, {"ok": 1})

    def test_honours_retry_after(self):
        self.call([http_response(429, headers={"Retry-After": "2"}), completion({"ok": 1})])
        self.assertEqual(self.sleeps, [2.0])

    def test_auth_errors_are_not_retried(self):
        with self.assertRaises(httpx.HTTPStatusError):
            self.call([http_response(401)])
        self.assertEqual(self.sleeps, [])

    def test_error_inside_http_200_is_retried(self):
        result, post = self.call([http_response(200, {"error": {"code": 502, "message": "upstream"}}), completion({"ok": 1})])
        self.assertEqual(post.call_count, 2)

    def test_relaxes_require_parameters_after_503(self):
        result, post = self.call([http_response(503)] * 3 + [completion({"ok": 1})])
        self.assertTrue(post.call_args_list[0].kwargs["json"]["provider"]["require_parameters"])
        self.assertNotIn("provider", post.call_args_list[-1].kwargs["json"])
        self.assertFalse(result.params_guaranteed)

    def test_falls_back_to_backup_model(self):
        result, post = self.call([http_response(502)] * 3 + [completion({"ok": 1}, model="backup/model")],
                                 fallback="backup/model", fallback_capabilities=ModelCapabilities("backup/model"))
        self.assertTrue(result.fallback_used)
        self.assertEqual(post.call_args_list[-1].kwargs["json"]["model"], "backup/model")
        self.assertTrue(any("fallback" in line.lower() for line in result.attempts))

    def test_transport_errors_are_retried(self):
        result, post = self.call([httpx.ConnectError("boom"), completion({"ok": 1})])
        self.assertEqual(post.call_count, 2)

    def test_result_carries_actual_cost(self):
        result, _ = self.call([completion({"ok": 1})])
        self.assertEqual(result.cost.reported_cost, 0.0031)
        self.assertEqual(result.generation_id, "gen-123")


class StructuredPipelineTests(unittest.TestCase):
    def setUp(self):
        patches = [
            mock.patch.object(openrouter, "get_capabilities", return_value=FULL_CAPS),
            mock.patch.object(openrouter, "get_api_key", return_value="k"),
            mock.patch.object(openrouter, "active_model", return_value="test/model"),
            mock.patch.object(openrouter, "fallback_model", return_value=None),
            mock.patch.object(openrouter, "_sleep"),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_qa_set_is_validated_and_ids_are_server_assigned(self):
        with mock.patch.object(openrouter.httpx, "post", return_value=completion({"questions": [qa_item(7), qa_item(9)]})) as post:
            document, result, warnings = run_qa(qa_request(PROFILE, "Balanced", 2), PROFILE, GenerationParams())
        self.assertEqual([q["question_id"] for q in document["questions"]], ["Q1", "Q2"])
        self.assertEqual(schema_errors(document, QA_DOCUMENT_SCHEMA), [])
        self.assertEqual(post.call_args.kwargs["json"]["response_format"]["type"], "json_schema")
        self.assertEqual(warnings, [])

    def test_malformed_json_gives_meaningful_error(self):
        with mock.patch.object(openrouter.httpx, "post", return_value=completion("{not json")):
            with self.assertRaises(GuardError) as caught:
                run_qa(qa_request(PROFILE, "Balanced", 1), PROFILE, GenerationParams())
        self.assertIn("unreadable", str(caught.exception))
        self.assertEqual(caught.exception.raw_text, "{not json")

    def test_schema_violation_lists_details(self):
        bad = qa_item(1)
        del bad["example_answer"]
        with mock.patch.object(openrouter.httpx, "post", return_value=completion({"questions": [bad]})):
            with self.assertRaises(SchemaValidationError) as caught:
                run_qa(qa_request(PROFILE, "Balanced", 1), PROFILE, GenerationParams())
        self.assertTrue(any("example_answer" in detail for detail in caught.exception.details))

    def test_wrong_difficulty_is_rejected(self):
        with mock.patch.object(openrouter.httpx, "post", return_value=completion({"questions": [qa_item(1, "Easy")]})):
            with self.assertRaises(SchemaValidationError):
                run_qa(qa_request(PROFILE, "Balanced", 1), PROFILE, GenerationParams())

    def test_evaluation_document_inserts_candidate_answer_server_side(self):
        tampered = dict(EVALUATION, candidate_answer="model rewrote this")
        with mock.patch.object(openrouter.httpx, "post", return_value=completion(EVALUATION)):
            document, _ = run_evaluation(evaluation_request(PROFILE, "Q?", "My real answer"), PROFILE, GenerationParams())
        self.assertEqual(document["candidate_answer"], "My real answer")
        with mock.patch.object(openrouter.httpx, "post", return_value=completion(tampered)):
            with self.assertRaises(SchemaValidationError):  # extra field rejected by additionalProperties
                run_evaluation(evaluation_request(PROFILE, "Q?", "My real answer"), PROFILE, GenerationParams())


class NewPageTests(unittest.TestCase):
    def setUp(self):
        from streamlit.testing.v1 import AppTest

        self.AppTest = AppTest
        catalog = {"test/model": FULL_ENTRY, "other/model": {"name": "Other", "supported_parameters": ["temperature", "max_tokens"], "pricing": {}}}
        patches = [
            mock.patch("interview_app.openrouter.model_catalog", return_value=catalog),
            mock.patch("interview_app.openrouter.httpx.post", side_effect=AssertionError("unexpected network call")),
            mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key", "OPENROUTER_MODEL": "test/model"}),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_settings_and_structured_pages_render(self):
        at = self.AppTest.from_file(str(ROOT / "app.py"), default_timeout=20).run()
        for page in ("app_pages/model_settings.py", "app_pages/structured_output.py"):
            at.switch_page(page).run()
            self.assertFalse(at.exception, f"{page}: {at.exception}")

    def test_settings_sync_disable_and_persist(self):
        at = self.AppTest.from_file(str(ROOT / "app.py"), default_timeout=20).run()
        at.switch_page("app_pages/model_settings.py").run()
        at.number_input(key="cfg_top_p_n").set_value(0.8).run()
        self.assertEqual(at.slider(key="cfg_top_p_s").value, 0.8)
        self.assertEqual(at.session_state.model_settings.top_p, 0.8)
        self.assertFalse(at.slider(key="cfg_top_k_s").disabled)
        self.assertTrue(at.slider(key="cfg_frequency_penalty_s").disabled)  # not in supported_parameters
        at.selectbox(key="cfg_provider").select("anthropic").run()  # only approved models are offered
        self.assertEqual(at.session_state.selected_model, "anthropic/claude-sonnet-5.5")
        self.assertTrue(at.selectbox(key="cfg_effort").disabled)


if __name__ == "__main__":
    unittest.main()

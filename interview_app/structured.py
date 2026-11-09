"""Structured JSON output formats: interview Q&A sets (Format 1) and evaluations (Format 2).

Pipeline for every call:
1. Build a ``StructuredRequest``: the system prompt, payload, schema, and expected output size.
   The same object drives the cost estimate and the real call, so the estimate prices what is sent.
2. Send it with the strongest output mode the model supports: JSON Schema (strict), then JSON
   mode, then prompt-only.
3. Validate the parsed JSON against the full schema server-side (always), then apply business
   rules (``semantic_errors_qa``), sanitise every string, and wrap the result in a document with
   server-controlled metadata. The final document is validated again against its document schema.
"""

from dataclasses import dataclass

from interview_app.catalog import FOCUS_KIND, PrepProfile
from interview_app.model_config import GenerationParams, ModelCapabilities
from interview_app.openrouter import ModelResult, complete_json
from interview_app.pricing import TYPICAL_OUTPUT_TOKENS, CostBreakdown, estimate_cost, estimate_input_tokens
from interview_app.prompts import structured_evaluation_prompt, structured_qa_prompt
from interview_app.schemas import (
    EVALUATION_DOCUMENT_SCHEMA,
    EVALUATION_FORMAT,
    EVALUATION_MODEL_SCHEMA,
    QA_DOCUMENT_SCHEMA,
    QA_FORMAT,
    QA_MODEL_SCHEMA,
    SCHEMA_VERSION,
    SchemaValidationError,
    build_metadata,
    sanitize_tree,
    semantic_errors_qa,
    validate_against,
)

MAX_QA_COUNT = 10
# Calibrated against live runs: Concise output was about half the Balanced size.
DEPTH_OUTPUT_FACTOR = {"Concise": 0.55, "Balanced": 1.0, "Detailed": 1.6}


@dataclass(frozen=True)
class StructuredRequest:
    system_prompt: str
    payload: dict
    schema: dict
    schema_name: str
    expected_output_tokens: int
    feature: str

    def params_for(self, params: GenerationParams) -> GenerationParams:
        """Ensure the output budget comfortably fits the expected response."""
        return params.with_min_tokens(int(self.expected_output_tokens * 1.6) + 200)


def qa_request(profile: PrepProfile, focus: str, count: int) -> StructuredRequest:
    count = max(1, min(MAX_QA_COUNT, int(count)))
    return StructuredRequest(
        system_prompt=structured_qa_prompt(profile),
        payload={"number_of_questions": count, "focus": f"{focus} ({FOCUS_KIND.get(focus, 'balanced mix')})"},
        schema=QA_MODEL_SCHEMA,
        schema_name=QA_FORMAT,
        expected_output_tokens=int(TYPICAL_OUTPUT_TOKENS["qa_item"] * count * DEPTH_OUTPUT_FACTOR[profile.depth]),
        feature="Structured Q&A set",
    )


def evaluation_request(profile: PrepProfile, question: str, answer: str, input_flags: tuple[str, ...] = ()) -> StructuredRequest:
    payload = {"interview_question": question, "candidate_answer": answer}
    if input_flags:
        payload["input_flags"] = list(input_flags)
    return StructuredRequest(
        system_prompt=structured_evaluation_prompt(profile),
        payload=payload,
        schema=EVALUATION_MODEL_SCHEMA,
        schema_name=EVALUATION_FORMAT,
        expected_output_tokens=int(TYPICAL_OUTPUT_TOKENS["evaluation"] * DEPTH_OUTPUT_FACTOR[profile.depth]),
        feature="Structured evaluation",
    )


def estimate_request_cost(request: StructuredRequest, caps: ModelCapabilities, params: GenerationParams) -> tuple[CostBreakdown, CostBreakdown]:
    """(typical, worst case). Worst case assumes the full max_tokens budget is used."""
    input_tokens = estimate_input_tokens(request.system_prompt, request.payload)
    budget = request.params_for(params).max_tokens
    if caps.max_completion_tokens:
        budget = min(budget, caps.max_completion_tokens)
    typical = min(request.expected_output_tokens, budget)
    return (
        estimate_cost(caps.model, caps.pricing, input_tokens, typical),
        estimate_cost(caps.model, caps.pricing, input_tokens, budget),
    )


def _raise_semantic(errors: list[str], result: ModelResult) -> None:
    error = SchemaValidationError(
        f"The AI's response broke {len(errors)} content rule{'s' if len(errors) != 1 else ''}. Please try again.", errors
    )
    error.raw_text = result.raw_text[:6000]
    raise error


def run_qa(request: StructuredRequest, profile: PrepProfile, params: GenerationParams) -> tuple[dict, ModelResult, list[str]]:
    result = complete_json(
        request.system_prompt, request.payload, request.params_for(params),
        schema=request.schema, schema_name=request.schema_name, feature=request.feature,
    )
    requested = request.payload["number_of_questions"]
    questions = result.data["questions"][:requested]
    errors = semantic_errors_qa({"questions": questions}, difficulty=profile.difficulty)
    if errors:
        _raise_semantic(errors, result)
    for position, item in enumerate(questions, start=1):
        item["question_id"] = f"Q{position}"  # server-assigned: stable, unique, machine-readable
    warnings = []
    if len(questions) < requested:
        warnings.append(f"The model returned {len(questions)} of the {requested} requested questions.")
    document = {
        "format": QA_FORMAT,
        "schema_version": SCHEMA_VERSION,
        "metadata": build_metadata(result.model, profile, result.output_mode),
        "questions": sanitize_tree(questions),
    }
    validate_against(document, QA_DOCUMENT_SCHEMA, "document")
    return document, result, warnings


def run_evaluation(request: StructuredRequest, profile: PrepProfile, params: GenerationParams) -> tuple[dict, ModelResult]:
    result = complete_json(
        request.system_prompt, request.payload, request.params_for(params),
        schema=request.schema, schema_name=request.schema_name, feature=request.feature,
    )
    document = {
        "format": EVALUATION_FORMAT,
        "schema_version": SCHEMA_VERSION,
        "metadata": build_metadata(result.model, profile, result.output_mode),
        "interview_question": request.payload["interview_question"],
        "candidate_answer": request.payload["candidate_answer"],  # server-inserted, never model-written
        **sanitize_tree(result.data),
    }
    validate_against(document, EVALUATION_DOCUMENT_SCHEMA, "document")
    return document, result

"""JSON Schemas for the structured interview-preparation formats, plus validation.

Each format has:
- a MODEL schema: what the LLM must return. A provider-safe copy (``wire_schema``) is sent as
  ``response_format.json_schema`` when the model supports structured outputs. Keywords that
  strict mode does not reliably support (min/max lengths, ranges) are stripped from that copy.
- a DOCUMENT schema: the final, downloadable document. The server adds deterministic fields
  (format name, schema version, metadata, the candidate answer) so they cannot be altered by the model.

The full schemas, including ranges and minimum sizes, are always enforced server-side with
``jsonschema``. Business rules that JSON Schema cannot express are checked in ``semantic_errors_*``.
"""

import copy
from datetime import datetime, timezone

from jsonschema import Draft202012Validator

from interview_app.security_guard import GuardError, clean_model_text

SCHEMA_VERSION = "1.0"
QA_FORMAT = "interview_qa_set"
EVALUATION_FORMAT = "interview_evaluation"

_STRICT_UNSUPPORTED = {"minItems", "maxItems", "minLength", "maxLength", "minimum", "maximum", "pattern", "format", "uniqueItems"}


def _string(min_length: int = 1, max_length: int = 4000) -> dict:
    return {"type": "string", "minLength": min_length, "maxLength": max_length}


def _string_list(min_items: int, max_items: int, max_length: int = 400) -> dict:
    return {"type": "array", "items": _string(1, max_length), "minItems": min_items, "maxItems": max_items}


def _object(properties: dict) -> dict:
    return {"type": "object", "additionalProperties": False, "required": list(properties), "properties": properties}


QA_ITEM_SCHEMA = _object({
    "question_id": _string(1, 12),
    "question": _string(10, 600),
    "category": {"type": "string", "enum": ["technical", "scenario", "behavioral"]},
    "difficulty": {"type": "string", "enum": ["Easy", "Medium", "Hard"]},
    "expected_answer": _string(20, 3000),
    "key_concepts": _string_list(2, 8, 120),
    "example_answer": _string(20, 4000),
    "follow_up_questions": _string_list(1, 4, 400),
    "evaluation_criteria": {
        "type": "array",
        "minItems": 2,
        "maxItems": 6,
        "items": _object({"criterion": _string(2, 120), "description": _string(5, 400)}),
    },
})

QA_MODEL_SCHEMA = _object({"questions": {"type": "array", "minItems": 1, "maxItems": 10, "items": QA_ITEM_SCHEMA}})

_SCORE = {"type": "integer", "minimum": 1, "maximum": 5}
_DIMENSION = _object({"score": _SCORE, "comment": _string(5, 600)})

EVALUATION_MODEL_SCHEMA = _object({
    "overall_score": _SCORE,
    "summary": _string(10, 800),
    "technical_accuracy": _DIMENSION,
    "communication_skills": _DIMENSION,
    "problem_solving": _DIMENSION,
    "strengths": _string_list(1, 5),
    "weaknesses": _string_list(1, 5),
    "missing_concepts": _string_list(0, 6),
    "improvement_suggestions": _string_list(1, 5),
    "recommended_follow_up_questions": _string_list(1, 4),
})

_METADATA = _object({
    "generated_at": _string(10, 40),
    "model": _string(1, 120),
    "domain": _string(1, 80),
    "role": _string(1, 80),
    "difficulty": {"type": "string", "enum": ["Easy", "Medium", "Hard"]},
    "output_mode": {"type": "string", "enum": ["json_schema", "json_object", "prompt"]},
})


def _document_schema(format_name: str, body: dict) -> dict:
    return _object({
        "format": {"type": "string", "const": format_name},
        "schema_version": {"type": "string", "const": SCHEMA_VERSION},
        "metadata": _METADATA,
        **body,
    })


QA_DOCUMENT_SCHEMA = _document_schema(QA_FORMAT, {"questions": QA_MODEL_SCHEMA["properties"]["questions"]})
EVALUATION_DOCUMENT_SCHEMA = _document_schema(EVALUATION_FORMAT, {
    "interview_question": _string(1, 600),
    "candidate_answer": _string(1, 8000),
    **EVALUATION_MODEL_SCHEMA["properties"],
})


def wire_schema(schema: dict) -> dict:
    """Copy of ``schema`` without keywords that strict structured-output modes may reject."""
    def strip(node):
        if isinstance(node, dict):
            return {key: strip(value) for key, value in node.items() if key not in _STRICT_UNSUPPORTED}
        if isinstance(node, list):
            return [strip(item) for item in node]
        return node
    return strip(copy.deepcopy(schema))


class SchemaValidationError(GuardError):
    """The model's JSON parsed but did not match the schema. ``details`` lists each violation."""

    def __init__(self, message: str, details: list[str]):
        super().__init__(message)
        self.details = details


def schema_errors(instance, schema: dict, limit: int = 8) -> list[str]:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda error: list(error.absolute_path))
    messages = []
    for error in errors[:limit]:
        path = "/".join(str(part) for part in error.absolute_path) or "(root)"
        messages.append(f"{path}: {error.message[:200]}")
    return messages


def validate_against(instance, schema: dict, what: str) -> None:
    errors = schema_errors(instance, schema)
    if errors:
        raise SchemaValidationError(
            f"The AI's {what} did not match the required structure ({len(errors)} problem{'s' if len(errors) != 1 else ''}). "
            "Try again, or choose a model that supports structured outputs.",
            errors,
        )


def sanitize_tree(node):
    """Apply output sanitisation to every string in a validated JSON tree."""
    if isinstance(node, str):
        return clean_model_text(node)
    if isinstance(node, list):
        return [sanitize_tree(item) for item in node]
    if isinstance(node, dict):
        return {key: sanitize_tree(value) for key, value in node.items()}
    return node


def semantic_errors_qa(data: dict, *, difficulty: str) -> list[str]:
    errors = []
    questions = data.get("questions", [])
    ids = [item.get("question_id") for item in questions]
    if len(set(ids)) != len(ids):
        errors.append("question_id values must be unique.")
    texts = [item.get("question", "").strip().lower() for item in questions]
    if len(set(texts)) != len(texts):
        errors.append("questions must not repeat.")
    wrong = [item.get("question_id") for item in questions if item.get("difficulty") != difficulty]
    if wrong:
        errors.append(f"difficulty must be {difficulty} for every question (wrong for {', '.join(map(str, wrong))}).")
    return errors


def build_metadata(model: str, profile, output_mode: str) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": model,
        "domain": profile.domain,
        "role": profile.role,
        "difficulty": profile.difficulty,
        "output_mode": output_mode,
    }

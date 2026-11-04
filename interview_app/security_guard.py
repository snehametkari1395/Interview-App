"""Input and output boundaries for untrusted text and model responses."""

import json


class GuardError(ValueError):
    """Raised when input or model output does not meet the app's boundaries."""


def validate_text(value: str, field_name: str, max_chars: int) -> str:
    text = value.strip()
    if not text:
        raise GuardError(f"Please enter {field_name} before continuing.")
    if len(text) > max_chars:
        raise GuardError(f"{field_name.capitalize()} must be {max_chars:,} characters or fewer.")
    return text


def parse_json_object(content: str) -> dict:
    """Accept only a JSON object, including one wrapped in a Markdown fence."""
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].removesuffix("```").strip()
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise GuardError("The AI returned an unreadable response. Please try again.") from error
    if not isinstance(result, dict):
        raise GuardError("The AI response did not match the expected format. Please try again.")
    return result


def text_field(data: dict, key: str, max_chars: int = 1200) -> str:
    value = data.get(key, "")
    if not isinstance(value, str):
        return ""
    return value.strip()[:max_chars]


def list_field(data: dict, key: str, limit: int = 8, max_chars: int = 500) -> list[str]:
    value = data.get(key, [])
    if not isinstance(value, list):
        return []
    return [item.strip()[:max_chars] for item in value if isinstance(item, str) and item.strip()][:limit]
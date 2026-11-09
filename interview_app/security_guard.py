"""Input and output boundaries for untrusted text and model responses.

This module is the app's primary, deterministic security layer. Everything here is plain
code: it behaves the same on every run, costs nothing, and cannot be talked out of its rules.
The optional LLM screen (``security_lab``) is an advisory second opinion only.
"""

import json
import re
import time
import unicodedata
from dataclasses import dataclass, field


class GuardError(ValueError):
    """Raised when input or model output does not meet the app's boundaries."""


# A canary token embedded in every system prompt. If it ever appears in model output,
# the model has been coaxed into echoing its instructions and the response is discarded.
PROMPT_CANARY = "FN-CANARY-7Q4K9"

# ---------------------------------------------------------------------------
# Input sanitisation and validation
# ---------------------------------------------------------------------------

_INVISIBLE = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_CHAT_TEMPLATE_TOKEN = re.compile(r"<\|[^|<>\n]{1,40}\|>|\[/?INST\]|<</?SYS>>", re.IGNORECASE)
_REPEATED_RUN = re.compile(r"(.)\1{199,}", re.DOTALL)


def sanitize_text(value: str) -> str:
    """Normalise untrusted text without changing its meaning.

    - NFKC normalisation folds look-alike characters (full-width letters, ligatures) so
      pattern checks cannot be dodged with Unicode tricks.
    - Zero-width and bidirectional-override characters are removed; they are invisible to
      the user but can hide or reorder instructions.
    - Control characters other than newline and tab are removed.
    - Chat-template tokens such as ``<|im_start|>`` are neutralised so pasted text cannot
      imitate a message boundary.
    """
    text = unicodedata.normalize("NFKC", value)
    text = _INVISIBLE.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL.sub("", text)
    text = _CHAT_TEMPLATE_TOKEN.sub("[token removed]", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def validate_text(value: str, field_name: str, max_chars: int) -> str:
    """Sanitise, then enforce presence and size limits. Returns the clean text."""
    text = sanitize_text(value or "")
    if not text:
        raise GuardError(f"Please enter {field_name} before continuing.")
    if len(text) > max_chars:
        raise GuardError(f"{field_name.capitalize()} must be {max_chars:,} characters or fewer.")
    if _REPEATED_RUN.search(text):
        raise GuardError(f"{field_name.capitalize()} contains a long run of repeated characters. Please remove it.")
    return text


def require_choice(value: str, options, field_name: str) -> str:
    """Allow only values from a known list (used for anything that reaches a system prompt)."""
    if value not in options:
        raise GuardError(f"Please choose a valid {field_name}.")
    return value


# ---------------------------------------------------------------------------
# Prompt-injection heuristics
# ---------------------------------------------------------------------------

INJECTION_PATTERNS: dict[str, re.Pattern] = {
    "instruction_override": re.compile(
        r"\b(ignore|disregard|forget|override|bypass)\b[^.\n]{0,40}?\b(previous|prior|above|earlier|all|any|system|your|these)\b"
        r"[^.\n]{0,30}?\b(instructions?|rules|prompts?|directions|guidelines|polic(y|ies))\b",
        re.IGNORECASE,
    ),
    "prompt_exfiltration": re.compile(
        r"\b(reveal|show|print|repeat|output|display|leak|dump|tell me|what (is|are))\b[^.\n]{0,40}?"
        r"\b(system|hidden|initial|original|developer|secret)\s+(prompt|instructions?|message|rules)\b",
        re.IGNORECASE,
    ),
    "role_hijack": re.compile(
        r"\byou are (now|no longer)\b|\b(developer|god|admin|jailbreak|DAN)\s+mode\b|\bpretend (to be|you are)\b"
        r"|\bact as (an? )?(unrestricted|unfiltered|system|admin|developer|evaluator that)\b|\bnew instructions\s*:",
        re.IGNORECASE,
    ),
    "score_manipulation": re.compile(
        r"\b(give|award|assign)\s+(me|this( answer)?|the candidate|it)\s+(a\s+)?(score|rating|grade|mark)\s+(of\s+)?(5|five|full|perfect|maximum)\b"
        r"|\b(score|rate|grade|mark)\s+(me|this( answer)?|it)\s+(a\s+|as\s+)?(5|five|perfect|maximum|highest|full marks)\b"
        r"|\bthis answer (deserves|should (get|receive)|must (get|receive))\s+(a\s+)?(5|five|perfect|full marks|the highest)\b"
        r"|[\"']score[\"']\s*:\s*[45]\b",
        re.IGNORECASE,
    ),
    "role_header": re.compile(r"^\s*(#{1,6}\s*|\[)?(system|assistant|developer)\s*(\]|:)\s*", re.IGNORECASE | re.MULTILINE),
    "encoded_payload": re.compile(r"[A-Za-z0-9+/]{160,}={0,2}"),
}

FLAG_DESCRIPTIONS = {
    "instruction_override": "Asks the AI to ignore or override its instructions",
    "prompt_exfiltration": "Asks the AI to reveal hidden or system instructions",
    "role_hijack": "Tries to change the AI's role or switch it into a special mode",
    "score_manipulation": "Tries to dictate the score the evaluator should give",
    "role_header": "Imitates a system or assistant message header",
    "encoded_payload": "Contains a long encoded blob that could hide instructions",
    "hidden_characters": "Contained invisible or direction-changing characters (removed)",
    "template_tokens": "Contained chat-template control tokens (neutralised)",
}


@dataclass(frozen=True)
class InputAssessment:
    risk: str  # "low" | "medium" | "high"
    flags: tuple[str, ...] = field(default_factory=tuple)
    blocked: bool = False

    @property
    def message(self) -> str:
        if self.blocked:
            return (
                "This text looks like it is trying to instruct the AI evaluator (for example, by dictating a score). "
                "Please remove those instructions and submit your answer on its own merits."
            )
        if self.flags:
            return (
                "Parts of this text look like instructions to an AI. They will be treated as ordinary content, "
                "not followed. If you are quoting an attack as part of your answer, that is fine."
            )
        return ""


def assess_input(raw_text: str) -> InputAssessment:
    """Classify untrusted text by deterministic rules.

    Policy, chosen to limit false positives: a candidate answering "How would you handle prompt
    injection?" may legitimately quote "ignore previous instructions". So most flags only add a
    warning and are passed to the model as metadata. Text is blocked only when it tries to
    dictate the score (no legitimate use in an answer) or trips three or more categories at once.
    """
    flags: list[str] = []
    if _INVISIBLE.search(raw_text or ""):
        flags.append("hidden_characters")
    if _CHAT_TEMPLATE_TOKEN.search(raw_text or ""):
        flags.append("template_tokens")
    normalized = unicodedata.normalize("NFKC", raw_text or "")
    normalized = _INVISIBLE.sub("", normalized)
    for name, pattern in INJECTION_PATTERNS.items():
        if pattern.search(normalized):
            flags.append(name)

    active = [flag for flag in flags if flag != "hidden_characters"]
    blocked = "score_manipulation" in flags or len(active) >= 3
    risk = "high" if blocked else ("medium" if flags else "low")
    return InputAssessment(risk=risk, flags=tuple(flags), blocked=blocked)


def guard_untrusted_input(value: str, field_name: str, max_chars: int) -> tuple[str, InputAssessment]:
    """Validate, sanitise, and assess one piece of user text. Raises GuardError when blocked."""
    assessment = assess_input(value or "")
    clean = validate_text(value, field_name, max_chars)
    if assessment.blocked:
        raise GuardError(assessment.message)
    return clean, assessment


# ---------------------------------------------------------------------------
# Model-output validation
# ---------------------------------------------------------------------------

_MD_IMAGE = re.compile(r"!\[[^\]]{0,300}\]\([^)]{0,2000}\)")
_MD_LINK = re.compile(r"\[([^\]]{1,300})\]\([^)]{0,2000}\)")
_HTML_TAG = re.compile(r"</?[A-Za-z][^>]{0,300}>")


def check_for_prompt_leak(content: str) -> None:
    if PROMPT_CANARY in content:
        raise GuardError("The AI response was withheld because it appeared to echo protected instructions. Please try again.")


def parse_json_object(content: str) -> dict:
    """Accept only a JSON object, including one wrapped in a Markdown fence or brief prose."""
    check_for_prompt_leak(content)
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].removesuffix("```").strip()
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise GuardError("The AI returned an unreadable response. Please try again.") from None
        try:
            result = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as error:
            raise GuardError("The AI returned an unreadable response. Please try again.") from error
    if not isinstance(result, dict):
        raise GuardError("The AI response did not match the expected format. Please try again.")
    return result


def clean_model_text(value: str) -> str:
    """Strip content that could act on the viewer's browser when rendered as Markdown.

    Markdown images are removed entirely: an injected image URL is a classic way to exfiltrate
    data, because the browser fetches it automatically. Links keep their text but lose the URL,
    and raw HTML tags are dropped.
    """
    text = _MD_IMAGE.sub("", value)
    text = _MD_LINK.sub(r"\1", text)
    text = _HTML_TAG.sub("", text)
    return text.strip()


def text_field(data: dict, key: str, max_chars: int = 1200) -> str:
    value = data.get(key, "")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        return ""
    return clean_model_text(value)[:max_chars].strip()


def list_field(data: dict, key: str, limit: int = 8, max_chars: int = 500) -> list[str]:
    value = data.get(key, [])
    if not isinstance(value, list):
        return []
    items = [clean_model_text(item)[:max_chars].strip() for item in value if isinstance(item, str)]
    return [item for item in items if item][:limit]


def int_field(data: dict, key: str, low: int, high: int, default: int) -> int:
    value = data.get(key, default)
    if isinstance(value, bool):
        return default
    try:
        return max(low, min(high, int(round(float(value)))))
    except (TypeError, ValueError):
        return default


def choice_field(data: dict, key: str, options: tuple[str, ...], default: str) -> str:
    value = data.get(key, default)
    if not isinstance(value, str):
        return default
    lowered = value.strip().lower()
    for option in options:
        if option.lower() == lowered:
            return option
    return default


def dict_list_field(data: dict, key: str, schema: dict[str, int], limit: int, required: str | None = None) -> list[dict[str, str]]:
    """Coerce a list of objects to ``{field: str}`` dicts using ``schema`` (field -> max chars)."""
    value = data.get(key, [])
    if not isinstance(value, list):
        return []
    rows = []
    for item in value:
        if not isinstance(item, dict):
            continue
        row = {name: text_field(item, name, max_chars) for name, max_chars in schema.items()}
        if required and not row.get(required):
            continue
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows


# ---------------------------------------------------------------------------
# Secrets and abuse limits
# ---------------------------------------------------------------------------

_SECRET_PATTERNS = (
    re.compile(r"sk-or-v1-[A-Za-z0-9]{16,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]{12,}", re.IGNORECASE),
    re.compile(r"((?:api[_-]?key|secret|token|password)\s*[=:]\s*)[\"']?[^\s\"']{6,}[\"']?", re.IGNORECASE),
)


def redact_secrets(text: str, *known_secrets: str) -> str:
    """Remove anything that looks like a credential before text is logged or sent anywhere."""
    for secret in known_secrets:
        if secret and len(secret) >= 8:
            text = text.replace(secret, "[REDACTED]")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda match: (match.group(1) if match.groups() else "") + "[REDACTED]", text)
    return text


def check_rate_limit(history: list[float], *, cost: int = 1, limit: int = 40, window_s: float = 600.0, now: float | None = None) -> None:
    """Sliding-window limit on model calls per browser session. Mutates ``history`` in place."""
    now = time.time() if now is None else now
    history[:] = [stamp for stamp in history if now - stamp < window_s]
    if len(history) + cost > limit:
        wait = int(window_s - (now - history[0])) + 1 if history else int(window_s)
        raise GuardError(f"You've reached the limit of {limit} AI requests per {int(window_s // 60)} minutes. Please wait about {max(wait, 1)} seconds.")
    history.extend([now] * cost)

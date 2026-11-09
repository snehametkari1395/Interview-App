"""OpenRouter client; all model traffic passes through this module.

Security notes:
- The API key is read server-side (environment variable or ``st.secrets``) and is only ever placed
  in the Authorization header. It is never rendered, returned to callers, or logged.
- Errors shown to users are mapped to fixed, friendly messages. Raw exception text and provider
  response bodies are never displayed, and anything logged passes through ``redact_secrets``.

Reliability (chosen improvement, based on the OpenRouter errors, limits, and provider-routing docs):
- Transient failures (HTTP 408/429/500/502/503/504, timeouts, connection errors, and errors that
  arrive inside an HTTP 200 body) are retried with exponential backoff and jitter. ``Retry-After``
  is honoured when present.
- Requests set ``provider.require_parameters`` so OpenRouter routes only to providers that honour
  every parameter sent. If no provider qualifies (HTTP 503), the request is retried once without
  that guarantee, and the result is labelled so the user knows.
- An optional fallback model is tried when the primary model is unavailable. Authentication,
  credit, and moderation errors are never retried or failed over.
"""

import json
import logging
import os
import random
import time
from dataclasses import dataclass, field

import httpx
import streamlit as st

from interview_app.model_config import (
    GenerationParams,
    ModelCapabilities,
    build_request_body,
    capabilities_from_catalog_entry,
)
from interview_app.pricing import CostBreakdown, actual_cost, extract_usage
from interview_app.schemas import trim_to_schema, validate_against, wire_schema
from interview_app.security_guard import GuardError, check_rate_limit, parse_json_object, redact_secrets

API_BASE = "https://openrouter.ai/api/v1"
API_URL = f"{API_BASE}/chat/completions"
MODELS_URL = f"{API_BASE}/models"
KEY_URL = f"{API_BASE}/key"
# Models approved for this project (the account's OpenRouter guardrail allows only these).
ALLOWED_MODELS = ("openai/gpt-6-luna", "anthropic/claude-sonnet-5.5", "openai/gpt-6.1-sol")
DEFAULT_MODEL = ALLOWED_MODELS[0]  # recommended default
ALLOWED_EMBEDDING_MODELS = ("qwen/qwen3-embedding-8b", "openai/text-embedding-3-small", "openai/text-embedding-3-large")
DEFAULT_EMBEDDING_MODEL = ALLOWED_EMBEDDING_MODELS[0]  # recommended default
REQUEST_TIMEOUT_S = 90.0

RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})
FAILOVER_STATUS = RETRYABLE_STATUS | {404}
MAX_ATTEMPTS = 3
BASE_BACKOFF_S = 1.0
MAX_BACKOFF_S = 8.0
MAX_RETRY_AFTER_S = 20.0
_sleep = time.sleep  # replaced in tests

logger = logging.getLogger("interview_app.openrouter")


class ModelServiceError(RuntimeError):
    """A model call failed; ``str(error)`` is always safe to show to the user."""


class ProviderError(ModelServiceError):
    """An error object returned inside an HTTP 200 body."""

    def __init__(self, message: str, status: int | None):
        super().__init__(message)
        self.status = status


@dataclass
class ModelResult:
    data: dict
    raw_text: str
    model: str
    latency_s: float
    usage: dict = field(default_factory=dict)
    finish_reason: str | None = None
    applied_params: dict = field(default_factory=dict)
    skipped_params: tuple[str, ...] = ()
    output_mode: str = "prompt"
    requested_model: str = ""
    generation_id: str = ""
    cost: CostBreakdown | None = None
    attempts: tuple[str, ...] = ()
    fallback_used: bool = False
    params_guaranteed: bool = False


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _config_value(name: str, default: str = "") -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    try:
        return str(st.secrets.get(name, default)).strip()
    except Exception:
        return default


def get_api_key() -> str:
    return _config_value("OPENROUTER_API_KEY")


def get_model() -> str:
    """The configured default model (environment or secrets)."""
    return _config_value("OPENROUTER_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL


def _session_get(key: str):
    try:
        return st.session_state.get(key)
    except Exception:  # outside a Streamlit session (e.g. unit tests)
        return None


def active_model() -> str:
    """The model chosen on the Model settings page, else the configured default."""
    selected = _session_get("selected_model")
    return selected if isinstance(selected, str) and selected else get_model()


def fallback_model() -> str | None:
    selected = _session_get("fallback_model")
    if isinstance(selected, str):
        return selected or None
    return _config_value("OPENROUTER_FALLBACK_MODEL") or None


@st.cache_data(ttl=3600, show_spinner=False, max_entries=1)
def _fetch_model_catalog() -> dict[str, dict]:
    """Public model list with capabilities and pricing. Failures are not cached."""
    response = httpx.get(MODELS_URL, timeout=20.0)
    response.raise_for_status()
    models = response.json().get("data", [])
    return {
        item["id"]: {
            "name": item.get("name", item["id"]),
            "description": str(item.get("description") or "")[:600],
            "supported_parameters": item.get("supported_parameters") or [],
            "context_length": item.get("context_length"),
            "top_provider": item.get("top_provider") or {},
            "pricing": item.get("pricing") or {},
            "architecture": item.get("architecture") or {},
            "reasoning": item.get("reasoning") or {},
        }
        for item in models
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }


def model_catalog() -> dict[str, dict]:
    try:
        return _fetch_model_catalog()
    except Exception as error:  # network issues must never break the app
        logger.warning("Could not load the OpenRouter model catalog: %s", type(error).__name__)
        return {}


def refresh_model_catalog() -> None:
    _fetch_model_catalog.clear()


def get_capabilities(model: str | None = None) -> ModelCapabilities:
    model = model or active_model()
    return capabilities_from_catalog_entry(model, model_catalog().get(model))


def get_key_info(api_key: str) -> dict:
    """Credit and limit information for the configured key (whitelisted numeric fields only)."""
    response = httpx.get(KEY_URL, headers={"Authorization": f"Bearer {api_key}"}, timeout=15.0)
    response.raise_for_status()
    data = response.json().get("data", {})
    allowed = ("limit", "limit_remaining", "limit_reset", "usage", "usage_daily", "usage_weekly", "usage_monthly", "is_free_tier")
    return {key: data.get(key) for key in allowed if isinstance(data, dict) and key in data}


# ---------------------------------------------------------------------------
# Session accounting
# ---------------------------------------------------------------------------


def _session_history() -> list[float] | None:
    try:
        return st.session_state.setdefault("_llm_call_history", [])
    except Exception:
        return None


def reserve_calls(count: int = 1) -> None:
    """Apply the per-session rate limit before making ``count`` model calls."""
    history = _session_history()
    if history is not None:
        check_rate_limit(history, cost=count)


def record_usage(result: "ModelResult", feature: str = "") -> None:
    """Keep a per-session log of model calls and their actual cost."""
    try:
        log = st.session_state.setdefault("usage_log", [])
    except Exception:
        return
    cost = result.cost
    log.append({
        "feature": feature,
        "model": result.model,
        "input_tokens": cost.input_tokens if cost else None,
        "output_tokens": cost.output_tokens if cost else None,
        "cost_usd": cost.best_total if cost else None,
    })
    del log[:-200]
    st.session_state.last_call = result


def session_spend() -> tuple[int, float]:
    log = _session_get("usage_log") or []
    return len(log), sum(item["cost_usd"] or 0.0 for item in log)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def _sdk_status(error: Exception) -> int | None:
    """HTTP status of an error raised by the OpenRouter Python SDK (used by LangChain's ChatOpenRouter)."""
    try:
        from openrouter.errors import OpenRouterError
    except ImportError:  # pragma: no cover - SDK is a dependency of langchain-openrouter
        return None
    if isinstance(error, OpenRouterError):
        status = getattr(getattr(error, "raw_response", None), "status_code", None)
        return status if isinstance(status, int) else None
    return None


def _status_of(error: Exception) -> int | None:
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code
    if isinstance(error, ProviderError):
        return error.status
    return _sdk_status(error)


def describe_error(error: Exception) -> str:
    """Map any exception to a message that is safe and useful to show the user."""
    if isinstance(error, (GuardError, ModelServiceError)):
        return str(error)
    if isinstance(error, httpx.TimeoutException):
        return "The AI service took too long to respond. Please try again, or lower max output tokens."
    sdk_status = _sdk_status(error)
    if isinstance(error, httpx.HTTPStatusError) or sdk_status is not None:
        status = sdk_status if sdk_status is not None else error.response.status_code
        messages = {
            400: "The AI service rejected the request. Try a different model or parameter settings.",
            401: "The OpenRouter API key was rejected. Check OPENROUTER_API_KEY.",
            402: "Your OpenRouter account has insufficient credits for this request.",
            403: "This request was blocked by the AI provider's moderation or access rules.",
            404: "The selected model is unavailable to this account: it was not found, or an OpenRouter guardrail or data policy blocks it. Choose another model in Model settings or adjust your OpenRouter guardrails.",
            408: "The AI service timed out. Please try again.",
            413: "The request was too large for this model. Shorten the input.",
            429: "The AI service is rate-limiting requests. Please wait a moment and try again.",
            503: "No provider for this model can serve the request with the current settings. Try another model.",
        }
        if status in messages:
            return messages[status]
        if status >= 500:
            return "The AI service is temporarily unavailable. Please try again shortly."
        return f"The AI service returned an error (HTTP {status})."
    if isinstance(error, httpx.HTTPError) or type(error).__name__ == "NoResponseError":
        return "Could not reach the AI service. Check your internet connection and try again."
    if type(error).__name__ == "ResponseValidationError":
        return "OpenRouter returned an unexpected response. Please try again."
    logger.exception("Unexpected error during model call")
    return "Something went wrong while contacting the AI service. Please try again."


# ---------------------------------------------------------------------------
# Transport with retries
# ---------------------------------------------------------------------------


def _retry_delay(attempt: int, retry_after: str | None) -> float:
    if retry_after:
        try:
            return min(MAX_RETRY_AFTER_S, max(0.0, float(retry_after)))
        except ValueError:
            pass
    return min(MAX_BACKOFF_S, BASE_BACKOFF_S * 2 ** (attempt - 1)) + random.uniform(0, 0.3)


def _post_with_retries(body: dict, api_key: str, log: list[str], client: httpx.Client | None = None) -> dict:
    model = body.get("model", "")
    sender = client if client is not None else httpx
    for attempt in range(1, MAX_ATTEMPTS + 1):
        last_attempt = attempt == MAX_ATTEMPTS
        try:
            response = sender.post(
                API_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "X-Title": "Fieldnotes Interview Practice"},
                json=body,
                timeout=REQUEST_TIMEOUT_S,
            )
        except httpx.TransportError as error:  # includes timeouts
            if last_attempt:
                raise
            delay = _retry_delay(attempt, None)
            log.append(f"{model}: {type(error).__name__}, retrying in {delay:.1f}s")
            _sleep(delay)
            continue

        if response.status_code in RETRYABLE_STATUS and not last_attempt:
            delay = _retry_delay(attempt, response.headers.get("Retry-After"))
            log.append(f"{model}: HTTP {response.status_code}, retrying in {delay:.1f}s")
            _sleep(delay)
            continue
        if response.status_code >= 400:
            logger.warning("OpenRouter HTTP %s for model %s: %s", response.status_code, model, redact_secrets(response.text[:300], api_key))
            response.raise_for_status()

        try:
            payload = response.json()
        except ValueError as error:
            raise ModelServiceError("OpenRouter returned an unexpected response. Please try again.") from error
        if not isinstance(payload, dict):
            raise ModelServiceError("OpenRouter returned an unexpected response. Please try again.")
        error_body = payload.get("error")
        if error_body:
            code = error_body.get("code") if isinstance(error_body, dict) else None
            code = code if isinstance(code, int) else None
            if code in RETRYABLE_STATUS and not last_attempt:
                delay = _retry_delay(attempt, None)
                log.append(f"{model}: provider error {code}, retrying in {delay:.1f}s")
                _sleep(delay)
                continue
            logger.warning("OpenRouter error payload for model %s (code %s)", model, code)
            raise ProviderError("The AI provider reported an error for this request. Please try again or choose another model.", code)
        return payload
    raise ModelServiceError("The AI service did not respond successfully. Please try again.")  # pragma: no cover


# ---------------------------------------------------------------------------
# Model calls
# ---------------------------------------------------------------------------


def _parse_result(payload: dict, plan, route_model: str, caps: ModelCapabilities, schema: dict | None) -> tuple[dict, str, str | None]:
    try:
        choice = payload["choices"][0]
        content = choice["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise ModelServiceError("OpenRouter returned an unexpected response. Please try again.") from error
    finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None

    if not isinstance(content, str) or not content.strip():
        if finish_reason == "length":
            raise GuardError("The model used its whole output budget before answering (often on reasoning). Increase max output tokens or lower reasoning effort.")
        raise ModelServiceError("The model returned an empty response. Please try again.")
    try:
        data = parse_json_object(content)
        if schema is not None:
            data, _repairs = trim_to_schema(data, schema)
            validate_against(data, schema, "response")
    except GuardError as error:
        error.raw_text = content[:6000]
        if finish_reason == "length":
            truncated = GuardError("The response was cut off before it finished. Increase max output tokens and try again.")
            truncated.raw_text = content[:6000]
            raise truncated from None
        raise
    return data, content, finish_reason


def call_model(
    system_prompt: str,
    user_payload: dict,
    *,
    params: GenerationParams,
    model: str,
    api_key: str,
    capabilities: ModelCapabilities,
    schema: dict | None = None,
    schema_name: str = "response",
    fallback: str | None = None,
    fallback_capabilities: ModelCapabilities | None = None,
    client: httpx.Client | None = None,
) -> ModelResult:
    """Make one JSON chat completion with retries and failover. Thread-safe: no Streamlit state.

    ``client`` lets callers inject a transport (e.g. ``httpx.MockTransport`` in the security suite)
    without patching module globals.
    """
    if not api_key:
        raise ModelServiceError("Add OPENROUTER_API_KEY to your environment or .streamlit/secrets.toml to enable AI features.")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=True)},
    ]
    request_schema = wire_schema(schema) if schema is not None else None
    routes: list[tuple[str, str, ModelCapabilities, bool]] = [("primary", model, capabilities, True)]
    if capabilities.known:
        routes.append(("relaxed", model, capabilities, False))
    if fallback and fallback != model:
        routes.append(("fallback", fallback, fallback_capabilities or ModelCapabilities(fallback), True))

    attempts: list[str] = []
    last_error: Exception | None = None
    started = time.perf_counter()
    for kind, route_model, caps, require in routes:
        if kind == "relaxed" and _status_of(last_error) != 503:
            continue
        if kind == "relaxed":
            attempts.append(f"{route_model}: no provider supports every parameter; retrying without that guarantee")
        plan = build_request_body(route_model, messages, params, caps, schema=request_schema, schema_name=schema_name, require_parameters=require)
        try:
            payload = _post_with_retries(plan.body, api_key, attempts, client)
        except Exception as error:
            last_error = error
            if _status_of(error) in FAILOVER_STATUS or isinstance(error, httpx.TransportError):
                attempts.append(f"{route_model}: failed ({describe_error(error)})")
                continue
            raise
        if kind == "fallback":
            attempts.append(f"Served by fallback model {route_model}")
        data, content, finish_reason = _parse_result(payload, plan, route_model, caps, schema)
        usage = extract_usage(payload.get("usage"))
        served = str(payload.get("model") or route_model)
        return ModelResult(
            data=data,
            raw_text=content,
            model=served,
            requested_model=model,
            latency_s=time.perf_counter() - started,
            usage=usage,
            finish_reason=finish_reason,
            applied_params=plan.applied,
            skipped_params=plan.skipped,
            output_mode=plan.output_mode,
            generation_id=str(payload.get("id") or "")[:80],
            cost=actual_cost(served, caps.pricing, usage),
            attempts=tuple(attempts),
            fallback_used=kind == "fallback",
            params_guaranteed=require and caps.known,
        )
    assert last_error is not None
    raise last_error


def current_params() -> GenerationParams:
    """The user's model settings (defaults outside a session)."""
    stored = _session_get("model_settings")
    if isinstance(stored, GenerationParams):
        return stored.validated()
    return GenerationParams()


def complete_json(
    system_prompt: str,
    user_payload: dict,
    params: GenerationParams | None = None,
    model: str | None = None,
    *,
    schema: dict | None = None,
    schema_name: str = "response",
    feature: str = "",
) -> ModelResult:
    """Session-aware entry point: resolves key, model, fallback, capabilities, and the rate limit."""
    model = model or active_model()
    backup = fallback_model()
    reserve_calls(1)
    result = call_model(
        system_prompt,
        user_payload,
        params=(params or current_params()),
        model=model,
        api_key=get_api_key(),
        capabilities=get_capabilities(model),
        schema=schema,
        schema_name=schema_name,
        fallback=backup,
        fallback_capabilities=get_capabilities(backup) if backup else None,
    )
    record_usage(result, feature)
    return result


def chat_json(system_prompt: str, user_payload: dict, params: GenerationParams | None = None) -> dict:
    """Backwards-compatible helper returning only the parsed JSON object."""
    return complete_json(system_prompt, user_payload, params).data

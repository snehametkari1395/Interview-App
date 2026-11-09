"""LangChain model construction for the workflows.

``build_llm`` turns the app's model settings into a ``ChatOpenRouter`` (langchain-openrouter).
It reuses ``build_request_body`` so the LangChain path sends exactly the parameters the rest of
the app would: only supported parameters, ``provider.require_parameters`` when capabilities are
known, and JSON Schema / JSON mode when the model supports it.

Resilience uses LangChain's native ``with_fallbacks``:
1. primary model (the SDK retries transient errors with exponential backoff),
2. the same model without ``require_parameters`` if no provider supports every parameter (HTTP 503),
3. the configured fallback model on transient or availability errors.
Auth, credit, and moderation errors are never failed over.
"""

from dataclasses import dataclass

from langchain_core.runnables import Runnable
from langchain_openrouter import ChatOpenRouter
from openrouter import errors as sdk_errors

from interview_app.model_config import GenerationParams, ModelCapabilities, RequestPlan, build_request_body
from interview_app.openrouter import (
    active_model,
    current_params,
    fallback_model,
    get_api_key,
    get_capabilities,
)
from interview_app.schemas import wire_schema

REQUEST_TIMEOUT_MS = 90_000
SDK_RETRIES = 2
_EXPLICIT_FIELDS = ("temperature", "max_tokens", "top_p", "frequency_penalty", "presence_penalty", "seed")
_EXTRA_FIELDS = ("top_k", "repetition_penalty", "min_p", "top_a", "response_format")

UNAVAILABLE_ERRORS = (sdk_errors.ServiceUnavailableResponseError,)
TRANSIENT_ERRORS = (
    sdk_errors.BadGatewayResponseError,
    sdk_errors.InternalServerResponseError,
    sdk_errors.ServiceUnavailableResponseError,
    sdk_errors.ProviderOverloadedResponseError,
    sdk_errors.TooManyRequestsResponseError,
    sdk_errors.NotFoundResponseError,
    sdk_errors.RequestTimeoutResponseError,
    sdk_errors.EdgeNetworkTimeoutResponseError,
    sdk_errors.NoResponseError,
)


@dataclass(frozen=True)
class ModelSpec:
    """Everything a chain needs to call one model. Safe to pass to worker threads."""

    model: str
    params: GenerationParams
    capabilities: ModelCapabilities
    api_key: str
    fallback: "ModelSpec | None" = None

    def with_params(self, params: GenerationParams) -> "ModelSpec":
        fallback = self.fallback.with_params(params) if self.fallback else None
        return ModelSpec(self.model, params, self.capabilities, self.api_key, fallback)


def spec_from_session(model: str | None = None, params: GenerationParams | None = None) -> ModelSpec:
    """Resolve the active model, settings, key, and fallback in the main Streamlit thread."""
    model = model or active_model()
    params = params or current_params()
    api_key = get_api_key()
    backup = fallback_model()
    fallback = ModelSpec(backup, params, get_capabilities(backup), api_key) if backup and backup != model else None
    return ModelSpec(model, params, get_capabilities(model), api_key, fallback)


def _chat_model(spec: ModelSpec, plan: RequestPlan, streaming: bool) -> ChatOpenRouter:
    body = plan.body
    return ChatOpenRouter(
        model_name=spec.model,
        openrouter_api_key=spec.api_key,
        **{field: body[field] for field in _EXPLICIT_FIELDS if field in body},
        reasoning=body.get("reasoning"),
        openrouter_provider=body.get("provider"),
        model_kwargs={field: body[field] for field in _EXTRA_FIELDS if field in body},
        streaming=streaming,
        stream_usage=True,
        max_retries=SDK_RETRIES,
        request_timeout=REQUEST_TIMEOUT_MS,
        app_title="Fieldnotes Interview Practice",
    )


def build_llm(
    spec: ModelSpec,
    *,
    schema: dict | None = None,
    schema_name: str = "response",
    streaming: bool = False,
) -> tuple[Runnable, RequestPlan]:
    """Return (runnable chat model with fallbacks, request plan of the primary model)."""
    request_schema = wire_schema(schema) if schema is not None else None

    def plan_for(target: ModelSpec, require: bool) -> RequestPlan:
        plan = build_request_body(target.model, [], target.params, target.capabilities,
                                  schema=request_schema, schema_name=schema_name, require_parameters=require)
        if schema is None:  # free-text output (streamed reply): no response_format
            plan.body.pop("response_format", None)
        return plan

    primary_plan = plan_for(spec, True)
    runnable: Runnable = _chat_model(spec, primary_plan, streaming)
    if spec.capabilities.known:
        relaxed = _chat_model(spec, plan_for(spec, False), streaming)
        runnable = runnable.with_fallbacks([relaxed], exceptions_to_handle=UNAVAILABLE_ERRORS)
    if spec.fallback is not None:
        backup = _chat_model(spec.fallback, plan_for(spec.fallback, True), streaming)
        runnable = runnable.with_fallbacks([backup], exceptions_to_handle=TRANSIENT_ERRORS)
    return runnable, primary_plan

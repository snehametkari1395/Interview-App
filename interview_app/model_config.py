"""Generation parameters and model-capability-aware request building.

Single source of truth for every tunable parameter: its OpenRouter field name, valid range
(from the OpenRouter parameters reference), the app's recommended value, and the provider's
conventional default. The UI, validation, and request builder all read ``PARAM_SPECS``.

Rules for what is sent:
- temperature and max_tokens are always sent when the model supports them.
- Other sampling parameters are sent only when the model lists them in
  ``supported_parameters`` AND the user moved them away from the provider default.
- When capabilities are known, ``provider.require_parameters`` is set so OpenRouter routes only
  to providers that honour every parameter sent. Without it, providers silently ignore unknown
  parameters (OpenRouter provider-routing docs).
- When capabilities are unknown, only temperature and max_tokens are sent.
"""

from dataclasses import dataclass, field, fields, replace

ALL_REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
REASONING_EFFORTS = ("low", "medium", "high")  # offered when a model does not publish its own list
STANDARD_PARAMS = frozenset({"temperature", "max_tokens"})
DEFAULT_TEMPERATURE = 0.4
DEFAULT_MAX_TOKENS = 2000
TEMPERATURE_RANGE = (0.0, 2.0)
MAX_TOKENS_RANGE = (64, 64000)


@dataclass(frozen=True)
class ParamSpec:
    key: str
    label: str
    kind: str  # "float" | "int"
    minimum: float
    maximum: float
    step: float
    recommended: float
    provider_default: float | None  # None: always sent when supported
    description: str


PARAM_SPECS: tuple[ParamSpec, ...] = (
    ParamSpec(
        "temperature", "Temperature", "float", 0.0, 2.0, 0.05, DEFAULT_TEMPERATURE, None,
        "Randomness of token choice. Low (0–0.3): focused and repeatable, best for scoring. Mid (0.4–0.8): natural "
        "variety. High (>1.0): more creative but less consistent, more errors and malformed JSON.",
    ),
    ParamSpec(
        "max_tokens", "Max output tokens", "int", MAX_TOKENS_RANGE[0], MAX_TOKENS_RANGE[1], 64, DEFAULT_MAX_TOKENS, None,
        "Hard ceiling on response length, not a target. Too low cuts structured output off mid-JSON. Reasoning "
        "models spend part of this budget on hidden reasoning tokens. Capped at the model's maximum automatically.",
    ),
    ParamSpec(
        "top_p", "Top P", "float", 0.0, 1.0, 0.01, 1.0, 1.0,
        "Nucleus sampling: only tokens within this cumulative probability are considered. Lower values make output "
        "more conservative. Adjust temperature or top P, rarely both.",
    ),
    ParamSpec(
        "top_k", "Top K", "int", 0, 200, 1, 0, 0,
        "Only the K most likely tokens are considered at each step. 0 disables it. Small values (e.g. 20–40) "
        "reduce rambling; 1 is greedy decoding.",
    ),
    ParamSpec(
        "frequency_penalty", "Frequency penalty", "float", -2.0, 2.0, 0.1, 0.0, 0.0,
        "Penalises tokens in proportion to how often they have already appeared. Positive values reduce verbatim "
        "repetition in long answers; negative values encourage it.",
    ),
    ParamSpec(
        "presence_penalty", "Presence penalty", "float", -2.0, 2.0, 0.1, 0.0, 0.0,
        "Penalises any token that has appeared at all, nudging the model toward new topics. Useful for more varied "
        "question sets; too high can drift off-topic.",
    ),
    ParamSpec(
        "repetition_penalty", "Repetition penalty", "float", 0.0, 2.0, 0.05, 1.0, 1.0,
        "Multiplicative penalty on repeated tokens (1.0 = off). Common on open-weight models. Values above ~1.2 can "
        "degrade fluency.",
    ),
    ParamSpec(
        "min_p", "Min P", "float", 0.0, 1.0, 0.01, 0.0, 0.0,
        "Drops tokens whose probability is below this fraction of the most likely token. A small value (0.05) "
        "trims unlikely tokens while keeping variety at higher temperatures.",
    ),
    ParamSpec(
        "top_a", "Top A", "float", 0.0, 1.0, 0.01, 0.0, 0.0,
        "Dynamic cutoff based on the top token's probability; higher values narrow choices when the model is "
        "confident. Supported by few models.",
    ),
)
SPEC_BY_KEY = {spec.key: spec for spec in PARAM_SPECS}
OPTIONAL_SPECS = tuple(spec for spec in PARAM_SPECS if spec.provider_default is not None)


@dataclass(frozen=True)
class GenerationParams:
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: int = DEFAULT_MAX_TOKENS
    reasoning_effort: str | None = None
    top_p: float = 1.0
    top_k: int = 0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    repetition_penalty: float = 1.0
    min_p: float = 0.0
    top_a: float = 0.0
    seed: int | None = None

    def validated(self) -> "GenerationParams":
        values = {}
        for spec in PARAM_SPECS:
            raw = getattr(self, spec.key)
            try:
                number = float(raw)
            except (TypeError, ValueError):
                number = float(spec.recommended)
            number = min(spec.maximum, max(spec.minimum, number))
            values[spec.key] = int(round(number)) if spec.kind == "int" else round(number, 3)
        effort = self.reasoning_effort if self.reasoning_effort in ALL_REASONING_EFFORTS else None
        seed = self.seed if isinstance(self.seed, int) and not isinstance(self.seed, bool) and 0 <= self.seed < 2**31 else None
        return GenerationParams(**values, reasoning_effort=effort, seed=seed)

    def with_min_tokens(self, minimum: int) -> "GenerationParams":
        return replace(self, max_tokens=max(self.max_tokens, minimum))

    def changed_optional(self) -> dict:
        """Optional sampling parameters the user moved away from the provider default."""
        return {spec.key: getattr(self, spec.key) for spec in OPTIONAL_SPECS if getattr(self, spec.key) != spec.provider_default}

    def label(self) -> str:
        parts = [f"temp {self.temperature:g}", f"{self.max_tokens:,} max tokens"]
        parts += [f"{SPEC_BY_KEY[key].label.lower()} {value:g}" for key, value in self.changed_optional().items()]
        if self.reasoning_effort:
            parts.append(f"{self.reasoning_effort} reasoning")
        if self.seed is not None:
            parts.append(f"seed {self.seed}")
        return " · ".join(parts)

    def as_dict(self) -> dict:
        return {item.name: getattr(self, item.name) for item in fields(self)}


def _to_price(value) -> float | None:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if price >= 0 else None


@dataclass(frozen=True)
class ModelCapabilities:
    model: str
    known: bool = False
    supported: frozenset[str] = field(default_factory=frozenset)
    max_completion_tokens: int | None = None
    context_length: int | None = None
    name: str = ""
    supported_efforts: tuple[str, ...] = ()
    pricing: dict = field(default_factory=dict)  # field -> USD per unit (float); missing when unknown
    input_modalities: tuple[str, ...] = ()
    output_modalities: tuple[str, ...] = ()

    def supports(self, parameter: str) -> bool:
        if self.known:
            return parameter in self.supported
        return parameter in STANDARD_PARAMS

    @property
    def supports_reasoning(self) -> bool:
        return self.known and "reasoning" in self.supported

    @property
    def supports_structured_outputs(self) -> bool:
        return self.known and "structured_outputs" in self.supported

    @property
    def effort_options(self) -> tuple[str, ...]:
        if not self.supports_reasoning:
            return ()
        published = tuple(effort for effort in self.supported_efforts if effort in ALL_REASONING_EFFORTS and effort != "none")
        return published or REASONING_EFFORTS

    @property
    def provider(self) -> str:
        return self.model.split("/", 1)[0] if "/" in self.model else ""


def capabilities_from_catalog_entry(model: str, entry: dict | None) -> ModelCapabilities:
    if not entry:
        return ModelCapabilities(model=model)
    supported = entry.get("supported_parameters") or []
    top = entry.get("top_provider") or {}
    max_completion = top.get("max_completion_tokens") if isinstance(top, dict) else None
    reasoning = entry.get("reasoning") if isinstance(entry.get("reasoning"), dict) else {}
    efforts = reasoning.get("supported_efforts") if isinstance(reasoning.get("supported_efforts"), list) else []
    architecture = entry.get("architecture") if isinstance(entry.get("architecture"), dict) else {}
    raw_pricing = entry.get("pricing") if isinstance(entry.get("pricing"), dict) else {}
    pricing = {key: price for key, value in raw_pricing.items() if (price := _to_price(value)) is not None}
    return ModelCapabilities(
        model=model,
        known=True,
        supported=frozenset(str(item) for item in supported if isinstance(item, str)),
        max_completion_tokens=max_completion if isinstance(max_completion, int) and max_completion > 0 else None,
        context_length=entry.get("context_length") if isinstance(entry.get("context_length"), int) else None,
        name=str(entry.get("name") or model),
        supported_efforts=tuple(str(item) for item in efforts if isinstance(item, str)),
        pricing=pricing,
        input_modalities=tuple(architecture.get("input_modalities") or ()),
        output_modalities=tuple(architecture.get("output_modalities") or ()),
    )


@dataclass(frozen=True)
class RequestPlan:
    body: dict
    applied: dict
    skipped: tuple[str, ...]
    output_mode: str  # "json_schema" | "json_object" | "prompt"


def build_request_body(
    model: str,
    messages: list[dict],
    params: GenerationParams,
    capabilities: ModelCapabilities,
    *,
    schema: dict | None = None,
    schema_name: str = "response",
    require_parameters: bool = True,
) -> RequestPlan:
    """Build the chat-completions body, including only parameters the model supports."""
    params = params.validated()
    body: dict = {"model": model, "messages": messages}
    applied: dict = {}
    skipped: list[str] = []

    if capabilities.supports("temperature"):
        body["temperature"] = applied["temperature"] = params.temperature
    else:
        skipped.append("temperature")

    if capabilities.supports("max_tokens"):
        max_tokens = params.max_tokens
        if capabilities.max_completion_tokens:
            max_tokens = min(max_tokens, capabilities.max_completion_tokens)
        body["max_tokens"] = applied["max_tokens"] = max_tokens
    else:
        skipped.append("max_tokens")

    for key, value in params.changed_optional().items():
        if capabilities.known and capabilities.supports(key):
            body[key] = applied[key] = value
        else:
            skipped.append(key)

    if params.seed is not None:
        if capabilities.known and capabilities.supports("seed"):
            body["seed"] = applied["seed"] = params.seed
        else:
            skipped.append("seed")

    if params.reasoning_effort:
        if params.reasoning_effort in capabilities.effort_options:
            # exclude=True keeps reasoning text out of the response; only the answer is returned.
            body["reasoning"] = {"effort": params.reasoning_effort, "exclude": True}
            applied["reasoning_effort"] = params.reasoning_effort
        else:
            skipped.append("reasoning_effort")

    if schema is not None and capabilities.supports_structured_outputs:
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": schema_name, "strict": True, "schema": schema}}
        output_mode = "json_schema"
    elif capabilities.known and capabilities.supports("response_format"):
        body["response_format"] = {"type": "json_object"}
        output_mode = "json_object"
    else:
        output_mode = "prompt"
    applied["output_mode"] = output_mode

    if capabilities.known and require_parameters:
        body["provider"] = {"require_parameters": True}

    return RequestPlan(body=body, applied=applied, skipped=tuple(skipped), output_mode=output_mode)


PARAMETER_GUIDE = {spec.label: spec.description for spec in PARAM_SPECS[:2]} | {
    "Reasoning effort": (
        "Only for models that support it; the options come from the model's own published list. Higher effort lets "
        "the model think longer before answering, which usually improves accuracy on hard, multi-step questions at "
        "the cost of latency and tokens (reasoning tokens are billed as output). Little effect on easy questions."
    ),
}

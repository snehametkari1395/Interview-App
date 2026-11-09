"""Reusable LangChain building blocks: structured chains and a sanitised streaming reply.

A structured chain is an LCEL pipeline:

    guard (RunnableLambda) -> ChatPromptTemplate -> ChatOpenRouter (+fallbacks) -> validate (RunnableLambda)

- guard: sanitises and length-checks the untrusted fields, blocks score manipulation, and attaches
  deterministic ``input_flags`` (the same rules as the rest of the app).
- prompt: the system prompt is supplied as a template *variable*, so braces in JSON examples are
  never interpreted as template fields, and untrusted text is only ever serialised JSON data.
- validate: rejects canary echoes, parses JSON, validates against the full JSON Schema
  (stricter than what strict mode enforces), and sanitises every string before it reaches the UI.
"""

import json
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Iterator

from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda

from interview_app.chains.llm import ModelSpec, build_llm
from interview_app.pricing import CostBreakdown, actual_cost
from interview_app.schemas import sanitize_tree, trim_to_schema, validate_against
from interview_app.security_guard import (
    PROMPT_CANARY,
    GuardError,
    assess_input,
    check_for_prompt_leak,
    clean_model_text,
    parse_json_object,
    validate_text,
)

PROMPT = ChatPromptTemplate.from_messages([("system", "{system}"), ("human", "{payload}")])


@dataclass
class ChainOutput:
    data: dict
    model: str
    feature: str
    latency_s: float = 0.0
    usage: dict = field(default_factory=dict)
    cost: CostBreakdown | None = None
    output_mode: str = "prompt"
    input_flags: tuple[str, ...] = ()
    repairs: tuple[str, ...] = ()

    def usage_record(self) -> dict:
        return {
            "feature": self.feature,
            "model": self.model,
            "input_tokens": self.usage.get("prompt_tokens"),
            "output_tokens": self.usage.get("completion_tokens"),
            "cost_usd": self.cost.best_total if self.cost else None,
            "latency_s": round(self.latency_s, 2),
        }


def usage_from_message(message: AIMessage) -> dict:
    """Map LangChain usage metadata and OpenRouter's billed cost to the app's usage dict."""
    metadata = message.usage_metadata or {}
    usage: dict = {}
    if metadata:
        usage["prompt_tokens"] = metadata.get("input_tokens", 0)
        usage["completion_tokens"] = metadata.get("output_tokens", 0)
        usage["total_tokens"] = metadata.get("total_tokens", 0)
        cached = (metadata.get("input_token_details") or {}).get("cache_read")
        reasoning = (metadata.get("output_token_details") or {}).get("reasoning")
        if cached:
            usage["cached_tokens"] = cached
        if reasoning:
            usage["reasoning_tokens"] = reasoning
    cost = (message.response_metadata or {}).get("cost")
    if isinstance(cost, (int, float)) and not isinstance(cost, bool):
        usage["cost"] = float(cost)
    return usage


def guard_payload(payload: dict, guard_fields: dict[str, int]) -> tuple[dict, tuple[str, ...]]:
    """Validate untrusted fields; returns the cleaned payload and any injection flags."""
    clean = dict(payload)
    flags: list[str] = []
    for name, limit in guard_fields.items():
        value = clean.get(name)
        if value in (None, ""):
            continue
        if not isinstance(value, str):
            raise GuardError(f"{name.replace('_', ' ').capitalize()} must be text.")
        assessment = assess_input(value)
        if assessment.blocked:
            raise GuardError(assessment.message)
        clean[name] = validate_text(value, name.replace("_", " "), limit)
        flags.extend(flag for flag in assessment.flags if flag not in flags)
    if flags:
        clean["input_flags"] = flags
    return clean, tuple(flags)


class StructuredChain:
    """A LangChain LCEL chain that returns schema-validated, sanitised JSON."""

    def __init__(
        self,
        *,
        system_prompt: str,
        schema: dict,
        schema_name: str,
        spec: ModelSpec,
        feature: str,
        guard_fields: dict[str, int] | None = None,
        semantic_check: Callable[[dict], list[str]] | None = None,
    ):
        self.schema = schema
        self.spec = spec
        self.feature = feature
        self.guard_fields = guard_fields or {}
        self.semantic_check = semantic_check
        llm, plan = build_llm(spec, schema=schema, schema_name=schema_name)
        self.output_mode = plan.output_mode
        self.runnable: Runnable = (
            RunnableLambda(self._prepare, name=f"{feature} guard")
            | PROMPT.partial(system=system_prompt)
            | llm
            | RunnableLambda(self._validate, name=f"{feature} validate")
        )

    def _prepare(self, payload: dict) -> dict:
        clean, flags = guard_payload(payload, self.guard_fields)
        self._flags = flags
        return {"payload": json.dumps(clean, ensure_ascii=True)}

    def _validate(self, message: AIMessage) -> ChainOutput:
        content = message.content if isinstance(message.content, str) else ""
        finish = (message.response_metadata or {}).get("finish_reason")
        if not content.strip():
            if finish == "length":
                raise GuardError("The model used its whole output budget before answering. Increase max output tokens or lower reasoning effort.")
            raise GuardError("The model returned an empty response. Please try again.")
        try:
            data, repairs = trim_to_schema(parse_json_object(content), self.schema)
            validate_against(data, self.schema, "response")
            problems = self.semantic_check(data) if self.semantic_check else []
            if problems:
                from interview_app.schemas import SchemaValidationError

                raise SchemaValidationError(f"The AI's response broke {len(problems)} content rule(s). Please try again.", problems)
        except GuardError as error:
            error.raw_text = content[:6000]
            if finish == "length":
                truncated = GuardError("The response was cut off before it finished. Increase max output tokens and try again.")
                truncated.raw_text = content[:6000]
                raise truncated from None
            raise
        usage = usage_from_message(message)
        served = (message.response_metadata or {}).get("model_name") or self.spec.model
        caps = self.spec.capabilities if served.startswith(self.spec.model) or not self.spec.fallback else self.spec.fallback.capabilities
        return ChainOutput(
            data=sanitize_tree(data),
            model=served,
            feature=self.feature,
            usage=usage,
            cost=actual_cost(served, caps.pricing, usage),
            output_mode=self.output_mode,
            input_flags=getattr(self, "_flags", ()),
            repairs=tuple(repairs),
        )

    def invoke(self, payload: dict) -> ChainOutput:
        started = time.perf_counter()
        output = self.runnable.invoke(payload)
        output.latency_s = time.perf_counter() - started
        return output


# ---------------------------------------------------------------------------
# Streaming reply with incremental output sanitisation
# ---------------------------------------------------------------------------

_SAFE_TAIL = len(PROMPT_CANARY)
_OPENERS = re.compile(r"!?\[|<")
_MAX_HELD = 400


def _construct_end(tail: str) -> int | None:
    """Length of the Markdown/HTML construct at the start of ``tail``, or None if still incomplete."""
    if tail.startswith("<"):
        close = tail.find(">")
        return close + 1 if close != -1 else None
    bracket = tail.find("]")
    if bracket == -1:
        return None
    if bracket + 1 >= len(tail):
        return None  # cannot tell yet whether "(" follows
    if tail[bracket + 1] != "(":
        return bracket + 1  # plain bracketed text, not a link
    close = tail.find(")", bracket)
    return close + 1 if close != -1 else None


class SafeStream:
    """Sanitise streamed Markdown before it reaches the browser.

    Plain text is emitted as it arrives, except the last few characters, which are held so a canary
    token split across chunks is detected before any of it is shown. Anything that could become a
    Markdown image, link, or HTML tag is held until complete, then passed through
    ``clean_model_text`` (images and HTML removed, link targets dropped).
    """

    def __init__(self):
        self.buffer = ""
        self.text = ""

    def feed(self, chunk: str) -> str:
        self.buffer += chunk
        check_for_prompt_leak(self.text + self.buffer)
        out = []
        while True:
            match = _OPENERS.search(self.buffer)
            if not match:
                cut = max(0, len(self.buffer) - _SAFE_TAIL)
                out.append(self.buffer[:cut])
                self.buffer = self.buffer[cut:]
                break
            out.append(self.buffer[: match.start()])
            tail = self.buffer[match.start():]
            end = _construct_end(tail)
            if end is None and len(tail) <= _MAX_HELD:
                self.buffer = tail
                break
            end = end or len(tail)
            out.append(clean_model_text(tail[:end]))
            self.buffer = tail[end:]
        emitted = "".join(out)
        self.text += emitted
        return emitted

    def flush(self) -> str:
        check_for_prompt_leak(self.text + self.buffer)
        rest = clean_model_text(self.buffer) if any(mark in self.buffer for mark in "[<") else self.buffer
        self.buffer = ""
        self.text += rest
        return rest


class ReplyStream:
    """Iterate to stream a sanitised text reply; usage and cost are available afterwards."""

    def __init__(self, spec: ModelSpec, system_prompt: str, payload: dict, feature: str):
        llm, _plan = build_llm(spec, streaming=True)
        self.spec = spec
        self.feature = feature
        self.chain = PROMPT.partial(system=system_prompt) | llm
        self.payload = json.dumps(payload, ensure_ascii=True)
        self.output: ChainOutput | None = None
        self.text = ""

    def __iter__(self) -> Iterator[str]:
        started = time.perf_counter()
        sanitizer = SafeStream()
        merged: AIMessageChunk | None = None
        for chunk in self.chain.stream({"payload": self.payload}):
            merged = chunk if merged is None else merged + chunk
            piece = chunk.content if isinstance(chunk.content, str) else ""
            safe = sanitizer.feed(piece) if piece else ""
            if safe:
                yield safe
        rest = sanitizer.flush()
        if rest:
            yield rest
        self.text = sanitizer.text.strip()
        usage = usage_from_message(merged) if merged is not None else {}
        served = ((merged.response_metadata or {}).get("model_name") if merged is not None else None) or self.spec.model
        self.output = ChainOutput(
            data={"text": self.text},
            model=served,
            feature=self.feature,
            latency_s=time.perf_counter() - started,
            usage=usage,
            cost=actual_cost(served, self.spec.capabilities.pricing, usage),
            output_mode="text",
        )

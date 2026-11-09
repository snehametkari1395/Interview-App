"""Prompt cost estimation (before a call) and actual cost (after a call).

Prices come from the live OpenRouter models endpoint (``pricing`` values are USD per token,
published as decimal strings). Nothing is hardcoded.

- Estimated cost: input tokens are approximated from character count, because providers use
  different tokenizers and no single local tokenizer is correct for every model. Output tokens
  are shown two ways: a typical size for the task, and the worst case (max_tokens).
- Actual cost: computed from the token usage the API returns. OpenRouter also returns its own
  billed ``usage.cost``; when present it is shown as authoritative, since providers can apply
  caching discounts, request fees, or reasoning-token pricing differently.
"""

import json
import math
from dataclasses import dataclass

CHARS_PER_TOKEN = 4.0  # common English-text heuristic; varies by tokenizer and language
MESSAGE_OVERHEAD_TOKENS = 4  # per message, for role markers and separators

TYPICAL_OUTPUT_TOKENS = {
    "review": 750,
    "questions": 90,  # per question
    "qa_item": 550,  # per structured Q&A item
    "evaluation": 650,
    "jd_analysis": 900,
    "guide": 2200,
    "critique": 3000,
    "model_answer": 450,
    "judge": 120,  # per rated response
    "screen": 80,
}


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN) if text else 0


def estimate_input_tokens(system_prompt: str, user_payload: dict) -> int:
    user_text = json.dumps(user_payload, ensure_ascii=True)
    return estimate_tokens(system_prompt) + estimate_tokens(user_text) + 2 * MESSAGE_OVERHEAD_TOKENS


def format_usd(amount: float | None) -> str:
    if amount is None:
        return "Unavailable"
    if amount == 0:
        return "$0.00"
    if amount < 0.01:
        return f"${amount:.6f}"
    return f"${amount:,.4f}"


def price_per_million(pricing: dict, key: str) -> str:
    value = pricing.get(key)
    return "Unavailable" if value is None else f"${value * 1_000_000:,.2f} / 1M"


@dataclass(frozen=True)
class CostBreakdown:
    model: str
    is_estimate: bool
    input_tokens: int
    output_tokens: int
    input_cost: float | None
    output_cost: float | None
    request_cost: float = 0.0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    reported_cost: float | None = None  # OpenRouter's billed amount (actual only)
    note: str = ""

    @property
    def total(self) -> float | None:
        if self.input_cost is None or self.output_cost is None:
            return None
        return self.input_cost + self.output_cost + self.request_cost

    @property
    def best_total(self) -> float | None:
        return self.reported_cost if self.reported_cost is not None else self.total

    def as_dict(self) -> dict:
        return {
            "model": self.model,
            "type": "estimate" if self.is_estimate else "actual",
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cached_input_tokens": self.cached_tokens,
            "input_cost_usd": self.input_cost,
            "output_cost_usd": self.output_cost,
            "request_fee_usd": self.request_cost,
            "computed_total_usd": self.total,
            "openrouter_billed_usd": self.reported_cost,
            "note": self.note,
        }


def _cost(tokens: int, price: float | None) -> float | None:
    return None if price is None else tokens * price


def estimate_cost(model: str, pricing: dict, input_tokens: int, output_tokens: int) -> CostBreakdown:
    note = "" if pricing.get("prompt") is not None else "Pricing for this model is not published, so cost cannot be calculated."
    return CostBreakdown(
        model=model,
        is_estimate=True,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        input_cost=_cost(input_tokens, pricing.get("prompt")),
        output_cost=_cost(output_tokens, pricing.get("completion")),
        request_cost=pricing.get("request") or 0.0,
        note=note,
    )


def actual_cost(model: str, pricing: dict, usage: dict) -> CostBreakdown:
    """Cost from returned usage. Cached input tokens use the cache-read price when published."""
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    cached = min(int(usage.get("cached_tokens") or 0), prompt_tokens)
    reasoning = int(usage.get("reasoning_tokens") or 0)
    prompt_price, cache_price = pricing.get("prompt"), pricing.get("input_cache_read")
    if prompt_price is None:
        input_cost = None
    elif cached and cache_price is not None:
        input_cost = (prompt_tokens - cached) * prompt_price + cached * cache_price
    else:
        input_cost = prompt_tokens * prompt_price
    reported = usage.get("cost")
    reported = float(reported) if isinstance(reported, (int, float)) and not isinstance(reported, bool) else None
    notes = []
    if not usage:
        notes.append("The API did not return token usage.")
    if reasoning:
        notes.append(f"Output includes {reasoning:,} reasoning tokens, billed as output.")
    if prompt_price is None:
        notes.append("Pricing metadata unavailable; showing OpenRouter's billed amount only.")
    return CostBreakdown(
        model=model,
        is_estimate=False,
        input_tokens=prompt_tokens,
        output_tokens=completion_tokens,
        input_cost=input_cost,
        output_cost=_cost(completion_tokens, pricing.get("completion")),
        request_cost=pricing.get("request") or 0.0,
        reasoning_tokens=reasoning,
        cached_tokens=cached,
        reported_cost=reported,
        note=" ".join(notes),
    )


def extract_usage(raw_usage) -> dict:
    """Flatten the OpenRouter usage object into plain numbers (unknown fields dropped)."""
    if not isinstance(raw_usage, dict):
        return {}

    def number(value):
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    usage = {key: number(raw_usage.get(key)) for key in ("prompt_tokens", "completion_tokens", "total_tokens", "cost")}
    prompt_details = raw_usage.get("prompt_tokens_details") if isinstance(raw_usage.get("prompt_tokens_details"), dict) else {}
    completion_details = raw_usage.get("completion_tokens_details") if isinstance(raw_usage.get("completion_tokens_details"), dict) else {}
    usage["cached_tokens"] = number(prompt_details.get("cached_tokens"))
    usage["reasoning_tokens"] = number(completion_details.get("reasoning_tokens"))
    return {key: value for key, value in usage.items() if value is not None}

"""Run the same task under different parameter configurations and compare the results.

Metrics are split deliberately:
- Deterministic (computed in code, always available): response length, latency, token use,
  lexical diversity, and run-to-run consistency (text similarity and score spread).
- LLM-judged (optional): quality, relevance, creativity, and accuracy. A judge model sees all
  outputs under anonymous labels in shuffled order to reduce position and identity bias.
"""

import random
import re
import statistics
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from itertools import combinations

from interview_app.catalog import PrepProfile
from interview_app.coaching import normalize_review
from interview_app.model_config import GenerationParams, ModelCapabilities
from interview_app.openrouter import call_model, describe_error
from interview_app.prompts import judge_prompt, model_answer_prompt, review_prompt
from interview_app.security_guard import int_field, list_field, text_field

TASKS = ("Model answer", "Answer review")
MAX_CONFIGS = 3
MAX_RUNS = 3


@dataclass(frozen=True)
class RunConfig:
    label: str
    model: str
    params: GenerationParams


@dataclass
class RunOutcome:
    label: str
    run: int
    ok: bool
    text: str = ""
    score: int | None = None
    key_points: list[str] = field(default_factory=list)
    latency_s: float = 0.0
    completion_tokens: int | None = None
    finish_reason: str | None = None
    skipped_params: tuple[str, ...] = ()
    error: str = ""


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def lexical_diversity(text: str) -> float:
    """Type-token ratio over the first 200 words (a rough proxy for varied wording)."""
    words = _words(text)[:200]
    return round(len(set(words)) / len(words), 3) if words else 0.0


def consistency(texts: list[str]) -> float | None:
    """Mean pairwise word-sequence similarity across runs (1.0 = identical). None for one run."""
    texts = [text for text in texts if text]
    if len(texts) < 2:
        return None
    ratios = [SequenceMatcher(None, _words(a), _words(b)).ratio() for a, b in combinations(texts, 2)]
    return round(statistics.mean(ratios), 3)


def _execute(task: str, profile: PrepProfile, question: str, answer: str, config: RunConfig, run: int, api_key: str, caps: ModelCapabilities) -> RunOutcome:
    if task == "Answer review":
        prompt = review_prompt(profile)
        payload = {"mode": "Guided coaching", "interview_question": question, "candidate_answer": answer}
    else:
        prompt = model_answer_prompt(profile)
        payload = {"interview_question": question}
    try:
        result = call_model(prompt, payload, params=config.params, model=config.model, api_key=api_key, capabilities=caps)
    except Exception as error:  # one failed run must not sink the comparison
        return RunOutcome(label=config.label, run=run, ok=False, error=describe_error(error))

    if task == "Answer review":
        review = normalize_review(result.data)
        text = "\n".join(filter(None, [review["verdict"], *review["improvements"], review["sample_answer"]]))
        score, points = review["score"], review["strengths"]
    else:
        text = text_field(result.data, "answer", 6000)
        score, points = None, list_field(result.data, "key_points", limit=5)
    return RunOutcome(
        label=config.label,
        run=run,
        ok=bool(text),
        text=text,
        score=score,
        key_points=points,
        latency_s=round(result.latency_s, 2),
        completion_tokens=result.usage.get("completion_tokens"),
        finish_reason=result.finish_reason,
        skipped_params=result.skipped_params,
        error="" if text else "The model returned an empty answer.",
    )


def run_comparison(
    task: str,
    profile: PrepProfile,
    question: str,
    answer: str,
    configs: list[RunConfig],
    runs: int,
    api_key: str,
    capabilities: dict[str, ModelCapabilities],
) -> list[RunOutcome]:
    jobs = [(config, run) for config in configs[:MAX_CONFIGS] for run in range(1, min(runs, MAX_RUNS) + 1)]
    with ThreadPoolExecutor(max_workers=min(4, len(jobs))) as pool:
        futures = [
            pool.submit(_execute, task, profile, question, answer, config, run, api_key, capabilities[config.model])
            for config, run in jobs
        ]
        return [future.result() for future in futures]


def summarize(configs: list[RunConfig], outcomes: list[RunOutcome]) -> list[dict]:
    rows = []
    for config in configs:
        ok = [o for o in outcomes if o.label == config.label and o.ok]
        failed = sum(1 for o in outcomes if o.label == config.label and not o.ok)
        scores = [o.score for o in ok if o.score is not None]
        tokens = [o.completion_tokens for o in ok if o.completion_tokens]
        rows.append({
            "Config": config.label,
            "Model": config.model,
            "Settings": config.params.label(),
            "Successful runs": len(ok),
            "Failed runs": failed,
            "Avg words": round(statistics.mean(len(_words(o.text)) for o in ok)) if ok else None,
            "Avg output tokens": round(statistics.mean(tokens)) if tokens else None,
            "Avg latency (s)": round(statistics.mean(o.latency_s for o in ok), 2) if ok else None,
            "Lexical diversity": round(statistics.mean(lexical_diversity(o.text) for o in ok), 3) if ok else None,
            "Consistency": consistency([o.text for o in ok]),
            "Avg score": round(statistics.mean(scores), 2) if scores else None,
            "Score spread": (max(scores) - min(scores)) if len(scores) > 1 else None,
        })
    return rows


JUDGE_DIMENSIONS = ("quality", "relevance", "creativity", "accuracy")


def judge_outputs(
    profile: PrepProfile,
    question: str,
    outcomes: list[RunOutcome],
    *,
    api_key: str,
    model: str,
    capabilities: ModelCapabilities,
    seed: int | None = None,
) -> list[dict]:
    """Ask a judge model to rate each successful output. Returns one row per output."""
    candidates = [o for o in outcomes if o.ok]
    if not candidates:
        return []
    order = list(range(len(candidates)))
    random.Random(seed).shuffle(order)
    anonymous = {f"Response {position + 1}": candidates[index] for position, index in enumerate(order)}
    payload = {
        "interview_context": profile.label() + f" · {profile.domain}",
        "interview_question": question,
        "responses": [{"label": label, "text": outcome.text[:4000]} for label, outcome in anonymous.items()],
    }
    params = GenerationParams(temperature=0.0, max_tokens=max(1500, 220 * len(candidates)))
    result = call_model(judge_prompt(), payload, params=params, model=model, api_key=api_key, capabilities=capabilities)
    rows = []
    for item in result.data.get("ratings", []) if isinstance(result.data.get("ratings"), list) else []:
        if not isinstance(item, dict):
            continue
        outcome = anonymous.get(text_field(item, "label", 40))
        if outcome is None:
            continue
        row = {"Config": outcome.label, "Run": outcome.run}
        for dimension in JUDGE_DIMENSIONS:
            row[dimension.capitalize()] = int_field(item, dimension, 1, 5, 3)
        row["Judge note"] = text_field(item, "note", 300)
        rows.append(row)
    return rows

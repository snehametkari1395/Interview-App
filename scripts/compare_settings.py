"""Compare model settings on one interview task and write docs/MODEL_SETTINGS.md.

Experiment 1: reasoning effort (low / medium / high), several runs each, on the same answer review.
Experiment 2: max output tokens (300 / 800 / 2000), to show what happens when the budget is too small.

Temperature is not compared: the approved models are reasoning models and do not accept it
(the app never sends it to them).

Usage:  uv run python scripts/compare_settings.py [--runs 3]
"""

import argparse
import logging
import statistics
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
logging.disable(logging.WARNING)

from interview_app.catalog import PrepProfile  # noqa: E402
from interview_app.coaching import normalize_review  # noqa: E402
from interview_app.comparison import RunOutcome, consistency, judge_outputs  # noqa: E402
from interview_app.model_config import GenerationParams  # noqa: E402
from interview_app.openrouter import call_model, describe_error, get_api_key, get_capabilities, get_model  # noqa: E402
from interview_app.pricing import format_usd  # noqa: E402
from interview_app.prompts import review_prompt  # noqa: E402

OUTPUT = ROOT / "docs" / "MODEL_SETTINGS.md"
PROFILE = PrepProfile("IT / Software Engineering", "Backend Developer", "Medium", "Balanced", "Neutral")
QUESTION = "How would you design a rate limiter for a public REST API?"
# A partially correct answer: right idea, but no algorithm details, storage, or distributed concerns.
ANSWER = (
    "I would count how many requests each user makes and block them when they go over a limit, "
    "for example 100 requests per minute. I would return an error so the client knows to slow down. "
    "The limit could be stored somewhere like a database."
)
EFFORTS = ("low", "medium", "high")
TOKEN_BUDGETS = (300, 800, 2000)


def run_once(params: GenerationParams, model: str, api_key: str, caps) -> dict:
    payload = {"mode": "Guided coaching", "interview_question": QUESTION, "candidate_answer": ANSWER}
    try:
        result = call_model(review_prompt(PROFILE), payload, params=params, model=model, api_key=api_key, capabilities=caps)
    except Exception as error:
        return {"ok": False, "error": describe_error(error)}
    review = normalize_review(result.data)
    text = "\n".join(filter(None, [review["verdict"], *review["improvements"], review["sample_answer"]]))
    return {
        "ok": True,
        "score": review["score"],
        "text": text,
        "words": len(text.split()),
        "latency": result.latency_s,
        "output_tokens": int(result.usage.get("completion_tokens") or 0),
        "reasoning_tokens": int(result.usage.get("reasoning_tokens") or 0),
        "cost": result.cost.best_total if result.cost else None,
        "finish": result.finish_reason,
    }


def mean(values, digits=1):
    values = [v for v in values if v is not None]
    if not values:
        return None
    value = round(statistics.mean(values), digits)
    return int(value) if digits == 0 else value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    api_key, model = get_api_key(), get_model()
    if not api_key:
        sys.exit("Set OPENROUTER_API_KEY first.")
    caps = get_capabilities(model)
    base = GenerationParams(max_tokens=4000)  # generous budget so high effort is not cut off

    # Experiment 1: reasoning effort ------------------------------------------------------
    # Interleaved (low, medium, high, low, ...) so a slow moment at the provider does not hit one setting only.
    effort_runs: dict[str, list[dict]] = {effort: [] for effort in EFFORTS}
    for run in range(1, args.runs + 1):
        for effort in EFFORTS:
            outcome = run_once(replace(base, reasoning_effort=effort), model, api_key, caps)
            effort_runs[effort].append(outcome)
            status = f"score {outcome['score']}, {outcome['latency']:.1f}s" if outcome["ok"] else outcome["error"]
            print(f"effort={effort} run {run}: {status}")

    outcomes = [
        RunOutcome(label=effort, run=index + 1, ok=True, text=item["text"], score=item["score"])
        for effort, items in effort_runs.items() for index, item in enumerate(items) if item["ok"]
    ]
    try:
        judged = judge_outputs(PROFILE, QUESTION, outcomes, api_key=api_key, model=model, capabilities=caps, seed=7)
    except Exception as error:
        print(f"judge failed: {describe_error(error)}")
        judged = []

    # Experiment 2: max output tokens -----------------------------------------------------
    budget_runs = {}
    for budget in TOKEN_BUDGETS:
        budget_runs[budget] = run_once(replace(base, max_tokens=budget, reasoning_effort="low"), model, api_key, caps)
        outcome = budget_runs[budget]
        print(f"max_tokens={budget}: {'ok, ' + str(outcome['output_tokens']) + ' tokens' if outcome['ok'] else outcome['error']}")

    # Report -------------------------------------------------------------------------------
    lines = [
        "# Model settings: comparison",
        "",
        f"Run {datetime.now(timezone.utc).isoformat(timespec='seconds')} · model `{model}` · "
        f"script `scripts/compare_settings.py`",
        "",
        "Task: review the same partially correct answer (expected score about 2–3 out of 5).",
        "",
        f"- Question: *{QUESTION}*",
        f"- Answer: *{ANSWER}*",
        "",
        "**Why not temperature?** The approved models are reasoning models and do not accept `temperature`; "
        "the app checks each model's supported parameters and never sends it. The settings this model does "
        "accept are reasoning effort and max output tokens, so those are compared here.",
        "",
        f"## Experiment 1: reasoning effort ({args.runs} runs each, max tokens 4000)",
        "",
        "| Effort | Successful runs | Scores | Avg latency (s) | Avg output tokens | of which reasoning | Avg words shown | Consistency | Avg cost per call | Judge quality (1–5) | Judge accuracy (1–5) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    summary = {}
    for effort, items in effort_runs.items():
        ok = [item for item in items if item["ok"]]
        judge_rows = [row for row in judged if row["Config"] == effort]
        summary[effort] = {
            "latency": mean([i["latency"] for i in ok]),
            "tokens": mean([i["output_tokens"] for i in ok], 0),
            "cost": mean([i["cost"] for i in ok], 8),
            "quality": mean([r["Quality"] for r in judge_rows]),
            "scores": [i["score"] for i in ok],
        }
        lines.append(
            f"| **{effort}** | {len(ok)}/{len(items)} | {', '.join(str(i['score']) for i in ok) or '–'} | "
            f"{summary[effort]['latency']} | {summary[effort]['tokens']} | {mean([i['reasoning_tokens'] for i in ok], 0)} | "
            f"{mean([i['words'] for i in ok], 0)} | {consistency([i['text'] for i in ok])} | "
            f"{format_usd(summary[effort]['cost'])} | {summary[effort]['quality'] or '–'} | "
            f"{mean([r['Accuracy'] for r in judge_rows]) or '–'} |"
        )
    lines += [
        "",
        "*Consistency* is word-sequence similarity between runs (1.0 = identical text). *Judge* scores come from "
        "the same model rating all outputs anonymously in shuffled order (LLM-as-a-judge, so treat them as a rough signal).",
        "",
        "## Experiment 2: max output tokens (reasoning effort low)",
        "",
        "| Max tokens | Result | Output tokens used | Finish reason |",
        "| --- | --- | --- | --- |",
    ]
    for budget, outcome in budget_runs.items():
        if outcome["ok"]:
            lines.append(f"| {budget} | Complete review, score {outcome['score']} | {outcome['output_tokens']} | {outcome['finish'] or '–'} |")
        else:
            lines.append(f"| {budget} | **Failed:** {outcome['error']} | – | – |")

    measured = {effort: s for effort, s in summary.items() if s["latency"] is not None}
    lines += ["", "## Findings (computed from the table above)", ""]
    if measured:
        def pick(key, best=min):
            effort = best(measured, key=lambda e: measured[e][key] if measured[e][key] is not None else float("inf"))
            return effort, measured[effort][key]

        fastest, slowest = pick("latency"), pick("latency", max)
        fewest, most = pick("tokens"), pick("tokens", max)
        cheapest, dearest = pick("cost"), pick("cost", max)
        lines += [
            f"- Output tokens: **{fewest[0]}** used the fewest ({fewest[1]}), **{most[0]}** the most ({most[1]}). "
            "Higher effort spends more tokens on hidden reasoning.",
            f"- Cost: **{cheapest[0]}** was cheapest ({format_usd(cheapest[1])} per call), **{dearest[0]}** the most "
            f"expensive ({format_usd(dearest[1])}). Cost follows output tokens.",
            f"- Latency: **{fastest[0]}** was fastest ({fastest[1]}s), **{slowest[0]}** slowest ({slowest[1]}s). Latency is measured "
            "end to end, so it also depends on provider load and routing, not only on reasoning effort.",
            "- Scores per effort: " + "; ".join(f"{e}: {', '.join(map(str, s['scores']))}" for e, s in measured.items()) + ".",
        ]
    budget_ok = [budget for budget, outcome in budget_runs.items() if outcome["ok"]]
    budget_cut = [budget for budget, outcome in budget_runs.items() if not outcome["ok"]]
    if budget_cut:
        lines.append(
            f"- Max tokens {', '.join(map(str, budget_cut))} cut the review off before the JSON was complete"
            + (f"; {', '.join(map(str, budget_ok))} was enough." if budget_ok else ".")
            + " The app detects the cut-off and asks for a larger budget instead of showing broken output."
        )
    lines += [
        "- Caveat: one question and a few runs per setting is a small sample.",
        "",
    ]
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

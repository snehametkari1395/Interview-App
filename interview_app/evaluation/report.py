"""Aggregate evaluation results into summaries, comparisons, recommendations, and a Markdown report."""

import statistics
from collections import Counter

from interview_app.evaluation.judge import DIMENSION_KEYS, DIMENSION_LABELS

DETERMINISTIC_KEYS = (
    ("topic_coverage", "Topic coverage"),
    ("required_fields_ok", "Required fields"),
    ("difficulty_ok", "Difficulty label"),
    ("follow_up_distinct", "Distinct follow-ups"),
    ("readability_ok", "Readable length"),
    ("repetition_score", "Repetition score (1-5)"),
)
MIN_MEANINGFUL_DELTA = 0.3

ADVICE = {
    "jd_relevance": "Pass richer job context to chain B and require each question to name the skill it targets.",
    "technical_accuracy": "Ask for checkable expected-answer points and add a verification step, or use a stronger model for answers.",
    "question_quality": "Add examples of discriminating, open-ended questions and forbid yes/no or leading questions.",
    "difficulty_alignment": "Strengthen the difficulty definitions with example question shapes and a self-check step.",
    "answer_completeness": "Require a minimum number of expected-answer points covering definition, approach, and trade-offs.",
    "clarity": "Cap question length and require one question per item.",
    "repetition": "Lower the duplicate threshold or send more stored questions as 'avoid'.",
    "follow_up_quality": "Require follow-ups that probe why / what-if / measurement for the same question.",
    "domain_alignment": "Add domain vocabulary and realistic scenarios to the domain guidance in the catalog.",
}


def _mean(values) -> float | None:
    values = [value for value in values if value is not None]
    return round(statistics.mean(values), 2) if values else None


def summarize(results: dict) -> list[dict]:
    rows = []
    for config in results["meta"]["configs"]:
        records = [r for r in results["records"] if r["config"] == config["label"]]
        ok = [r for r in records if r["ok"]]
        judged = [r for r in ok if r.get("judge")]
        dims = {key: _mean(r["judge"][key]["score"] for r in judged) for key in DIMENSION_KEYS}
        scored = {key: value for key, value in dims.items() if value is not None}
        row = {
            "config": config["label"], "model": config["model"], "prompt_version": config["prompt_version"],
            "licence": records[0]["licence"] if records else "",
            "cases": len(records), "success_rate": round(len(ok) / len(records), 2) if records else 0.0,
            "judged_cases": len(judged),
            "overall": _mean(r["judge_overall"] for r in judged),
            "dimensions": dims,
            "strongest": max(scored, key=scored.get) if scored else None,
            "weakest": min(scored, key=scored.get) if scored else None,
            "deterministic": {key: _mean(r["deterministic"][key] for r in ok) for key, _ in DETERMINISTIC_KEYS},
            "latency_s": _mean(r.get("latency_s") for r in ok),
            "tokens_out": _mean(r.get("tokens_out") for r in ok),
            "cost_per_case": _mean(r.get("cost_usd") for r in ok),
            "judge_disagreement": _mean(r.get("judge_disagreement") for r in judged),
            "errors": [r["error"] for r in records if not r["ok"]],
        }
        rows.append(row)
    return rows


def _delta_rows(a: dict, b: dict, noise: float) -> list[dict]:
    rows = []
    for key in DIMENSION_KEYS:
        x, y = a["dimensions"].get(key), b["dimensions"].get(key)
        if x is None or y is None:
            continue
        delta = round(y - x, 2)
        rows.append({"dimension": DIMENSION_LABELS[key], a["config"]: x, b["config"]: y, "delta": delta, "meaningful": abs(delta) > noise})
    return rows


def noise_level(summary: list[dict]) -> float:
    disagreement = _mean(row["judge_disagreement"] for row in summary) or 0.0
    return round(max(MIN_MEANINGFUL_DELTA, 2 * disagreement), 2)


def prompt_comparison(summary: list[dict]) -> dict | None:
    by_model: dict[str, dict[str, dict]] = {}
    for row in summary:
        by_model.setdefault(row["model"], {})[row["prompt_version"]] = row
    for model, versions in by_model.items():
        if "v1-original" in versions and "v2-improved" in versions:
            return {"model": model, "rows": _delta_rows(versions["v1-original"], versions["v2-improved"], noise_level(summary)),
                    "v1": versions["v1-original"], "v2": versions["v2-improved"]}
    return None


def model_comparison(summary: list[dict]) -> list[dict]:
    return sorted([row for row in summary if row["prompt_version"] == "v2-improved"], key=lambda row: row["overall"] or 0, reverse=True)


def recommendations(results: dict, summary: list[dict]) -> list[str]:
    advice: list[str] = []
    for row in summary:
        if row["weakest"]:
            advice.append(f"{row['config']}: weakest dimension is {DIMENSION_LABELS[row['weakest']].lower()} "
                          f"({row['dimensions'][row['weakest']]}/5). {ADVICE[row['weakest']]}")
        coverage = row["deterministic"].get("topic_coverage")
        if coverage is not None and coverage < 0.8:
            advice.append(f"{row['config']}: deterministic topic coverage is {coverage:.0%}; questions miss expected JD topics.")
        if row["success_rate"] < 1:
            advice.append(f"{row['config']}: {len(row['errors'])} generation(s) failed validation or the API; see errors.")
    suggestions = Counter(s for r in results["records"] for s in r.get("judge_suggestions", []))
    advice += [f"Judge suggestion (seen {count}x): {text}" for text, count in suggestions.most_common(3)]
    return advice


LIMITATIONS = [
    "LLM judges are themselves models: scores can vary between runs and models, and may favour fluent or longer text despite instructions.",
    "Self-preference bias is reduced by using a judge from a different model family, but not eliminated.",
    "Position bias is measured by judging each output twice with the question order reversed; the disagreement is reported.",
    "Technical accuracy is judged without ground-truth answers; a judge can miss subtle errors or flag correct answers.",
    "The dataset is small (8 cases); differences below the noise threshold should not be treated as real.",
    "Deterministic checks are reliable but shallow: keyword coverage and embedding similarity are proxies for relevance and novelty.",
]


def to_markdown(results: dict) -> str:
    meta, summary = results["meta"], summarize(results)
    noise = noise_level(summary)
    lines = [
        "# Evaluation results", "",
        f"Run {meta['run_at']} · {len(meta['cases'])} cases · judge `{meta['judge_model']}` ({meta['judge_licence']}) · "
        f"{meta['judge_passes']} judge passes · differences under {noise} are treated as noise", "",
        "## Scores by configuration (judge, 1-5)", "",
        "| Config | Model | Prompt | Licence | Overall | " + " | ".join(DIMENSION_LABELS[k] for k in DIMENSION_KEYS) + " |",
        "| --- | --- | --- | --- | --- | " + " | ".join("---" for _ in DIMENSION_KEYS) + " |",
    ]
    for row in summary:
        lines.append(f"| {row['config']} | `{row['model']}` | {row['prompt_version']} | {row['licence']} | **{row['overall']}** | "
                     + " | ".join(str(row["dimensions"][k]) for k in DIMENSION_KEYS) + " |")
    lines += ["", "## Strongest and weakest dimensions", ""]
    for row in summary:
        if row["strongest"]:
            lines.append(f"- **{row['config']}**: strongest {DIMENSION_LABELS[row['strongest']]} ({row['dimensions'][row['strongest']]}), "
                         f"weakest {DIMENSION_LABELS[row['weakest']]} ({row['dimensions'][row['weakest']]})")
    lines += ["", "## Deterministic checks (no LLM)", "",
              "| Config | Success | " + " | ".join(label for _, label in DETERMINISTIC_KEYS) + " |",
              "| --- | --- | " + " | ".join("---" for _ in DETERMINISTIC_KEYS) + " |"]
    for row in summary:
        lines.append(f"| {row['config']} | {row['success_rate']:.0%} | " + " | ".join(str(row["deterministic"][k]) for k, _ in DETERMINISTIC_KEYS) + " |")
    lines += ["", "## Model comparison (improved prompt)", "", "| Config | Model | Overall | Latency (s) | Output tokens | Cost per case | Judge disagreement |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in model_comparison(summary):
        cost = f"${row['cost_per_case']:.5f}" if row["cost_per_case"] is not None else "n/a"
        lines.append(f"| {row['config']} | `{row['model']}` | {row['overall']} | {row['latency_s']} | {row['tokens_out']} | {cost} | {row['judge_disagreement']} |")
    comparison = prompt_comparison(summary)
    if comparison:
        lines += ["", f"## Prompt comparison on `{comparison['model']}` (v1 original vs v2 improved)", "",
                  "| Dimension | v1 | v2 | Delta | Beyond noise? |", "| --- | --- | --- | --- | --- |"]
        for item in comparison["rows"]:
            values = [value for key, value in item.items() if key not in ("dimension", "delta", "meaningful")]
            lines.append(f"| {item['dimension']} | {values[0]} | {values[1]} | {item['delta']:+} | {'yes' if item['meaningful'] else 'no'} |")
        lines.append(f"\nOverall: v1 {comparison['v1']['overall']} → v2 {comparison['v2']['overall']}. "
                     f"Topic coverage: {comparison['v1']['deterministic']['topic_coverage']} → {comparison['v2']['deterministic']['topic_coverage']}.")
    lines += ["", "## Recommendations", ""] + [f"- {item}" for item in recommendations(results, summary)]
    lines += ["", "## Limitations of LLM-as-a-judge", ""] + [f"- {item}" for item in LIMITATIONS]
    lines += ["", "## Individual results", ""]
    for record in results["records"]:
        status = f"judge {record.get('judge_overall')}" if record.get("judge") else ("generated" if record["ok"] else f"FAILED: {record['error']}")
        lines.append(f"### {record['config']} · {record['case_id']} ({record['difficulty']}) · {status}")
        if record["ok"]:
            for question in record["generation"]["questions"]:
                lines.append(f"- {question['question']}")
            det = record["deterministic"]
            lines.append(f"\nDeterministic: coverage {det['topic_coverage']:.0%}, max similarity {det['max_pair_similarity']}, issues: {', '.join(det['issues']) or 'none'}")
            if record.get("judge"):
                lines.append("\n| Dimension | Score | Passes | Explanation |\n| --- | --- | --- | --- |")
                for key in DIMENSION_KEYS:
                    item = record["judge"][key]
                    lines.append(f"| {DIMENSION_LABELS[key]} | {item['score']} | {item['passes']} | {item['explanations'][0].replace('|', '/')} |")
        lines.append("")
    return "\n".join(lines)

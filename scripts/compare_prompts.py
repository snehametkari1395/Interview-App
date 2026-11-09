"""Compare the five system-prompt techniques on the human-labelled answer set.

    uv run python scripts/compare_prompts.py            # 5 techniques x 4 cases x 2 runs = 40 calls on the configured model
    uv run python scripts/compare_prompts.py --runs 1

Writes docs/prompt_techniques/latest.json and docs/PROMPT_TECHNIQUES.md.
"""

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
logging.disable(logging.WARNING)

from interview_app.catalog import PrepProfile  # noqa: E402
from interview_app.chains.llm import ModelSpec  # noqa: E402
from interview_app.model_config import GenerationParams  # noqa: E402
from interview_app.openrouter import get_api_key, get_capabilities, get_model  # noqa: E402
from interview_app.prompt_techniques import TECHNIQUES, TEST_CASES, rank, run_comparison, save_results, summarize  # noqa: E402
from interview_app.prompts import SECURITY_RULES  # noqa: E402


def report(results: dict) -> str:
    rows = rank(summarize(results))
    best = rows[0]
    meta = results["meta"]
    lines = [
        "# System prompt techniques: comparison", "",
        f"Run {meta['run_at']} · model `{meta['model']}` · reasoning effort {meta['reasoning_effort']} · "
        f"{meta['cases']} human-labelled answers × {meta['runs']} runs per technique", "",
        "Task: evaluate a candidate's interview answer (score 1–5 plus feedback). All five prompts share the same defensive "
        "security rules and output fields; only the prompting technique differs. Scoring is deterministic: each answer has a "
        "human-assigned expected score range.", "",
        "## Results (best first)", "",
        "| Rank | Technique | Valid | Accuracy (score in expected range) | Mean distance from range | Consistency (same score both runs) | Latency (s) | Output tokens | Cost per call |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for position, row in enumerate(rows, start=1):
        consistency = f"{row['consistency']:.0%}" if row["consistency"] is not None else "n/a"
        lines.append(f"| {position} | **{row['technique']}** | {row['valid']} | {row['accuracy']:.0%} | {row['mean_abs_error']} | "
                     f"{consistency} | {row['latency_s']} | {row['output_tokens']} | ${row['cost_per_call']:.5f} |")
    lines += ["", f"**Best: {best['technique']}.** Ranking order: accuracy, then distance from the expected range, then consistency, then cost. "
              f"The app uses this technique for answer evaluation (chain C).", ""]
    lines += ["## Findings", ""]
    consistent = max(rows, key=lambda r: r["consistency"] or 0)
    cheapest = min(rows, key=lambda r: r["cost_per_call"] or 9)
    lines.append(f"- Most consistent: **{consistent['technique']}** ({consistent['consistency']:.0%} of answers scored identically in both runs).")
    fastest = min(rows, key=lambda r: r["latency_s"] or 99)
    lines.append(f"- Cheapest: **{cheapest['technique']}** (${cheapest['cost_per_call']:.5f} per call). "
                 f"Fastest: **{fastest['technique']}** ({fastest['latency_s']} s on average).")
    for technique in TECHNIQUES:
        ok = [r for r in results["records"] if r["technique"] == technique.key and r["ok"]]
        low = sum(r["score"] < r["expected"][0] for r in ok)
        high = sum(r["score"] > r["expected"][1] for r in ok)
        if low or high:
            lines.append(f"- {technique.name}: {low} run(s) scored below the expected range and {high} above it"
                         + (" (tends to be harsh)." if low > high else " (tends to be lenient)." if high > low else "."))
    lines.append(f"- All techniques handled the hard cases (a confidently wrong answer and a buzzword-heavy answer) within range unless listed above.")
    lines.append(f"- Caveat: {meta['cases']} answers × {meta['runs']} runs per technique is a small sample; one or two runs separate several techniques.")
    lines.append("")
    lines += ["## Scores per answer", "", "| Technique | " + " | ".join(f"{c['id']} (expected {c['expected'][0]}–{c['expected'][1]})" for c in TEST_CASES) + " |",
              "| --- | " + " | ".join("---" for _ in TEST_CASES) + " |"]
    for technique in TECHNIQUES:
        cells = []
        for case in TEST_CASES:
            scores = [str(r["score"]) if r["ok"] else "error" for r in results["records"] if r["technique"] == technique.key and r["case"] == case["id"]]
            cells.append(", ".join(scores))
        lines.append(f"| {technique.name} | " + " | ".join(cells) + " |")
    lines += ["", "## The five prompts", "",
              "Each prompt is shown with the shared security rules collapsed into `[SHARED SECURITY RULES]` (see `interview_app/prompts.py`). "
              "The examples below use the Backend Developer test case's profile.", ""]
    profile = PrepProfile("IT / Software Engineering", "Backend Developer", "Medium", "Balanced", "Neutral")
    for technique in TECHNIQUES:
        text = technique.build(profile).replace(SECURITY_RULES, "[SHARED SECURITY RULES]")
        lines += [f"### {technique.name}", "", technique.description, "", "```text", text, "```", ""]
    errors = [r for r in results["records"] if not r["ok"]]
    if errors:
        lines += ["## Errors", ""] + [f"- {r['technique']} · {r['case']}: {r['error']}" for r in errors]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--model", default=None)
    parser.add_argument("--report-only", action="store_true", help="rebuild the report from the saved results (no API calls)")
    args = parser.parse_args()
    if args.report_only:
        from interview_app.prompt_techniques import load_results

        (ROOT / "docs" / "PROMPT_TECHNIQUES.md").write_text(report(load_results()), encoding="utf-8")
        print("Rebuilt docs/PROMPT_TECHNIQUES.md")
        return 0
    if not get_api_key():
        print("OPENROUTER_API_KEY is not configured.")
        return 2
    model = args.model or get_model()
    spec = ModelSpec(model, GenerationParams(), get_capabilities(model), get_api_key())
    print(f"Running {len(TECHNIQUES)} techniques x {len(TEST_CASES)} cases x {args.runs} runs on {model}...")
    results = run_comparison(spec, runs=args.runs, progress=lambda done, total: print(f"  {done}/{total}", end="\r", flush=True))
    save_results(results)
    (ROOT / "docs" / "PROMPT_TECHNIQUES.md").write_text(report(results), encoding="utf-8")
    for row in rank(summarize(results)):
        print(f"{row['technique']:18} valid {row['valid']:5} accuracy {row['accuracy']:.0%}  error {row['mean_abs_error']}  "
              f"consistency {row['consistency']}  latency {row['latency_s']}s  cost/call ${row['cost_per_call']:.5f}")
    print("Wrote docs/PROMPT_TECHNIQUES.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

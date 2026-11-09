"""Run the prompt and model evaluation and write the report.

    uv run python scripts/run_evaluation.py                       # show the plan and cost estimate only
    uv run python scripts/run_evaluation.py --yes                 # run with the defaults
    uv run python scripts/run_evaluation.py --models a,b --judge c --cases it-backend-medium,data-analyst-easy --yes

Defaults: the open-weight comparison models from interview_app.licensing (v2 prompt), plus the
original v1 prompt on the first model for the prompt comparison, judged twice by JUDGE_MODEL.
Writes docs/evaluation/latest.json, a timestamped copy, and docs/EVALUATION_RESULTS.md.
"""

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
logging.disable(logging.WARNING)

from interview_app.evaluation.report import summarize, to_markdown  # noqa: E402
from interview_app.evaluation.runner import EvalConfig, load_dataset, run_evaluation, save_results  # noqa: E402
from interview_app.licensing import COMPARISON_MODELS, JUDGE_MODEL, classify  # noqa: E402
from interview_app.openrouter import get_api_key, get_capabilities  # noqa: E402
from interview_app.pricing import estimate_cost  # noqa: E402
from interview_app.vectorstore import QuestionMemory  # noqa: E402

GEN_TOKENS = (1500, 1300)    # rough input/output tokens per generation (3 questions)
JUDGE_TOKENS = (3200, 900)   # rough input/output tokens per judge pass


def build_configs(models: list[str], prompt_comparison: bool) -> list[EvalConfig]:
    configs = [EvalConfig(f"{model.split('/')[-1]} · v2", model, "v2-improved") for model in models]
    if prompt_comparison and models:
        configs.append(EvalConfig(f"{models[0].split('/')[-1]} · v1", models[0], "v1-original"))
    return configs


def estimate(configs, cases, judge, passes) -> float:
    total = 0.0
    for config in configs:
        cost = estimate_cost(config.model, get_capabilities(config.model).pricing, *GEN_TOKENS).total
        total += (cost or 0) * len(cases)
    if judge:
        cost = estimate_cost(judge, get_capabilities(judge).pricing, *JUDGE_TOKENS).total
        total += (cost or 0) * len(cases) * len(configs) * passes
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", default=",".join(COMPARISON_MODELS))
    parser.add_argument("--judge", default=JUDGE_MODEL, help="judge model; use 'none' for deterministic checks only")
    parser.add_argument("--cases", default="", help="comma-separated case ids (default: all)")
    parser.add_argument("--passes", type=int, default=2)
    parser.add_argument("--no-prompt-comparison", action="store_true")
    parser.add_argument("--yes", action="store_true", help="actually run (otherwise only print the plan)")
    args = parser.parse_args()

    api_key = get_api_key()
    if not api_key:
        print("OPENROUTER_API_KEY is not configured.")
        return 2
    models = [model.strip() for model in args.models.split(",") if model.strip()]
    judge = None if args.judge.lower() == "none" else args.judge
    cases = load_dataset()
    if args.cases:
        wanted = {case_id.strip() for case_id in args.cases.split(",")}
        cases = [case for case in cases if case["id"] in wanted]
    configs = build_configs(models, not args.no_prompt_comparison)

    calls = len(configs) * len(cases) * (1 + (args.passes if judge else 0))
    print(f"Plan: {len(configs)} configs x {len(cases)} cases, judge {judge or 'none'} x {args.passes} passes = {calls} model calls")
    for config in configs:
        print(f"  {config.label:32} {config.model:45} {classify(config.model).category}")
    if judge:
        print(f"  judge: {judge} ({classify(judge).category})")
    print(f"Estimated cost: ${estimate(configs, cases, judge, args.passes):.4f}")
    if not args.yes:
        print("Dry run. Add --yes to run.")
        return 0

    embedder = QuestionMemory(path=None).embed

    def progress(done, total, record):
        status = f"judge {record.get('judge_overall')}" if record.get("judge") else ("ok" if record["ok"] else f"FAILED {record['error'][:60]}")
        print(f"[{done}/{total}] {record['config']:32} {record['case_id']:26} {status}", flush=True)

    results = run_evaluation(configs, cases, api_key=api_key, judge_model=judge, embed=embedder, passes=args.passes, progress=progress)
    path = save_results(results)
    report = ROOT / "docs" / "EVALUATION_RESULTS.md"
    report.write_text(to_markdown(results), encoding="utf-8")
    for row in summarize(results):
        cost = f"${row['cost_per_case']:.5f}" if row["cost_per_case"] is not None else "n/a"
        print(f"{row['config']:32} overall {row['overall']}  success {row['success_rate']:.0%}  latency {row['latency_s']}s  cost/case {cost}")
    print(f"Saved {path.relative_to(ROOT)} and {report.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

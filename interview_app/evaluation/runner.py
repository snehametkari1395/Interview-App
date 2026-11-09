"""Evaluation runner: generate -> deterministic checks -> LLM judge (two passes) for each config x case."""

import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from interview_app.catalog import PrepProfile
from interview_app.chains.llm import ModelSpec
from interview_app.chains.workflows import question_chain
from interview_app.evaluation.checks import Embedder, run_checks
from interview_app.evaluation.judge import DIMENSION_KEYS, judge_once
from interview_app.licensing import classify
from interview_app.model_config import GenerationParams
from interview_app.openrouter import describe_error, get_capabilities
from interview_app.vectorstore import Thresholds

ROOT = Path(__file__).resolve().parent.parent.parent
DATASET_PATH = ROOT / "evals" / "dataset.json"
RESULTS_DIR = ROOT / "docs" / "evaluation"


@dataclass(frozen=True)
class EvalConfig:
    label: str
    model: str
    prompt_version: str = "v2-improved"


def load_dataset(path: Path = DATASET_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def profile_for(case: dict) -> PrepProfile:
    return PrepProfile(case["domain"], case["role"], case["difficulty"], "Balanced", "Neutral").validated()


def make_spec(model: str, api_key: str, params: GenerationParams | None = None) -> ModelSpec:
    return ModelSpec(model=model, params=params or GenerationParams(temperature=0.4), capabilities=get_capabilities(model), api_key=api_key)


def evaluate_case(config: EvalConfig, case: dict, *, gen_spec: ModelSpec, judge_spec: ModelSpec | None,
                  embed: Embedder, thresholds: Thresholds, passes: int = 2) -> dict:
    record: dict = {
        "config": config.label, "model": config.model, "prompt_version": config.prompt_version,
        "licence": classify(config.model).category, "case_id": case["id"], "domain": case["domain"],
        "difficulty": case["difficulty"], "ok": False, "error": "",
    }
    chain = question_chain(gen_spec, profile_for(case), config.prompt_version, case["count"])
    payload = {"number_of_questions": case["count"], "focus": case["focus"], "avoid": [], "job_context": case["job_context"]}
    started = time.perf_counter()
    try:
        output = chain.invoke(payload)
    except Exception as error:  # a failed generation is a result, not a crash
        record.update(error=describe_error(error), latency_s=round(time.perf_counter() - started, 2))
        return record
    record.update(
        ok=True,
        latency_s=round(output.latency_s, 2),
        tokens_in=output.usage.get("prompt_tokens"),
        tokens_out=output.usage.get("completion_tokens"),
        cost_usd=output.cost.best_total if output.cost else None,
        served_model=output.model,
        generation=output.data,
        deterministic=run_checks(output.data, case, embed, thresholds).as_dict(),
    )
    if judge_spec is None:
        return record

    pass_scores: list[dict] = []
    weaknesses, suggestions, judge_cost = [], [], 0.0
    explanations: dict[str, list[str]] = {key: [] for key in DIMENSION_KEYS}
    for number in range(passes):
        try:
            judged = judge_once(judge_spec, case, output.data, reverse=number % 2 == 1)
        except Exception as error:
            record["judge_error"] = describe_error(error)
            continue
        if judged.cost and judged.cost.best_total:
            judge_cost += judged.cost.best_total
        pass_scores.append({key: judged.data["scores"][key]["score"] for key in DIMENSION_KEYS})
        for key in DIMENSION_KEYS:
            explanations[key].append(judged.data["scores"][key]["explanation"])
        weaknesses += judged.data["weaknesses"]
        suggestions += judged.data["suggestions"]
    if pass_scores:
        record["judge"] = {
            key: {"score": round(statistics.mean(scores[key] for scores in pass_scores), 2),
                  "passes": [scores[key] for scores in pass_scores], "explanations": explanations[key]}
            for key in DIMENSION_KEYS
        }
        record["judge_overall"] = round(statistics.mean(record["judge"][key]["score"] for key in DIMENSION_KEYS), 2)
        if len(pass_scores) > 1:
            record["judge_disagreement"] = round(statistics.mean(
                abs(pass_scores[0][key] - pass_scores[1][key]) for key in DIMENSION_KEYS), 2)
        record["judge_weaknesses"] = list(dict.fromkeys(weaknesses))[:6]
        record["judge_suggestions"] = list(dict.fromkeys(suggestions))[:6]
        record["judge_cost_usd"] = round(judge_cost, 6)
    return record


def run_evaluation(configs: list[EvalConfig], cases: list[dict], *, api_key: str, judge_model: str | None,
                   embed: Embedder, thresholds: Thresholds | None = None, passes: int = 2, workers: int = 4,
                   progress: Callable[[int, int, dict], None] | None = None) -> dict:
    thresholds = thresholds or Thresholds()
    judge_spec = make_spec(judge_model, api_key, GenerationParams(temperature=0.0, max_tokens=2500)) if judge_model else None
    specs = {config.model: make_spec(config.model, api_key) for config in configs}
    jobs = [(config, case) for config in configs for case in cases]
    records: list[dict] = []
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(evaluate_case, config, case, gen_spec=specs[config.model], judge_spec=judge_spec,
                               embed=embed, thresholds=thresholds, passes=passes) for config, case in jobs]
        for done, future in enumerate(futures, start=1):
            record = future.result()
            records.append(record)
            if progress:
                progress(done, len(jobs), record)
    return {
        "meta": {
            "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "duration_s": round(time.perf_counter() - started, 1),
            "configs": [config.__dict__ for config in configs],
            "judge_model": judge_model, "judge_licence": classify(judge_model).category if judge_model else None,
            "judge_passes": passes, "cases": [case["id"] for case in cases],
            "thresholds": {"duplicate": thresholds.duplicate, "similar": thresholds.similar},
        },
        "records": records,
    }


def save_results(results: dict, directory: Path = RESULTS_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = results["meta"]["run_at"].replace(":", "").replace("-", "")[:15]
    path = directory / f"results_{stamp}.json"
    text = json.dumps(results, indent=2, ensure_ascii=False)
    path.write_text(text, encoding="utf-8")
    (directory / "latest.json").write_text(text, encoding="utf-8")
    return path


def load_latest(directory: Path = RESULTS_DIR) -> dict | None:
    path = directory / "latest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

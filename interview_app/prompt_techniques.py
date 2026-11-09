"""Five system-prompt techniques for the same task (evaluating an interview answer), and a comparison.

Every technique shares the same defensive security rules (``SECURITY_RULES``: untrusted data,
ignore overrides, canary) and the same output fields (the Format 2 evaluation), so the comparison
isolates the prompting technique itself. Chain-of-thought and self-critique add their own working
fields, which are kept out of the final evaluation.

Scoring is deterministic, against a small human-labelled test set: no LLM judge is involved.
"""

import copy
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from interview_app.catalog import PrepProfile
from interview_app.chains.base import StructuredChain
from interview_app.chains.llm import ModelSpec
from interview_app.openrouter import describe_error
from interview_app.prompts import SCORE_RUBRIC, _compose, context_block
from interview_app.schemas import EVALUATION_MODEL_SCHEMA, _string

ROOT = Path(__file__).resolve().parent.parent
RESULTS_PATH = ROOT / "docs" / "prompt_techniques" / "latest.json"

_FIELDS = """{
  "overall_score": integer 1-5,
  "summary": string, 1-2 sentences,
  "technical_accuracy": {"score": integer 1-5, "comment": string},
  "communication_skills": {"score": integer 1-5, "comment": string},
  "problem_solving": {"score": integer 1-5, "comment": string},
  "strengths": array of 0-5 strings,
  "weaknesses": array of 0-5 strings,
  "missing_concepts": array of 0-6 strings,
  "improvement_suggestions": array of 1-5 strings,
  "recommended_follow_up_questions": array of 1-4 strings
}"""


def _schema_with(extra: dict) -> dict:
    """The evaluation schema with extra working fields placed first (so they are generated first)."""
    schema = copy.deepcopy(EVALUATION_MODEL_SCHEMA)
    schema["properties"] = {**extra, **schema["properties"]}
    schema["required"] = [*extra, *schema["required"]]
    return schema


# -- 1. Zero-shot ---------------------------------------------------------------------------

def zero_shot(profile: PrepProfile) -> str:
    return _compose(
        "You evaluate interview answers.",
        f"TASK\nEvaluate the candidate answer to the interview question for a {profile.role} role at {profile.difficulty} difficulty. "
        "Score from 1 (poor) to 5 (excellent).",
        f"OUTPUT SCHEMA\n{_FIELDS}",
    )


# -- 2. Few-shot ----------------------------------------------------------------------------

_EXAMPLES = """EXAMPLES (different questions from the one you will evaluate; follow their calibration and style)

Example 1 · Question: "How would you prevent duplicate orders when a client retries a checkout request?" (Medium)
Answer: "I'd require an idempotency key per checkout, store it with the order in the same database transaction under a unique constraint, and return the stored response on retries. I'd expire keys after 24 hours and log conflicts."
Evaluation: {"overall_score": 5, "summary": "Complete, correct, and practical design with storage, atomicity, and expiry covered.", "technical_accuracy": {"score": 5, "comment": "Idempotency keys with a unique constraint in the same transaction are correct."}, "communication_skills": {"score": 4, "comment": "Concise and ordered."}, "problem_solving": {"score": 5, "comment": "Covers retries, concurrency, and cleanup."}, "strengths": ["Atomic storage of key and order", "Considers key expiry"], "weaknesses": ["Does not mention the response when a request is still in progress"], "missing_concepts": ["Handling in-flight duplicates"], "improvement_suggestions": ["Explain what a retry receives while the first request is still processing"], "recommended_follow_up_questions": ["What happens if two retries arrive at the same time?"]}

Example 2 · Question: "What is the difference between a primary key and a foreign key?" (Easy)
Answer: "A primary key is the main key. A foreign key is a key from somewhere else."
Evaluation: {"overall_score": 2, "summary": "Vague definitions with no explanation of uniqueness or referential integrity.", "technical_accuracy": {"score": 2, "comment": "Not wrong, but too vague to show understanding."}, "communication_skills": {"score": 3, "comment": "Clear but minimal."}, "problem_solving": {"score": 2, "comment": "No example or application."}, "strengths": [], "weaknesses": ["No mention of uniqueness", "No mention of referencing another table"], "missing_concepts": ["Uniqueness and non-null", "Referential integrity"], "improvement_suggestions": ["Define each key precisely and give a two-table example"], "recommended_follow_up_questions": ["What happens if you delete a row that a foreign key references?"]}"""


def few_shot(profile: PrepProfile) -> str:
    return _compose(
        "You evaluate interview answers.",
        context_block(profile, include_persona=False),
        _EXAMPLES,
        "TASK\nEvaluate the candidate answer in the user message the same way as the examples.",
        f"OUTPUT SCHEMA\n{_FIELDS}",
    )


# -- 3. Chain-of-thought --------------------------------------------------------------------

def chain_of_thought(profile: PrepProfile) -> str:
    return _compose(
        "You evaluate interview answers.",
        context_block(profile, include_persona=False),
        """TASK
Think step by step before scoring, and write your reasoning in "reasoning" first:
1. List the key points a strong answer to this question must cover at this difficulty.
2. Compare the candidate's answer against each point: covered, partially covered, missing, or wrong.
3. Decide each dimension score from that comparison, then the overall score.
Only then fill in the evaluation fields, consistent with your reasoning.""",
        f'OUTPUT SCHEMA\n{{\n  "reasoning": string, your step-by-step analysis,\n{_FIELDS[2:]}',
    )


# -- 4. Role + rubric (the app's original approach) ---------------------------------------------

def role_rubric(profile: PrepProfile) -> str:
    return _compose(
        f"You are a senior hiring manager with 15 years of experience interviewing {profile.role} candidates in {profile.domain}. "
        "You are fair, precise, and evidence-based.",
        context_block(profile, include_persona=False),
        "TASK\nEvaluate the candidate answer to the interview question. Base every point on what the candidate actually wrote.",
        SCORE_RUBRIC,
        f"OUTPUT SCHEMA\n{_FIELDS}",
    )


# -- 5. Self-critique ------------------------------------------------------------------------

def self_critique(profile: PrepProfile) -> str:
    return _compose(
        "You evaluate interview answers and check your own work.",
        context_block(profile, include_persona=False),
        SCORE_RUBRIC,
        """TASK
1. Write a draft overall score and a one-sentence justification ("draft_assessment").
2. Critique the draft ("critique"): were you too lenient or too harsh for this difficulty? Did you miss a correct point or an error?
3. Give the final evaluation, adjusting the draft where the critique found a problem.""",
        f'OUTPUT SCHEMA\n{{\n  "draft_assessment": string,\n  "critique": string,\n{_FIELDS[2:]}',
    )


@dataclass(frozen=True)
class Technique:
    key: str
    name: str
    description: str
    build: Callable[[PrepProfile], str]
    schema: dict


TECHNIQUES: tuple[Technique, ...] = (
    Technique("zero_shot", "Zero-shot", "A minimal instruction and output format; no rubric, context, or examples.", zero_shot, EVALUATION_MODEL_SCHEMA),
    Technique("few_shot", "Few-shot", "Two worked examples (one strong, one weak) show the expected calibration and style.", few_shot, EVALUATION_MODEL_SCHEMA),
    Technique("chain_of_thought", "Chain-of-thought", "Step-by-step reasoning (expected points, comparison, then scores) written before the evaluation.",
              chain_of_thought, _schema_with({"reasoning": _string(10, 4000)})),
    Technique("role_rubric", "Role + rubric", "An expert hiring-manager persona with an anchored 1–5 rubric (the app's original approach).", role_rubric, EVALUATION_MODEL_SCHEMA),
    Technique("self_critique", "Self-critique", "Draft a score, critique it for leniency or harshness, then finalise.",
              self_critique, _schema_with({"draft_assessment": _string(5, 800), "critique": _string(5, 1200)})),
)
TECHNIQUE_BY_KEY = {technique.key: technique for technique in TECHNIQUES}
# The technique the app uses for answer evaluation (chain C), chosen from the comparison in
# docs/PROMPT_TECHNIQUES.md: few-shot tied on accuracy and was the cheapest and fastest.
PRODUCTION_TECHNIQUE = "few_shot"
WORKING_FIELDS = ("reasoning", "draft_assessment", "critique")

# Human-labelled test set: expected overall score range for each answer.
TEST_CASES: tuple[dict, ...] = (
    {"id": "backend-strong", "profile": ("IT / Software Engineering", "Backend Developer", "Medium"),
     "question": "How would you design a REST endpoint for creating payments so that client retries never charge a customer twice?",
     "answer": "I'd require an Idempotency-Key header. The server stores the key, a hash of the request, and the final response in the same "
               "database transaction as the payment, with a unique constraint on the key. A retry with the same key returns the stored response; "
               "the same key with a different body returns 422. While the first request is still processing, a retry gets 409 so the client "
               "backs off. Keys expire after 24 hours.",
     "expected": (4, 5)},
    {"id": "analyst-partial", "profile": ("Data Science", "Data Analyst", "Easy"),
     "question": "What is the difference between the mean and the median, and when would you report the median instead?",
     "answer": "The mean is the average of all the values and the median is the middle value when you sort them. I would use the median sometimes.",
     "expected": (2, 3)},
    {"id": "finance-weak", "profile": ("Finance", "Financial Analyst", "Medium"),
     "question": "A business unit is 12% over budget halfway through the year. How would you analyse and report the variance?",
     "answer": "I would tell them to spend less money for the rest of the year.",
     "expected": (1, 2)},
    {"id": "hr-strong", "profile": ("Human Resources", "Talent Acquisition Specialist", "Medium"),
     "question": "A hiring manager wants to skip the structured interview for a senior engineer because they 'just know' who they like. How do you respond?",
     "answer": "I'd acknowledge their experience, then explain that unstructured interviews predict performance poorly and expose us to bias and "
               "legal risk. I'd offer to keep it light: the same four competency questions for every candidate, a shared scorecard with "
               "behavioural anchors, and independent scoring before the debrief. If time is the concern, I'd cut the panel to two interviewers "
               "rather than drop the structure, and I'd share our offer-acceptance and 90-day retention data from structured hires.",
     "expected": (4, 5)},
    # Harder cases, where evaluators commonly fail.
    {"id": "confident-wrong", "profile": ("Data Science", "Data Scientist", "Medium"),
     "question": "Your A/B test shows p = 0.03 for the new checkout button. How do you interpret that result for the product team?",
     "answer": "A p-value of 0.03 means there is a 97% probability that the new button is better, so we can be 97% confident it will "
               "increase conversion. Because it's under 0.05 the effect is also large enough to matter, so I'd recommend shipping it to "
               "everyone immediately and moving on.",
     "expected": (1, 2)},
    {"id": "verbose-shallow", "profile": ("Business / Management", "Product Manager", "Hard"),
     "question": "Your largest customer demands a feature while reliability incidents are rising. How do you decide what the team works on next?",
     "answer": "I would leverage a holistic, data-driven, customer-centric approach and align all stakeholders around a shared north-star "
               "vision. Synergy between engineering and sales is key, so I'd facilitate an agile, collaborative workshop to ideate on "
               "priorities and empower the team to own outcomes. Ultimately it's about balancing value and quality through best practices "
               "and continuous improvement, keeping communication transparent at every step.",
     "expected": (1, 2)},
    {"id": "terse-correct", "profile": ("IT / Software Engineering", "Software Engineer", "Easy"),
     "question": "What is the difference between a process and a thread?",
     "answer": "A process has its own memory space; threads run inside a process and share its memory. So threads are cheaper to create "
               "and switch between, but need synchronisation, and a crash in one thread can take down the whole process.",
     "expected": (4, 5)},
)


def _profile(case: dict) -> PrepProfile:
    domain, role, difficulty = case["profile"]
    return PrepProfile(domain, role, difficulty, "Balanced", "Neutral").validated()


def run_one(spec: ModelSpec, technique: Technique, case: dict, run: int) -> dict:
    chain = StructuredChain(system_prompt=technique.build(_profile(case)), schema=technique.schema,
                            schema_name=f"evaluation_{technique.key}", spec=spec.with_params(spec.params.with_min_tokens(2500)),
                            feature=f"Prompt technique: {technique.name}")
    record = {"technique": technique.key, "case": case["id"], "run": run, "expected": list(case["expected"])}
    started = time.perf_counter()
    try:
        output = chain.invoke({"interview_question": case["question"], "candidate_answer": case["answer"]})
    except Exception as error:
        return {**record, "ok": False, "error": describe_error(error), "latency_s": round(time.perf_counter() - started, 2)}
    score = output.data["overall_score"]
    low, high = case["expected"]
    return {
        **record, "ok": True, "score": score, "in_range": low <= score <= high,
        "abs_error": 0 if low <= score <= high else min(abs(score - low), abs(score - high)),
        "latency_s": round(output.latency_s, 2), "output_tokens": output.usage.get("completion_tokens"),
        "cost_usd": output.cost.best_total if output.cost else None, "summary": output.data["summary"],
        "working": {field: output.data[field][:600] for field in WORKING_FIELDS if field in output.data},
    }


def run_comparison(spec: ModelSpec, *, runs: int = 2, workers: int = 4, progress: Callable[[int, int], None] | None = None) -> dict:
    jobs = [(technique, case, run) for technique in TECHNIQUES for case in TEST_CASES for run in range(1, runs + 1)]
    records: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_one, spec, technique, case, run) for technique, case, run in jobs]
        for done, future in enumerate(futures, start=1):
            records.append(future.result())
            if progress:
                progress(done, len(jobs))
    return {"meta": {"run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "model": spec.model,
                     "reasoning_effort": spec.params.reasoning_effort, "runs": runs, "cases": len(TEST_CASES)},
            "records": records}


def summarize(results: dict) -> list[dict]:
    rows = []
    for technique in TECHNIQUES:
        records = [r for r in results["records"] if r["technique"] == technique.key]
        ok = [r for r in records if r["ok"]]
        pairs = {}
        for r in ok:
            pairs.setdefault(r["case"], []).append(r["score"])
        repeated = [scores for scores in pairs.values() if len(scores) > 1]
        rows.append({
            "key": technique.key,
            "technique": technique.name,
            "valid": f"{len(ok)}/{len(records)}",
            "accuracy": round(sum(r["in_range"] for r in ok) / len(records), 3) if records else 0.0,
            "mean_abs_error": round(statistics.mean(r["abs_error"] for r in ok), 2) if ok else None,
            "consistency": round(sum(max(s) == min(s) for s in repeated) / len(repeated), 3) if repeated else None,
            "latency_s": round(statistics.mean(r["latency_s"] for r in ok), 2) if ok else None,
            "output_tokens": round(statistics.mean(r["output_tokens"] or 0 for r in ok)) if ok else None,
            "cost_per_call": round(statistics.mean(r["cost_usd"] or 0 for r in ok), 6) if ok else None,
        })
    return rows


def rank(rows: list[dict]) -> list[dict]:
    """Best first: accuracy, then lower error, then consistency, then cost."""
    return sorted(rows, key=lambda r: (-r["accuracy"], r["mean_abs_error"] if r["mean_abs_error"] is not None else 9,
                                       -(r["consistency"] or 0), r["cost_per_call"] or 9))


def save_results(results: dict, path: Path = RESULTS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")


def load_results(path: Path = RESULTS_PATH) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

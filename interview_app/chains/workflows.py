"""The five LangChain workflows (chains A-E) plus duplicate-aware question generation.

Each factory returns a ``StructuredChain`` (an LCEL pipeline: guard -> prompt -> ChatOpenRouter ->
validate). Prompts live in ``chain_prompts``, schemas in ``chain_schemas``, and model
construction in ``chains.llm``, so prompts, chains, model configuration, and app logic stay separate.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

from interview_app.catalog import FOCUS_KIND, PrepProfile
from interview_app.chain_prompts import (
    followup_chain_prompt,
    interviewer_reply_prompt,
    triage_prompt,
    jd_chain_prompt,
    question_chain_prompt,
    summary_chain_prompt,
)
from interview_app.chain_schemas import (
    FOLLOWUP_SCHEMA,
    JD_ANALYSIS_SCHEMA,
    QUESTION_SET_SCHEMA,
    SUMMARY_SCHEMA,
    TRIAGE_SCHEMA,
)
from interview_app.chains.base import ChainOutput, ReplyStream, StructuredChain
from interview_app.chains.llm import ModelSpec
from interview_app.vectorstore import NoveltyCheck, QuestionMemory, Thresholds

MAX_JD_CHARS = 12000
MAX_ANSWER_CHARS = 8000
MAX_HINT_CHARS = 200


# A. Job description analysis ------------------------------------------------

def jd_analysis_chain(spec: ModelSpec, domain: str | None = None) -> StructuredChain:
    return StructuredChain(
        system_prompt=jd_chain_prompt(domain),
        schema=JD_ANALYSIS_SCHEMA,
        schema_name="job_description_analysis",
        spec=spec.with_params(spec.params.with_min_tokens(1800)),
        feature="A · Job description analysis",
        guard_fields={"job_description": MAX_JD_CHARS},
    )


# B. Question generation -----------------------------------------------------

def _difficulty_rule(difficulty: str):
    def check(data: dict) -> list[str]:
        wrong = [item["question"][:60] for item in data.get("questions", []) if item.get("difficulty") != difficulty]
        return [f"difficulty must be {difficulty} (wrong for: {', '.join(wrong)})"] if wrong else []
    return check


def question_chain(spec: ModelSpec, profile: PrepProfile, count: int = 3,
                   enforce_difficulty: bool = False) -> StructuredChain:
    """Chain B. With ``enforce_difficulty`` the whole set is rejected if any label differs (strict mode);
    by default mislabelled items are handled by the caller (dropped and regenerated, or measured in evaluation)."""
    return StructuredChain(
        system_prompt=question_chain_prompt(profile),
        schema=QUESTION_SET_SCHEMA,
        schema_name="interview_question_set",
        spec=spec.with_params(spec.params.with_min_tokens(400 + 450 * count)),
        feature="B · Question generation",
        guard_fields={"topic_hint": MAX_HINT_CHARS},
        semantic_check=_difficulty_rule(profile.difficulty) if enforce_difficulty else None,
    )


@dataclass
class GeneratedQuestions:
    accepted: list[dict]
    rejected: list[dict] = field(default_factory=list)
    outputs: list[ChainOutput] = field(default_factory=list)
    avoid_used: list[str] = field(default_factory=list)


def job_context_from(analysis: dict | None) -> dict | None:
    """Compact, model-written JD context (never the raw JD text) for downstream chains."""
    if not analysis or not analysis.get("is_job_description", True):
        return None
    return {
        "role_title": analysis.get("role_title", ""),
        "required_skills": [skill["name"] for skill in analysis.get("required_skills", [])][:10],
        "technical_competencies": analysis.get("technical_competencies", [])[:8],
        "behavioural_competencies": analysis.get("behavioural_competencies", [])[:8],
        "interview_topics": analysis.get("interview_topics", [])[:10],
    }


def generate_unique_questions(
    spec: ModelSpec,
    profile: PrepProfile,
    *,
    count: int,
    memory: QuestionMemory,
    thresholds: Thresholds,
    focus: str = "Balanced",
    topic_hint: str = "",
    job_context: dict | None = None,
    company: str = "",
    extra_avoid: list[str] | None = None,
    store: bool = True,
    max_rounds: int = 2,
    source: str = "question generation",
) -> GeneratedQuestions:
    """Chain B with semantic de-duplication.

    1. Retrieve the stored questions nearest to this request and send them as "avoid".
    2. Generate. Check each question against the vector store and this batch.
    3. Duplicates and questions labelled at the wrong difficulty are rejected, and replacements are
       requested (up to ``max_rounds`` more times).
    4. Accepted questions are labelled new or similar and stored with their metadata.
    """
    query = " ".join(filter(None, [profile.role, topic_hint, focus, " ".join((job_context or {}).get("interview_topics", [])[:5])]))
    avoid = memory.avoid_list(query, domain=profile.domain, k=8) + list(extra_avoid or [])
    result = GeneratedQuestions(accepted=[], avoid_used=list(avoid))
    accepted_vectors: list[list[float]] = []  # embeddings of result.accepted, in the same order
    for _round in range(max_rounds + 1):
        needed = count - len(result.accepted)
        if needed <= 0:
            break
        chain = question_chain(spec, profile, needed)
        payload: dict = {
            "number_of_questions": needed,
            "focus": f"{focus} ({FOCUS_KIND.get(focus, 'balanced mix')})",
            "avoid": (avoid + [item["question"] for item in result.accepted])[-20:],
        }
        if topic_hint:
            payload["topic_hint"] = topic_hint
        if job_context:
            payload["job_context"] = job_context
        output = chain.invoke(payload)
        result.outputs.append(output)
        candidates = []
        for item in output.data["questions"]:
            if item["difficulty"] != profile.difficulty:
                # The model labelled this question as a different level: drop it and ask for a replacement.
                result.rejected.append({**item, "novelty": f"wrong difficulty ({item['difficulty']})", "nearest": "", "similarity": 0.0})
                continue
            candidates.append(item)
        # One embedding call for the whole batch; each vector is reused for the novelty check and for storage.
        vectors = memory.embed([item["question"].strip() for item in candidates]) if candidates else []
        for item, vector in zip(candidates, vectors):
            batch = [accepted["question"] for accepted in result.accepted] if not store else None
            check: NoveltyCheck = memory.check(
                item["question"], thresholds, domain=profile.domain, extra_texts=batch,
                vector=vector, extra_vectors=accepted_vectors if batch else None,
            )
            item = {**item, "novelty": check.label, "nearest": check.best.text if check.best else "", "similarity": check.similarity}
            if check.label == "duplicate":
                result.rejected.append(item)
                avoid.append(item["question"])
                continue
            result.accepted.append(item)
            accepted_vectors.append(vector)
            if store:
                memory.add(item["question"], {
                    "domain": profile.domain, "role": profile.role, "company": company,
                    "difficulty": item["difficulty"], "category": item["category"], "topic": item["topic"],
                    "source": source, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }, vector=vector)
            if len(result.accepted) >= count:
                break
    return result


# C. Answer evaluation -------------------------------------------------------

def evaluation_chain(spec: ModelSpec, profile: PrepProfile) -> StructuredChain:
    """Chain C, built with the prompt technique that won the Prompt lab comparison."""
    from interview_app.prompt_techniques import PRODUCTION_TECHNIQUE, TECHNIQUE_BY_KEY

    technique = TECHNIQUE_BY_KEY[PRODUCTION_TECHNIQUE]
    return StructuredChain(
        system_prompt=technique.build(profile),
        schema=technique.schema,
        schema_name="interview_evaluation",
        spec=spec.with_params(spec.params.with_min_tokens(1200)),
        feature="C · Answer evaluation",
        guard_fields={"candidate_answer": MAX_ANSWER_CHARS},
    )


# D. Follow-up and adaptation --------------------------------------------------

def followup_chain(spec: ModelSpec, profile: PrepProfile) -> StructuredChain:
    return StructuredChain(
        system_prompt=followup_chain_prompt(profile),
        schema=FOLLOWUP_SCHEMA,
        schema_name="interview_next_question",
        spec=spec.with_params(spec.params.with_min_tokens(900)),
        feature="D · Follow-up",
    )


# Defensive triage --------------------------------------------------------------

BLOCKED_REPLY = ("I can't change how answers are scored or how this interview works, but I'm happy to keep going. "
                 "Please answer the current question in your own words.")


def triage_chain(spec: ModelSpec, profile: PrepProfile) -> StructuredChain:
    """Classify a candidate message (answer / clarification / off-topic / manipulation) before scoring it."""
    return StructuredChain(
        system_prompt=triage_prompt(profile),
        schema=TRIAGE_SCHEMA,
        schema_name="candidate_message_triage",
        spec=spec.with_params(spec.params.with_min_tokens(600)),
        feature="Defensive triage",
        guard_fields={"candidate_message": MAX_ANSWER_CHARS},
    )


# E. Interview summary -------------------------------------------------------

def summary_chain(spec: ModelSpec, profile: PrepProfile) -> StructuredChain:
    return StructuredChain(
        system_prompt=summary_chain_prompt(profile),
        schema=SUMMARY_SCHEMA,
        schema_name="interview_summary",
        spec=spec.with_params(spec.params.with_min_tokens(2000)),
        feature="E · Interview summary",
    )


# Streamed interviewer reply --------------------------------------------------

def interviewer_reply(spec: ModelSpec, profile: PrepProfile, question: str, evaluation: dict) -> ReplyStream:
    compact = {key: evaluation.get(key) for key in ("summary", "strengths", "weaknesses", "missing_concepts", "improvement_suggestions")}
    return ReplyStream(
        spec.with_params(replace(spec.params, max_tokens=max(300, min(spec.params.max_tokens, 600)))),
        interviewer_reply_prompt(profile),
        {"interview_question": question, "evaluation": compact},
        feature="Interviewer reply (streamed)",
    )

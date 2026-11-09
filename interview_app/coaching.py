"""Structured interview coaching, question generation, and job description analysis.

Each public function makes one model call and passes the raw JSON through a ``normalize_*``
function. Normalisers are pure: they coerce types, clamp numbers, cap lengths, and strip unsafe
markup, so the UI only ever renders validated data.
"""

from interview_app.catalog import FOCUS_KIND, PrepProfile
from interview_app.model_config import GenerationParams
from interview_app.openrouter import complete_json
from interview_app.prompts import jd_analysis_prompt, question_generation_prompt, review_prompt
from interview_app.security_guard import (
    GuardError,
    choice_field,
    dict_list_field,
    int_field,
    list_field,
    text_field,
)

QUESTION_KINDS = ("technical", "scenario", "behavioral")


def normalize_review(result: dict) -> dict:
    criteria = []
    for item in result.get("criteria", []) if isinstance(result.get("criteria"), list) else []:
        if isinstance(item, dict) and text_field(item, "name", 80):
            criteria.append({
                "name": text_field(item, "name", 80),
                "rating": int_field(item, "rating", 1, 5, 3),
                "comment": text_field(item, "comment", 300),
            })
    return {
        "score": int_field(result, "score", 1, 5, 3),
        "verdict": text_field(result, "verdict", 600),
        "interviewer_reaction": text_field(result, "interviewer_reaction", 400),
        "criteria": criteria[:4],
        "strengths": list_field(result, "strengths", limit=3),
        "improvements": list_field(result, "improvements", limit=3),
        "expected_points": list_field(result, "expected_points", limit=5, max_chars=300),
        "answer_steps": list_field(result, "answer_steps", limit=5),
        "sample_answer": text_field(result, "sample_answer", 3500),
        "follow_up": text_field(result, "follow_up", 800),
    }


def review_answer(
    profile: PrepProfile,
    mode: str,
    question: str,
    answer: str,
    *,
    input_flags: tuple[str, ...] = (),
    params: GenerationParams | None = None,
) -> dict:
    payload = {
        "mode": mode,
        "interview_question": question,
        "candidate_answer": answer,
    }
    if input_flags:
        payload["input_flags"] = list(input_flags)
    return normalize_review(complete_json(review_prompt(profile), payload, params, feature="Answer feedback").data)


def normalize_questions(result: dict, count: int) -> list[dict[str, str]]:
    raw = result.get("questions", [])
    if not isinstance(raw, list):
        raise GuardError("The AI did not return any questions. Please try again.")
    questions: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = text_field(item, "question", 500)
        if len(text) < 10 or text.lower() in seen:
            continue
        seen.add(text.lower())
        questions.append({
            "question": text,
            "topic": text_field(item, "topic", 60) or "General",
            "kind": choice_field(item, "kind", QUESTION_KINDS, "technical"),
            "hint": text_field(item, "hint", 300),
        })
        if len(questions) >= count:
            break
    if not questions:
        raise GuardError("The AI did not return usable questions. Please try again.")
    return questions


def generate_questions(
    profile: PrepProfile,
    focus: str,
    count: int,
    *,
    avoid: list[str] | None = None,
    params: GenerationParams | None = None,
) -> list[dict[str, str]]:
    focus_kind = FOCUS_KIND.get(focus, "balanced mix")
    payload = {
        "number_of_questions": int(count),
        "focus": f"{focus} ({focus_kind})",
        "avoid": (avoid or [])[:10],
    }
    params = (params or GenerationParams()).with_min_tokens(250 * count)
    return normalize_questions(complete_json(question_generation_prompt(profile), payload, params, feature="Question generation").data, count)


def normalize_jd_analysis(result: dict) -> dict:
    skills = dict_list_field(result, "skills", {"name": 100, "importance": 60, "evidence": 240}, limit=8, required="name")
    plan = [
        step
        for step in dict_list_field(result, "prep_plan", {"step": 100, "focus": 120, "action": 320}, limit=5)
        if step["step"] or step["action"]
    ]
    is_jd = result.get("is_job_description", True)
    return {
        "is_job_description": is_jd if isinstance(is_jd, bool) else True,
        "relevance_note": text_field(result, "relevance_note", 300),
        "role_summary": text_field(result, "role_summary", 1000),
        "skills": skills,
        "likely_questions": list_field(result, "likely_questions", limit=8),
        "prep_plan": plan,
    }


def analyze_job_description(
    role: str,
    description: str,
    domain: str | None = None,
    *,
    input_flags: tuple[str, ...] = (),
    params: GenerationParams | None = None,
) -> dict:
    payload = {"target_role": role, "job_description": description}
    if input_flags:
        payload["input_flags"] = list(input_flags)
    return normalize_jd_analysis(complete_json(jd_analysis_prompt(domain), payload, params, feature="Job description").data)

"""Interviewer evaluation guidelines for technical and behavioural interviews."""

from interview_app.catalog import INTERVIEW_TYPES, PrepProfile
from interview_app.model_config import GenerationParams
from interview_app.openrouter import chat_json
from interview_app.prompts import guideline_prompt
from interview_app.security_guard import GuardError, dict_list_field, int_field, list_field, text_field

DEFAULT_RUBRIC_LABELS = {1: "Insufficient", 2: "Developing", 3: "Competent", 4: "Strong", 5: "Exceptional"}


def normalize_rubric(raw) -> list[dict]:
    """Return exactly one row per score 1-5. Missing scores are filled with a neutral placeholder."""
    by_score: dict[int, dict] = {}
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        score = int_field(item, "score", 0, 6, 0)
        if 1 <= score <= 5 and score not in by_score:
            by_score[score] = {
                "score": score,
                "label": text_field(item, "label", 40) or DEFAULT_RUBRIC_LABELS[score],
                "description": text_field(item, "description", 400),
            }
    if len(by_score) < 3:
        raise GuardError("The AI returned an incomplete scoring rubric. Please try again.")
    return [
        by_score.get(score, {"score": score, "label": DEFAULT_RUBRIC_LABELS[score], "description": "Not provided by the model."})
        for score in range(1, 6)
    ]


def normalize_guide(result: dict) -> dict:
    return {
        "overview": text_field(result, "overview", 800),
        "competencies": dict_list_field(result, "competencies", {"name": 80, "description": 300}, limit=6, required="name"),
        "evaluation_criteria": dict_list_field(result, "evaluation_criteria", {"criterion": 100, "weight": 12, "look_for": 300}, limit=6, required="criterion"),
        "rubric": normalize_rubric(result.get("rubric")),
        "positive_indicators": list_field(result, "positive_indicators", limit=6, max_chars=300),
        "red_flags": list_field(result, "red_flags", limit=6, max_chars=300),
        "common_mistakes": list_field(result, "common_mistakes", limit=6, max_chars=300),
        "sample_question": text_field(result, "sample_question", 500),
        "strong_answer_example": text_field(result, "strong_answer_example", 3500),
        "follow_up_questions": list_field(result, "follow_up_questions", limit=5, max_chars=300),
        "interviewer_conduct": text_field(result, "interviewer_conduct", 500),
    }


def generate_guide(
    profile: PrepProfile,
    interview_type: str,
    focus_area: str = "",
    *,
    params: GenerationParams | None = None,
) -> dict:
    if interview_type not in INTERVIEW_TYPES:
        raise GuardError("Please choose a valid interview type.")
    payload: dict = {"interview_type": interview_type}
    if focus_area:
        payload["focus_area"] = focus_area
    params = (params or GenerationParams()).with_min_tokens(3000)
    return normalize_guide(chat_json(guideline_prompt(profile, interview_type), payload, params))


def guide_to_markdown(profile: PrepProfile, guides: dict[str, dict]) -> str:
    lines = [f"# Interviewer guide: {profile.role}", "", f"{profile.domain} · {profile.difficulty} difficulty · {profile.persona} interviewer", ""]
    for interview_type, guide in guides.items():
        lines += [f"## {interview_type} interview", "", guide["overview"], ""]
        lines += ["### Competencies", *[f"- **{c['name']}**: {c['description']}" for c in guide["competencies"]], ""]
        lines += ["### Evaluation criteria", "", "| Criterion | Weight | Look for |", "| --- | --- | --- |"]
        lines += [f"| {c['criterion']} | {c['weight']} | {c['look_for']} |" for c in guide["evaluation_criteria"]]
        lines += ["", "### Scoring rubric", ""]
        lines += [f"- **{row['score']} · {row['label']}**: {row['description']}" for row in guide["rubric"]]
        lines += ["", "### Positive indicators", *[f"- {item}" for item in guide["positive_indicators"]], ""]
        lines += ["### Red flags", *[f"- {item}" for item in guide["red_flags"]], ""]
        lines += ["### Common mistakes", *[f"- {item}" for item in guide["common_mistakes"]], ""]
        lines += ["### Example", "", f"**Question:** {guide['sample_question']}", "", f"**Strong answer:** {guide['strong_answer_example']}", ""]
        lines += ["### Follow-up questions", *[f"- {item}" for item in guide["follow_up_questions"]], ""]
        if guide["interviewer_conduct"]:
            lines += ["### Interviewer conduct", "", guide["interviewer_conduct"], ""]
    return "\n".join(lines)

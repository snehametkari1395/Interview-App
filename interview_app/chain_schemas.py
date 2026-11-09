"""JSON Schemas for the LangChain workflows. Chain C reuses the Format 2 evaluation schema."""

from interview_app.schemas import EVALUATION_MODEL_SCHEMA, _SCORE, _object, _string, _string_list

_CATEGORY = {"type": "string", "enum": ["technical", "scenario", "behavioral"]}
_DIFFICULTY = {"type": "string", "enum": ["Easy", "Medium", "Hard"]}

JD_ANALYSIS_SCHEMA = _object({
    "is_job_description": {"type": "boolean"},
    "relevance_note": _string(0, 300),
    "role_title": _string(0, 120),
    "company": _string(0, 120),
    "role_summary": _string(0, 1000),
    "required_skills": {
        "type": "array",
        "maxItems": 10,
        "items": _object({
            "name": _string(1, 100),
            "importance": {"type": "string", "enum": ["must-have", "nice-to-have"]},
            "evidence": _string(0, 300),
        }),
    },
    "technical_competencies": _string_list(0, 8, 200),
    "behavioural_competencies": _string_list(0, 8, 200),
    "interview_topics": _string_list(0, 10, 120),
    "likely_questions": _string_list(0, 8, 400),
    "prep_plan": {
        "type": "array",
        "maxItems": 5,
        "items": _object({"step": _string(1, 100), "focus": _string(1, 160), "action": _string(1, 400)}),
    },
})

GENERATED_QUESTION_SCHEMA = _object({
    "question": _string(10, 600),
    "topic": _string(1, 80),
    "category": _CATEGORY,
    "difficulty": _DIFFICULTY,
    "expected_answer_points": _string_list(2, 6, 300),
    "follow_up_questions": _string_list(1, 3, 300),
    "hint": _string(0, 300),
})

QUESTION_SET_SCHEMA = _object({
    "questions": {"type": "array", "minItems": 1, "maxItems": 10, "items": GENERATED_QUESTION_SCHEMA},
})

ANSWER_EVALUATION_SCHEMA = EVALUATION_MODEL_SCHEMA

FOLLOWUP_SCHEMA = _object({
    "decision": {"type": "string", "enum": ["follow_up", "new_topic"]},
    "rationale": _string(5, 400),
    "next_question": _string(10, 600),
    "topic": _string(1, 80),
    "category": _CATEGORY,
    "expected_answer_points": _string_list(1, 6, 300),
})

SUMMARY_SCHEMA = _object({
    "overall_score": _SCORE,
    "overall_evaluation": _string(20, 1500),
    "readiness": {"type": "string", "enum": ["ready", "nearly ready", "needs development", "not yet ready"]},
    "competency_scores": {
        "type": "array",
        "minItems": 2,
        "maxItems": 8,
        "items": _object({"competency": _string(1, 100), "score": _SCORE, "comment": _string(1, 400)}),
    },
    "strengths": _string_list(0, 5),
    "knowledge_gaps": _string_list(0, 6),
    "learning_plan": {
        "type": "array",
        "minItems": 2,
        "maxItems": 6,
        "items": _object({"focus": _string(1, 120), "action": _string(5, 500), "timeframe": _string(1, 60)}),
    },
})

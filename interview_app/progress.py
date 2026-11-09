"""Session progress for the Home dashboard.

Aggregates what the user did in this browser session: Interview chat turns (from the LangGraph
state) and Practice room answers. Nothing is persisted; the dashboard says so.
"""

import statistics
from dataclasses import dataclass, field

LEVELS = ("Easy", "Medium", "Hard")
SKILLS = (
    ("technical_accuracy", "Technical accuracy"),
    ("communication_skills", "Communication"),
    ("problem_solving", "Problem-solving"),
)


@dataclass
class Progress:
    interviews_completed: int = 0
    interviews_in_progress: int = 0
    questions_answered: int = 0
    average_score: float | None = None
    highest_level: str | None = None
    skills: dict[str, float | None] = field(default_factory=dict)
    skill_samples: int = 0
    recent: list[dict] = field(default_factory=list)

    @property
    def has_activity(self) -> bool:
        return self.questions_answered > 0 or self.interviews_in_progress > 0

    @property
    def strongest_skill(self) -> str | None:
        scored = {key: value for key, value in self.skills.items() if value is not None}
        return max(scored, key=scored.get) if scored else None

    @property
    def weakest_skill(self) -> str | None:
        scored = {key: value for key, value in self.skills.items() if value is not None}
        return min(scored, key=scored.get) if len(scored) > 1 else None


def summarize(chat_states: list[dict], practice_history: list[dict], recent_limit: int = 5) -> Progress:
    """Build the dashboard figures from chat interview states and practice-room answers."""
    turns = [turn for state in chat_states for turn in state.get("turns", [])]
    activity: list[dict] = []
    for state in chat_states:
        role = state.get("profile", {}).get("role", "")
        for turn in state.get("turns", []):
            activity.append({"source": "Interview chat", "role": role, "question": turn["question"],
                             "score": turn["overall_score"], "difficulty": turn["difficulty"]})
    for item in practice_history:
        activity.append({"source": "Practice room", "role": item.get("role", ""), "question": item["question"],
                         "score": item["score"], "difficulty": item.get("difficulty", "")})

    scores = [item["score"] for item in activity]
    levels = [turn["difficulty"] for turn in turns] + [item.get("difficulty") for item in practice_history]
    levels = [level for level in levels if level in LEVELS]
    skills = {key: (round(statistics.mean(turn[key] for turn in turns), 1) if turns else None) for key, _ in SKILLS}
    return Progress(
        interviews_completed=sum(state.get("status") == "finished" for state in chat_states),
        interviews_in_progress=sum(state.get("status") in ("awaiting_answer", "needs_question") for state in chat_states),
        questions_answered=len(activity),
        average_score=round(statistics.mean(scores), 1) if scores else None,
        highest_level=max(levels, key=LEVELS.index) if levels else None,
        skills=skills,
        skill_samples=len(turns),
        recent=list(reversed(activity))[:recent_limit],
    )

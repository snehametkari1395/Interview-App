"""LangGraph workflow for the conversational AI interviewer.

Graph (one invocation per user action; state is checkpointed per interview thread):

    START -> route
      route: finish requested or question limit reached -> summarize -> END
             a question is still needed                -> plan_next -> END
             a message is pending                      -> triage -> (END | evaluate -> adapt -> (summarize | plan_next)) -> END
             nothing asked yet                         -> opening -> END

- opening   : chain B (+ vector de-duplication) generates the first question.
- triage    : defensive prompt. Off-topic requests, clarifications, and manipulation attempts get a polite
              in-persona reply and are not scored; only genuine answers continue.
- evaluate  : chain C scores the latest answer (structured Format 2 evaluation, few-shot prompt).
- adapt     : deterministic. Records the turn, updates compact memory and the difficulty.
- plan_next : chain D chooses a follow-up or a new topic; new questions are checked for duplicates.
- summarize : chain E writes the debrief and learning plan.

Context management: no node sends the full transcript. Chain D receives the latest turn, the one
before it (truncated), one-line memories of older turns, and topics covered; chain E receives only
compact per-turn records. The transcript shown in the UI is stored in state but never sent.
"""

from dataclasses import asdict, dataclass, replace
from typing import Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from interview_app.catalog import PrepProfile
from interview_app.chains.base import ChainOutput
from interview_app.chains.llm import ModelSpec
from interview_app.chains.workflows import evaluation_chain, followup_chain, generate_unique_questions, summary_chain, triage_chain
from interview_app.vectorstore import QuestionMemory, Thresholds

LEVELS = ("Easy", "Medium", "Hard")
MAX_ANSWER_IN_CONTEXT = 2000
MAX_PREVIOUS_ANSWER = 600
MAX_CONSECUTIVE_FOLLOW_UPS = 2


class InterviewState(TypedDict, total=False):
    profile: dict
    focus: str
    topic_hint: str
    company: str
    job_context: dict | None
    max_questions: int
    difficulty: str
    difficulty_path: list[str]
    current: dict | None
    pending_answer: str
    last_answer_full: str
    pending_flags: list[str]
    finish_requested: bool
    turns: list[dict]
    memory_lines: list[str]
    topics_covered: list[str]
    asked: list[str]
    last_evaluation: dict | None
    last_triage: dict | None
    last_decision: dict | None
    summary: dict | None
    status: str  # awaiting_answer | needs_question | finished
    transcript: list[dict]
    usage: list[dict]


@dataclass
class Dependencies:
    """Non-serialisable collaborators, passed as LangGraph run context (never checkpointed)."""

    spec: ModelSpec
    memory: QuestionMemory
    thresholds: Thresholds


def next_difficulty(current: str, history: list[tuple[str, int]]) -> str:
    """Deterministic adaptation from scores earned at the current level.

    Down one level after a score of 2 or less; up one level after two consecutive scores of 4 or more
    at the current level; otherwise unchanged.
    """
    at_level = [score for level, score in history if level == current]
    index = LEVELS.index(current)
    if at_level and at_level[-1] <= 2 and index > 0:
        return LEVELS[index - 1]
    if len(at_level) >= 2 and at_level[-1] >= 4 and at_level[-2] >= 4 and index < len(LEVELS) - 1:
        return LEVELS[index + 1]
    return current


def consecutive_follow_ups(turns: list[dict]) -> int:
    count = 0
    for turn in reversed(turns):
        if turn.get("source") != "follow_up":
            break
        count += 1
    return count


def memory_line(number: int, turn: dict) -> str:
    gaps = turn["missing_concepts"][:2] or turn["weaknesses"][:1]
    return f"Q{number} [{turn['difficulty']}] {turn['topic']}: {turn['overall_score']}/5" + (f"; gaps: {'; '.join(gaps)}" if gaps else "")


def _profile(state: InterviewState, difficulty: str | None = None) -> PrepProfile:
    profile = PrepProfile(**state["profile"])
    return replace(profile, difficulty=difficulty or state.get("difficulty", profile.difficulty)).validated()


def _record(state: InterviewState, output: ChainOutput) -> list[dict]:
    return [*state.get("usage", []), output.usage_record()]


def _say(state: InterviewState, role: str, content: str, **meta: Any) -> list[dict]:
    return [*state.get("transcript", []), {"role": role, "content": content, **meta}]


# -- nodes --------------------------------------------------------------------

def opening(state: InterviewState, runtime: Runtime[Dependencies]) -> dict:
    deps = runtime.context
    profile = _profile(state)
    generated = generate_unique_questions(
        deps.spec, profile, count=1, memory=deps.memory, thresholds=deps.thresholds,
        focus=state.get("focus", "Balanced"), topic_hint=state.get("topic_hint", ""),
        job_context=state.get("job_context"), company=state.get("company", ""), source="interview chat",
    )
    if not generated.accepted:
        raise RuntimeError("Could not generate a non-duplicate opening question. Lower the duplicate threshold or change the topic.")
    question = generated.accepted[0]
    usage = state.get("usage", []) + [output.usage_record() for output in generated.outputs]
    current = {
        "question": question["question"], "topic": question["topic"], "category": question["category"],
        "difficulty": profile.difficulty, "expected_answer_points": question["expected_answer_points"],
        "novelty": question["novelty"], "source": "opening",
    }
    return {
        "current": current,
        "asked": [*state.get("asked", []), current["question"]],
        "difficulty_path": [*state.get("difficulty_path", []), profile.difficulty],
        "status": "awaiting_answer",
        "usage": usage,
        "transcript": _say(state, "assistant", current["question"], kind="question", topic=current["topic"],
                           difficulty=current["difficulty"], novelty=current["novelty"]),
    }


def evaluate(state: InterviewState, runtime: Runtime[Dependencies]) -> dict:
    deps = runtime.context
    current = state["current"]
    profile = _profile(state, current["difficulty"])
    payload = {
        "interview_question": current["question"],
        "candidate_answer": state["pending_answer"],
        "expected_answer_points": current.get("expected_answer_points", []),
    }
    if state.get("job_context"):
        payload["job_context"] = state["job_context"]
    output = evaluation_chain(deps.spec, profile).invoke(payload)
    return {"last_evaluation": output.data, "usage": _record(state, output)}


def adapt(state: InterviewState) -> dict:
    """Deterministic bookkeeping: record the turn, compact memory, adapt difficulty."""
    current, evaluation, answer = state["current"], state["last_evaluation"], state["pending_answer"]
    turn = {
        "question": current["question"], "topic": current["topic"], "difficulty": current["difficulty"],
        "source": current.get("source", ""), "answer_excerpt": answer[:MAX_PREVIOUS_ANSWER],
        "overall_score": evaluation["overall_score"],
        "technical_accuracy": evaluation["technical_accuracy"]["score"],
        "communication_skills": evaluation["communication_skills"]["score"],
        "problem_solving": evaluation["problem_solving"]["score"],
        "strengths": evaluation["strengths"][:3], "weaknesses": evaluation["weaknesses"][:3],
        "missing_concepts": evaluation["missing_concepts"][:4], "summary": evaluation["summary"],
    }
    turns = [*state.get("turns", []), turn]
    history = [(item["difficulty"], item["overall_score"]) for item in turns]
    difficulty = next_difficulty(state.get("difficulty", current["difficulty"]), history)
    topics = list(dict.fromkeys([*state.get("topics_covered", []), current["topic"]]))
    return {
        "turns": turns,
        "memory_lines": [memory_line(number, item) for number, item in enumerate(turns, start=1)],
        "topics_covered": topics,
        "difficulty": difficulty,
        "pending_answer": "",
        "pending_flags": [],
        "last_answer_full": answer[:MAX_ANSWER_IN_CONTEXT],
        "status": "needs_question",
    }


def plan_next(state: InterviewState, runtime: Runtime[Dependencies]) -> dict:
    deps = runtime.context
    profile = _profile(state)
    turns = state["turns"]
    latest = turns[-1]
    payload = {
        "latest_turn": {
            "question": latest["question"], "topic": latest["topic"], "difficulty": latest["difficulty"],
            "answer": state.get("last_answer_full", latest["answer_excerpt"])[:MAX_ANSWER_IN_CONTEXT],
            "evaluation": {key: latest[key] for key in ("overall_score", "summary", "weaknesses", "missing_concepts")},
        },
        "recent_turns": [
            {"question": item["question"], "answer_excerpt": item["answer_excerpt"], "overall_score": item["overall_score"]}
            for item in turns[-2:-1]
        ],
        "memory": state.get("memory_lines", [])[:-2],
        "topics_covered": state.get("topics_covered", []),
        "target_difficulty": profile.difficulty,
        "avoid": state.get("asked", [])[-12:],
    }
    must_change_topic = consecutive_follow_ups(turns) >= MAX_CONSECUTIVE_FOLLOW_UPS
    if must_change_topic:
        payload["must_change_topic"] = True  # deterministic rule; the model cannot count reliably
    usage = list(state.get("usage", []))
    decision = None
    for _attempt in range(3):
        output = followup_chain(deps.spec, profile).invoke(payload)
        usage.append(output.usage_record())
        decision = output.data
        check = deps.memory.check(decision["next_question"], deps.thresholds, domain=profile.domain, extra_texts=state.get("asked", []))
        decision["novelty"] = check.label
        # Follow-ups may be similar to earlier questions (same topic), but never near-duplicates.
        ignored_rule = must_change_topic and decision["decision"] == "follow_up"
        if check.label != "duplicate" and not ignored_rule:
            break
        payload["avoid"] = [*payload["avoid"], decision["next_question"]][-14:]
        if ignored_rule:
            payload["must_change_topic"] = True
    if decision["decision"] == "new_topic":
        deps.memory.add(decision["next_question"], {
            "domain": profile.domain, "role": profile.role, "company": state.get("company", ""),
            "difficulty": profile.difficulty, "category": decision["category"], "topic": decision["topic"], "source": "interview chat",
        })
    current = {
        "question": decision["next_question"], "topic": decision["topic"], "category": decision["category"],
        "difficulty": profile.difficulty, "expected_answer_points": decision["expected_answer_points"],
        "novelty": decision["novelty"], "source": decision["decision"],
    }
    return {
        "current": current,
        "last_decision": decision,
        "asked": [*state.get("asked", []), current["question"]],
        "difficulty_path": [*state.get("difficulty_path", []), profile.difficulty],
        "status": "awaiting_answer",
        "usage": usage,
    }


def summarize(state: InterviewState, runtime: Runtime[Dependencies]) -> dict:
    deps = runtime.context
    turns = state.get("turns", [])
    if not turns:
        return {"status": "finished", "summary": None, "finish_requested": False}
    compact = [{key: turn[key] for key in ("question", "topic", "difficulty", "overall_score", "technical_accuracy",
                                           "communication_skills", "problem_solving", "strengths", "weaknesses", "missing_concepts")}
               for turn in turns]
    output = summary_chain(deps.spec, _profile(state)).invoke({"turns": compact, "difficulty_path": state.get("difficulty_path", [])})
    return {"summary": output.data, "status": "finished", "finish_requested": False, "usage": _record(state, output)}


def triage(state: InterviewState, runtime: Runtime[Dependencies]) -> dict:
    """Defensive gate: only genuine answers are scored; everything else gets a polite in-persona reply."""
    deps = runtime.context
    payload = {"current_question": state["current"]["question"], "candidate_message": state["pending_answer"]}
    output = triage_chain(deps.spec, _profile(state)).invoke(payload)
    usage = _record(state, output)
    if output.data["category"] == "answer":
        return {"last_triage": output.data, "usage": usage}
    return {"last_triage": output.data, "usage": usage, "pending_answer": "", "pending_flags": [], "status": "awaiting_answer"}


def route_after_triage(state: InterviewState) -> str:
    return "evaluate" if state.get("pending_answer") else END


# -- routing ------------------------------------------------------------------

def route_start(state: InterviewState) -> str:
    if state.get("status") == "finished":
        return END
    if state.get("finish_requested") and not state.get("pending_answer"):
        return "summarize"
    if state.get("pending_answer"):
        return "triage"
    if state.get("status") == "needs_question":
        return "summarize" if len(state.get("turns", [])) >= state.get("max_questions", 5) else "plan_next"
    if not state.get("current"):
        return "opening"
    return END


def route_after_adapt(state: InterviewState) -> str:
    if state.get("finish_requested") or len(state.get("turns", [])) >= state.get("max_questions", 5):
        return "summarize"
    return "plan_next"


def build_interview_graph(checkpointer=None):
    graph = StateGraph(InterviewState, context_schema=Dependencies)
    graph.add_node("opening", opening)
    graph.add_node("triage", triage)
    graph.add_node("evaluate", evaluate)
    graph.add_node("adapt", adapt)
    graph.add_node("plan_next", plan_next)
    graph.add_node("summarize", summarize)
    graph.add_conditional_edges(START, route_start, ["opening", "triage", "plan_next", "summarize", END])
    graph.add_conditional_edges("triage", route_after_triage, ["evaluate", END])
    graph.add_edge("opening", END)
    graph.add_edge("evaluate", "adapt")
    graph.add_conditional_edges("adapt", route_after_adapt, ["summarize", "plan_next"])
    graph.add_edge("plan_next", END)
    graph.add_edge("summarize", END)
    return graph.compile(checkpointer=checkpointer or InMemorySaver())


def initial_state(profile: PrepProfile, *, focus: str, topic_hint: str, company: str, job_context: dict | None, max_questions: int) -> InterviewState:
    return {
        "profile": asdict(profile.validated()), "focus": focus, "topic_hint": topic_hint, "company": company,
        "job_context": job_context, "max_questions": max_questions, "difficulty": profile.difficulty,
        "difficulty_path": [], "current": None, "pending_answer": "", "pending_flags": [], "finish_requested": False,
        "turns": [], "memory_lines": [], "topics_covered": [], "asked": [], "last_evaluation": None, "last_triage": None,
        "last_decision": None, "summary": None, "status": "new", "transcript": [], "usage": [],
    }


def run_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}

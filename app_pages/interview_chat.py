import json
import queue
import threading
import uuid
from datetime import datetime

import streamlit as st

from interview_app.catalog import DOMAINS, PrepProfile
from interview_app.chains.interview_graph import Dependencies, build_interview_graph, initial_state, run_config
from interview_app.chains.llm import spec_from_session
from interview_app.chains.workflows import interviewer_reply, job_context_from
from interview_app.licensing import classify
from interview_app.openrouter import active_model, describe_error, get_api_key, reserve_calls
from interview_app.pricing import format_usd
from interview_app.security_guard import FLAG_DESCRIPTIONS, GuardError, guard_untrusted_input
from interview_app.services import current_thresholds, get_question_memory, record_chain_usage
from interview_app.ui import profile_inputs, remember_profile, render_sidebar, require_api_key, show_error

MAX_ANSWER_CHARS = 6000
MAX_HINT_CHARS = 200
MAX_COMPANY_CHARS = 120
QUESTION_ICON = ":material/record_voice_over:"
CANDIDATE_ICON = ":material/person:"

render_sidebar()

# ---------------------------------------------------------------------------
# Session-scoped graph, checkpointer, and interview list
# ---------------------------------------------------------------------------
if "chat_graph" not in st.session_state:
    st.session_state.chat_graph = build_interview_graph()  # InMemorySaver: per browser session, never on disk
    st.session_state.chat_threads = []
    st.session_state.chat_active = None
graph = st.session_state.chat_graph


def thread_state(thread_id: str) -> dict:
    return graph.get_state(run_config(thread_id)).values


def active_thread() -> dict | None:
    return next((item for item in st.session_state.chat_threads if item["id"] == st.session_state.chat_active), None)


def log_new_usage(thread: dict, state: dict, extra: list[dict] | None = None) -> None:
    usage = state.get("usage", [])
    record_chain_usage(usage[thread.get("logged", 0):] + (extra or []))
    thread["logged"] = len(usage)
    thread["extra_cost"] = thread.get("extra_cost", 0.0) + sum(item.get("cost_usd") or 0 for item in (extra or []))


def run_graph(thread: dict, update: dict | None, deps: Dependencies, *, stream_feedback: bool) -> tuple[str, list[dict]]:
    """Run one graph step in a worker thread; stream the interviewer's feedback as soon as scoring finishes.

    The answered question and profile are captured before the run, because the worker may already
    have moved ``current`` to the next question by the time the feedback starts streaming.

    Returns (feedback text, extra usage records). Raises the worker's exception, if any.
    """
    config = run_config(thread["id"])
    before = thread_state(thread["id"])
    answered = before.get("current") or {}
    profile = PrepProfile(**{**before["profile"], "difficulty": answered.get("difficulty", before["profile"]["difficulty"])})
    events: queue.Queue = queue.Queue()

    def worker():
        try:
            for chunk in graph.stream(update, config, context=deps, stream_mode="updates"):
                events.put(("update", chunk))
            events.put(("done", None))
        except Exception as error:  # surfaced in the main thread
            events.put(("error", error))

    threading.Thread(target=worker, daemon=True).start()
    feedback, extra, failure = "", [], None
    status = st.status("Evaluating your answer..." if stream_feedback else "Preparing the next question...", expanded=False)
    while True:
        kind, payload = events.get()
        if kind == "error":
            failure = payload
            break
        if kind == "done":
            break
        node = next(iter(payload))
        if node == "evaluate" and stream_feedback:
            evaluation = payload["evaluate"]["last_evaluation"]
            status.update(label=f"Scored {evaluation['overall_score']}/5 · choosing the next question...", state="running")
            try:
                reply = interviewer_reply(deps.spec, profile, answered.get("question", ""), evaluation)
                feedback = st.write_stream(reply)
                if reply.output:
                    extra.append(reply.output.usage_record())
            except Exception as error:  # the reply is cosmetic; fall back to the structured evaluation
                feedback = evaluation["summary"] + (f" Tip: {evaluation['improvement_suggestions'][0]}" if evaluation["improvement_suggestions"] else "")
                st.write(feedback)
                st.caption(f"Streaming unavailable ({describe_error(error)}); showing the evaluation summary.")
        elif node == "summarize":
            status.update(label="Writing your interview summary...", state="running")
    if failure is not None:
        status.update(label="Something went wrong", state="error")
        raise failure
    status.update(label="Done", state="complete")
    return feedback, extra


def append_transcript(thread: dict, entries: list[dict]) -> None:
    config = run_config(thread["id"])
    graph.update_state(config, {"transcript": [*thread_state(thread["id"]).get("transcript", []), *entries]})


def dependencies() -> Dependencies:
    return Dependencies(spec=spec_from_session(), memory=get_question_memory(), thresholds=current_thresholds())


# ---------------------------------------------------------------------------
# Header and interview list
# ---------------------------------------------------------------------------
st.badge("AI INTERVIEWER", icon=":material/forum:", color="violet")
st.title("Interview chat", icon=":material/forum:")
model = active_model()
licence = classify(model)
st.caption(f"Model `{model}` · {licence.category} ({licence.licence}). Each turn: evaluate (chain C), adapt difficulty, follow up (chain D), streamed feedback.")
if not licence.is_open_weight:
    st.info("The advanced features default to an open-weight model. You are using a proprietary model; choose an open-weight one in Model settings if your account allows it.", icon=":material/info:")

threads = st.session_state.chat_threads
toolbar = st.container(horizontal=True, vertical_alignment="bottom")
if threads:
    labels = {item["id"]: f"{item['label']} · {item['created']}" for item in threads}
    choice = toolbar.selectbox(
        "Your interviews this session",
        [item["id"] for item in threads],
        index=next((i for i, item in enumerate(threads) if item["id"] == st.session_state.chat_active), 0),
        format_func=labels.get,
        help="Switch between interviews to resume one where you left off.",
    )
    if choice != st.session_state.chat_active and st.session_state.chat_active is not None:
        st.session_state.chat_active = choice
        st.rerun()
if toolbar.button("New interview", icon=":material/add_comment:"):
    st.session_state.chat_active = None
    st.rerun()
if active_thread():
    with toolbar.popover("Clear history", icon=":material/delete:"):
        st.write("Delete this interview and its conversation history from this session?")
        if st.button("Delete interview", type="primary", key="confirm_clear"):
            graph.checkpointer.delete_thread(st.session_state.chat_active)
            st.session_state.chat_threads = [item for item in threads if item["id"] != st.session_state.chat_active]
            st.session_state.chat_active = None
            st.rerun()

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
thread = active_thread()
if thread is None:
    left, right = st.columns([1.3, 1], gap="large")
    with left, st.container(border=True):
        st.subheader("Start an interview")
        profile = profile_inputs("chat")
        focus = st.segmented_control("Question focus", DOMAINS[profile.domain].focuses, default="Balanced", required=True, key=f"chat_focus_{profile.domain}")
        topic_hint = st.text_input("Topic (optional)", max_chars=MAX_HINT_CHARS, placeholder="e.g. Python, SQL window functions, stakeholder management")
        company = st.text_input("Company (optional)", max_chars=MAX_COMPANY_CHARS, help="Stored with generated questions so you can filter the question memory.")
        analysis = st.session_state.get("jd_chain_analysis")
        use_jd = False
        if analysis and analysis.get("is_job_description"):
            use_jd = st.checkbox(f"Ground questions in my job description ({analysis.get('role_title') or 'analysed role'})", value=True)
        count = st.select_slider("Questions in this interview", options=[3, 4, 5, 6, 8, 10], value=5)
        start = st.button("Start interview", type="primary", width="stretch", icon=":material/play_arrow:", disabled=not get_api_key())
    with right, st.container(border=True):
        st.subheader("How it works")
        st.markdown(
            ":material/looks_one: The interviewer asks a question.\n\n"
            ":material/looks_two: You answer in your own words.\n\n"
            ":material/looks_3: Your answer is scored on accuracy, communication, and problem-solving, and you get spoken-style feedback.\n\n"
            ":material/looks_4: The next question follows up on gaps or moves to a new topic. Difficulty rises after two strong answers and eases after a weak one.\n\n"
            ":material/looks_5: At the end you get a summary, knowledge gaps, and a learning plan."
        )
        st.caption("Only compact notes about earlier turns are sent to the model, not the full conversation. Generated questions are stored to avoid repeats; your answers are not.")
    if start and require_api_key("the interview chat"):
        try:
            clean_hint = guard_untrusted_input(topic_hint, "topic", MAX_HINT_CHARS)[0] if topic_hint.strip() else ""
            clean_company = guard_untrusted_input(company, "company", MAX_COMPANY_CHARS)[0] if company.strip() else ""
            reserve_calls(1)
            new = {"id": uuid.uuid4().hex[:12], "label": f"{profile.role} · {profile.difficulty}", "created": datetime.now().strftime("%H:%M"), "logged": 0}
            state = initial_state(profile, focus=focus, topic_hint=clean_hint, company=clean_company,
                                  job_context=job_context_from(analysis) if use_jd else None, max_questions=count)
            with st.spinner("The interviewer is preparing the first question..."):
                result = graph.invoke(state, run_config(new["id"]), context=dependencies())
            remember_profile(profile)
            threads.append(new)
            st.session_state.chat_active = new["id"]
            log_new_usage(new, result)
            st.rerun()
        except GuardError as error:
            st.error(str(error))
        except Exception as error:
            show_error(error, "start the interview")
    st.stop()

# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------
state = thread_state(thread["id"])
chat_column, board_column = st.columns([2.2, 1], gap="large")

with board_column, st.container(border=True):
    turns = state.get("turns", [])
    st.markdown("**Scoreboard**")
    metrics = st.columns(2)
    metrics[0].metric("Answered", f"{len(turns)} / {state.get('max_questions', 0)}")
    metrics[1].metric("Average", f"{sum(t['overall_score'] for t in turns) / len(turns):.1f} / 5" if turns else "—")
    metrics = st.columns(2)
    metrics[0].metric("Difficulty", state.get("difficulty", "—"))
    cost = sum(item.get("cost_usd") or 0 for item in state.get("usage", [])) + thread.get("extra_cost", 0.0)
    metrics[1].metric("Cost", format_usd(cost))
    if turns:
        st.dataframe(
            [{"#": i, "Topic": t["topic"], "Level": t["difficulty"], "Score": t["overall_score"], "Tech": t["technical_accuracy"],
              "Comm.": t["communication_skills"], "Solve": t["problem_solving"]} for i, t in enumerate(turns, start=1)],
            hide_index=True,
            column_config={"Score": st.column_config.ProgressColumn(min_value=0, max_value=5, format="%d")},
            alt="Score for each answered question",
        )
        st.caption("Path: " + " → ".join(state.get("difficulty_path", [])))
    if state.get("status") in ("awaiting_answer", "needs_question") and turns:
        if st.button("End interview and summarise", icon=":material/flag:", width="stretch"):
            try:
                reserve_calls(1)
                with st.spinner("Writing your interview summary..."):
                    result = graph.invoke({"finish_requested": True}, run_config(thread["id"]), context=dependencies())
                log_new_usage(thread, result)
                st.rerun()
            except Exception as error:
                show_error(error, "summarise the interview")

with chat_column:
    for message in state.get("transcript", []):
        avatar = CANDIDATE_ICON if message["role"] == "user" else QUESTION_ICON
        with st.chat_message(message["role"], avatar=avatar):
            if message.get("kind") == "question":
                st.caption(f"{message.get('difficulty', '')} · {message.get('topic', '')}" + (f" · {message['novelty']} question" if message.get("novelty") else ""))
                st.markdown(f"**{message['content']}**")
            elif message.get("kind") == "feedback":
                st.write(message["content"])
                st.caption(f"Score {message['score']}/5 · technical {message['technical']}/5 · communication {message['communication']}/5 · problem-solving {message['problem_solving']}/5")
            else:
                st.write(message["content"])
                if message.get("flags"):
                    st.caption("Treated as plain content: " + "; ".join(FLAG_DESCRIPTIONS.get(flag, flag) for flag in message["flags"]))

    summary = state.get("summary")
    if state.get("status") == "finished" and summary:
        with st.container(border=True):
            st.subheader("Interview summary")
            row = st.columns(3)
            row[0].metric("Overall", f"{summary['overall_score']} / 5")
            row[1].metric("Readiness", summary["readiness"].capitalize())
            row[2].metric("Questions", len(state.get("turns", [])))
            st.write(summary["overall_evaluation"])
            st.dataframe(summary["competency_scores"], hide_index=True,
                         column_config={"score": st.column_config.ProgressColumn("Score", min_value=0, max_value=5, format="%d")},
                         alt="Competency scores")
            left, right = st.columns(2)
            with left:
                st.markdown(":green[**Strengths**]")
                for item in summary["strengths"]:
                    st.markdown(f"- {item}")
            with right:
                st.markdown(":red[**Knowledge gaps**]")
                for item in summary["knowledge_gaps"]:
                    st.markdown(f"- {item}")
            st.markdown("**Your learning plan**")
            for index, step in enumerate(summary["learning_plan"], start=1):
                st.markdown(f"{index}. **{step['focus']}** ({step['timeframe']}): {step['action']}")
            export = {"profile": state["profile"], "turns": state["turns"], "difficulty_path": state["difficulty_path"], "summary": summary}
            st.download_button("Download interview report (JSON)", json.dumps(export, indent=2, ensure_ascii=False),
                               "interview-report.json", "application/json", icon=":material/download:", on_click="ignore")

    needs_retry = bool(state.get("pending_answer")) or state.get("status") == "needs_question" or (state.get("finish_requested") and state.get("status") != "finished")
    if needs_retry:
        st.warning("The last step did not finish. Your answer is saved; you can retry.", icon=":material/replay:")
        if st.button("Retry", type="primary", icon=":material/replay:"):
            deps = dependencies()
            try:
                reserve_calls(3)
                with st.chat_message("assistant", avatar=QUESTION_ICON):
                    feedback, extra = run_graph(thread, None, deps, stream_feedback=bool(state.get("pending_answer")))
                after = thread_state(thread["id"])
                entries = []
                if feedback and after.get("turns"):
                    turn = after["turns"][-1]
                    entries.append({"role": "assistant", "kind": "feedback", "content": feedback, "score": turn["overall_score"],
                                    "technical": turn["technical_accuracy"], "communication": turn["communication_skills"], "problem_solving": turn["problem_solving"]})
                if after.get("status") == "awaiting_answer":
                    current = after["current"]
                    entries.append({"role": "assistant", "kind": "question", "content": current["question"], "topic": current["topic"],
                                    "difficulty": current["difficulty"], "novelty": current.get("novelty")})
                append_transcript(thread, entries)
                log_new_usage(thread, after, extra)
                st.rerun()
            except Exception as error:
                show_error(error, "continue the interview")

answer = st.chat_input("Type your answer...", max_chars=MAX_ANSWER_CHARS, disabled=state.get("status") != "awaiting_answer" or needs_retry)
if answer:
    try:
        clean, assessment = guard_untrusted_input(answer, "answer", MAX_ANSWER_CHARS)
    except GuardError as error:
        st.error(str(error))
        st.stop()
    deps = dependencies()
    with chat_column:
        with st.chat_message("user", avatar=CANDIDATE_ICON):
            st.write(clean)
        try:
            reserve_calls(3)
            user_entry = {"role": "user", "content": clean, "flags": list(assessment.flags)}
            update = {"pending_answer": clean, "pending_flags": list(assessment.flags), "transcript": [*state.get("transcript", []), user_entry]}
            with st.chat_message("assistant", avatar=QUESTION_ICON):
                feedback, extra = run_graph(thread, update, deps, stream_feedback=True)
            after = thread_state(thread["id"])
            turn = after["turns"][-1]
            entries = [{"role": "assistant", "kind": "feedback", "content": feedback, "score": turn["overall_score"],
                        "technical": turn["technical_accuracy"], "communication": turn["communication_skills"], "problem_solving": turn["problem_solving"]}]
            if after.get("status") == "awaiting_answer":
                current = after["current"]
                entries.append({"role": "assistant", "kind": "question", "content": current["question"], "topic": current["topic"],
                                "difficulty": current["difficulty"], "novelty": current.get("novelty")})
            append_transcript(thread, entries)
            log_new_usage(thread, after, extra)
            st.rerun()
        except GuardError as error:
            st.error(str(error))
        except Exception as error:
            show_error(error, "continue the interview")

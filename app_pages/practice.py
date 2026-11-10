import html

import streamlit as st

from interview_app.catalog import DOMAINS, PERSONAS
from interview_app.chains.llm import spec_from_session
from interview_app.chains.workflows import BLOCKED_REPLY, generate_unique_questions, job_context_from, triage_chain
from interview_app.coaching import review_answer
from interview_app.openrouter import describe_error, get_api_key, reserve_calls
from interview_app.services import current_thresholds, get_question_memory, record_chain_usage
from interview_app.pricing import format_usd
from interview_app.question_bank import get_questions
from interview_app.security_guard import FLAG_DESCRIPTIONS, GuardError, assess_input, guard_untrusted_input
from interview_app.ui import profile_inputs, remember_profile, render_sidebar, show_error

st.set_page_config(page_title="Practice room | Interview App", page_icon=":material/code:", layout="wide")

MAX_ANSWER_CHARS = 8000
QUESTION_ICON_PRACTICE = ":material/record_voice_over:"
QUESTION_SOURCES = ["AI-generated", "Curated bank"]
GENERIC_HINT = "Set the context, explain your decision or approach, share the result, and reflect on what you learned."


def reset_session() -> None:
    for key in (
        "practice_questions",
        "practice_index",
        "practice_answers",
        "practice_feedback",
        "practice_mode",
        "practice_role",
        "practice_profile",
        "practice_flags",
        "practice_notice",
    ):
        st.session_state.pop(key, None)


def build_question_set(profile, focus: str, count: int, source: str, use_jd: bool) -> tuple[list[dict], str]:
    """Return (questions, notice). Falls back to the curated bank if generation fails."""
    jd_questions = st.session_state.get("jd_questions", [])
    if use_jd and jd_questions:
        return [{"question": item, "topic": "Job description", "kind": "technical", "hint": ""} for item in jd_questions[:count]], ""
    if source == "AI-generated" and get_api_key():
        try:
            reserve_calls(1)
            article = "an" if profile.role[:1].upper() in "AEIOU" else "a"
            with st.spinner(f"Writing {count} new {profile.difficulty.lower()} questions for {article} {profile.role}..."):
                generated = generate_unique_questions(
                    spec_from_session(), profile, count=count, memory=get_question_memory(), thresholds=current_thresholds(),
                    focus=focus, job_context=job_context_from(st.session_state.get("jd_chain_analysis")), source="practice room",
                )
            record_chain_usage([output.usage_record() for output in generated.outputs])
            questions = [
                {"question": item["question"], "topic": item["topic"], "kind": item["category"], "hint": item["hint"], "novelty": item["novelty"]}
                for item in generated.accepted
            ]
            notice = f"Skipped {len(generated.rejected)} generated question(s) that duplicated earlier ones." if generated.rejected else ""
            if questions:
                return questions, notice
            raise GuardError("Every generated question duplicated an earlier one.")
        except Exception as error:
            notice = f"AI question generation failed ({describe_error(error)}). Using curated questions instead."
    else:
        notice = ""
    questions = get_questions(profile.role, focus, count, domain=profile.domain, difficulty=profile.difficulty)
    if len(questions) < count:
        notice = (notice + " " if notice else "") + f"The curated bank has {len(questions)} questions for this combination."
    return questions, notice


def render_setup() -> None:
    st.badge("INTERVIEW PRACTICE", icon=":material/terminal:", color="green")
    st.title("The interview room", icon=":material/record_voice_over:")
    st.caption("Build a focused round. Get a clear debrief. Turn the next answer into a stronger one.")
    left, right = st.columns([1.35, 1], gap="large")
    with left:
        jd_questions = st.session_state.get("jd_questions", [])
        with st.container(border=True):
            st.subheader("Set up your round")
            profile = profile_inputs("setup")
            focus = st.segmented_control("Question focus", DOMAINS[profile.domain].focuses, default="Balanced", required=True, key=f"setup_focus_{profile.domain}")
            mode = st.segmented_control(
                "Practice format",
                ["Guided coaching", "Mock interview"],
                default="Guided coaching",
                required=True,
            )
            has_key = bool(get_api_key())
            source = st.segmented_control(
                "Question source",
                QUESTION_SOURCES,
                default=QUESTION_SOURCES[0] if has_key else QUESTION_SOURCES[1],
                required=True,
                help="AI-generated questions adapt to your domain, difficulty, and persona. The curated bank works offline.",
            )
            count = st.select_slider("Questions in this round", options=[3, 5, 7, 10], value=5)
            use_jd = False
            if jd_questions:
                use_jd = st.checkbox(f"Use my {len(jd_questions)} job-specific questions", value=True)
            start = st.button("Start interview", type="primary", width="stretch")
        if start:
            questions, notice = build_question_set(profile, focus, count, source, use_jd)
            remember_profile(profile)
            st.session_state.practice_questions = questions
            st.session_state.practice_index = 0
            st.session_state.practice_answers = []
            st.session_state.practice_feedback = None
            st.session_state.practice_flags = ()
            st.session_state.practice_mode = mode
            st.session_state.practice_role = profile.role
            st.session_state.practice_profile = profile
            st.session_state.practice_notice = notice
            st.rerun()
    with right:
        with st.container(border=True):
            st.subheader("Your interview brief")
            st.write("Every round is built around a domain and role, not a generic quiz.")
            st.markdown(":material/looks_one: **Answer** one question at a time")
            st.markdown(":material/looks_two: **Debrief** with a score, criteria, and a sample answer")
            st.markdown(":material/looks_3: **Retry**, or take on the interviewer's follow-up")
            st.divider()
            persona = PERSONAS[st.session_state.get("setup_persona", "Neutral")]
            st.caption(f"**{persona.name} interviewer:** {persona.summary} Personas change tone, never how fairly you are scored.")
            st.caption("Guided coaching includes a structure hint. Mock interview keeps it hidden until after you answer.")
        if not get_api_key():
            st.warning("Add an OpenRouter API key to enable AI questions and feedback.")
        st.page_link(
            "app_pages/job_description.py",
            label="Build a round from a job description",
            icon=":material/description:",
        )


def render_feedback(feedback: dict, persona: str) -> None:
    st.subheader("Answer debrief")
    score_column, verdict_column = st.columns([1, 3], vertical_alignment="center")
    score_column.metric("Answer score", f"{feedback['score']} / 5")
    if feedback["verdict"]:
        verdict_column.write(feedback["verdict"])
    if feedback.get("interviewer_reaction"):
        with st.chat_message("assistant", avatar=":material/record_voice_over:"):
            st.caption(f"{persona} interviewer")
            st.write(feedback["interviewer_reaction"])
    if feedback.get("criteria"):
        with st.container(border=True):
            st.markdown("**How you did on each criterion**")
            for item in feedback["criteria"]:
                st.markdown(f"**{item['name']}** · {item['rating']} / 5")
                st.progress(item["rating"] / 5, text=item["comment"] or None)
    strengths, improvements = st.columns(2)
    with strengths:
        with st.container(border=True, height="stretch"):
            st.markdown("**What landed**")
            for item in feedback["strengths"]:
                st.markdown(f"- {item}")
    with improvements:
        with st.container(border=True, height="stretch"):
            st.markdown("**Your next improvement**")
            for item in feedback["improvements"]:
                st.markdown(f"- {item}")
    if feedback.get("expected_points"):
        with st.expander("What a strong answer covers"):
            for item in feedback["expected_points"]:
                st.markdown(f"- {item}")
    if feedback["answer_steps"]:
        with st.expander("Build a stronger answer, step by step", expanded=True):
            for index, step in enumerate(feedback["answer_steps"], start=1):
                st.markdown(f"**{index}.** {step}")
    if feedback["sample_answer"]:
        with st.expander("Example answer"):
            st.write(feedback["sample_answer"])
    if feedback["follow_up"]:
        st.markdown(f"**A useful follow-up:** {feedback['follow_up']}")


def render_summary(answers: list[dict], profile) -> None:
    st.title("Your session debrief", icon=":material/analytics:")
    scores = [item["feedback"]["score"] for item in answers if item.get("feedback")]
    summary_columns = st.columns(3)
    summary_columns[0].metric("Questions answered", len(answers))
    summary_columns[1].metric(
        "Average answer score",
        f"{sum(scores) / len(scores):.1f} / 5" if scores else "—",
    )
    summary_columns[2].metric("Role", st.session_state.practice_role)
    st.caption(f"{profile.domain} · {profile.label()}")
    if answers:
        with st.expander("Review your answers"):
            for position, item in enumerate(answers, start=1):
                st.markdown(f"**{position}. {item['question']}**")
                st.caption(item["answer"])
                st.markdown(f"Score: {item['feedback']['score']} / 5")
    if st.button("Set up another round", type="primary", icon=":material/refresh:"):
        reset_session()
        st.rerun()


def submit_answer(profile, mode: str, question: dict, index: int, answer: str) -> None:
    try:
        clean_answer, assessment = guard_untrusted_input(answer, "answer", MAX_ANSWER_CHARS)
        reserve_calls(2)
        with st.spinner("Reviewing your answer..."):
            # Defensive triage: off-topic requests and manipulation attempts get a polite reply, not a score.
            verdict = triage_chain(spec_from_session(), profile).invoke(
                {"current_question": question["question"], "candidate_message": clean_answer})
            record_chain_usage([verdict.usage_record()])
            if verdict.data["category"] != "answer":
                st.info(verdict.data["reply"], icon=QUESTION_ICON_PRACTICE)
                return
            result = review_answer(profile, mode, question["question"], clean_answer, input_flags=assessment.flags)
    except GuardError as error:
        if assess_input(answer).blocked:
            st.info(BLOCKED_REPLY, icon=QUESTION_ICON_PRACTICE)
            return
        st.error(str(error))
        return
    except Exception as error:
        show_error(error, "get feedback")
        return

    answers = st.session_state.practice_answers
    attempt = {"answer": clean_answer, "feedback": result}
    if index < len(answers):
        answers[index]["answer"] = clean_answer
        answers[index]["feedback"] = result
        answers[index]["attempts"].append(attempt)
    else:
        answers.append({
            "question": question["question"],
            "answer": clean_answer,
            "feedback": result,
            "attempts": [attempt],
        })
    st.session_state.practice_flags = assessment.flags
    st.session_state.setdefault("practice_history", []).append(  # for the Home dashboard (session only)
        {"question": question["question"], "score": result["score"], "role": profile.role, "difficulty": profile.difficulty})
    st.session_state.practice_feedback = result
    last_call = st.session_state.get("last_call")
    st.session_state.practice_cost = last_call.cost if last_call is not None else None
    st.rerun()


def render_practice() -> None:
    questions = st.session_state.practice_questions
    index = st.session_state.practice_index
    answers = st.session_state.practice_answers
    profile = st.session_state.practice_profile
    total = len(questions)

    if index >= total:
        render_summary(answers, profile)
        return

    mode = st.session_state.practice_mode
    question = questions[index]
    st.title(st.session_state.practice_role, icon=":material/record_voice_over:")
    st.caption(f"{mode} · {profile.domain} · {profile.difficulty} · {profile.persona} interviewer · {profile.depth} responses")
    if st.session_state.get("practice_notice"):
        st.info(st.session_state.practice_notice, icon=":material/info:")
    st.progress(index / total, text=f"Question {index + 1} of {total}")
    with st.container(border=True):
        st.caption(question["topic"] + (f" · {question['novelty']} question" if question.get("novelty") else ""))
        st.subheader(html.escape(question["question"]))

    feedback = st.session_state.practice_feedback
    if feedback is None:
        if mode == "Guided coaching":
            with st.expander("Before you answer: a quick structure"):
                st.write(question.get("hint") or GENERIC_HINT)
        answer = st.text_area(
            "Your answer",
            height=220,
            max_chars=MAX_ANSWER_CHARS,
            placeholder="Take a breath, then write it as you would say it aloud.",
            key=f"answer_{index}",
        )
        if st.button("Get feedback", type="primary", disabled=not bool(get_api_key())):
            submit_answer(profile, mode, question, index, answer)
    else:
        flags = st.session_state.get("practice_flags") or ()
        if flags:
            st.warning(
                "Parts of your answer looked like instructions to the AI, so they were treated as plain content: "
                + "; ".join(FLAG_DESCRIPTIONS.get(flag, flag) for flag in flags)
                + ".",
                icon=":material/shield:",
            )
        render_feedback(feedback, profile.persona)
        cost = st.session_state.get("practice_cost")
        if cost is not None:
            st.caption(f"Actual cost of this feedback: {format_usd(cost.best_total)} · {cost.input_tokens:,} input + {cost.output_tokens:,} output tokens · `{cost.model}`")
        actions = st.container(horizontal=True)
        if actions.button("Retry this answer", icon=":material/replay:"):
            st.session_state[f"answer_{index}"] = ""
            st.session_state.practice_feedback = None
            st.rerun()
        if feedback.get("follow_up") and not question.get("follow_up_added"):
            if actions.button("Answer the follow-up", icon=":material/subdirectory_arrow_right:", help="Adds the interviewer's follow-up as the next question."):
                question["follow_up_added"] = True
                questions.insert(index + 1, {"question": feedback["follow_up"], "topic": "Follow-up", "kind": question.get("kind", "technical"), "hint": ""})
                st.session_state.practice_index += 1
                st.session_state.practice_feedback = None
                st.rerun()
        if actions.button("Next question →", type="primary"):
            st.session_state.practice_index += 1
            st.session_state.practice_feedback = None
            st.rerun()

    if st.button("End session"):
        st.session_state.practice_index = total
        st.rerun()


render_sidebar()

if "practice_questions" in st.session_state and "practice_profile" in st.session_state:
    render_practice()
else:
    render_setup()

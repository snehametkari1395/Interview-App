import html

import streamlit as st

from interview_app.coaching import review_answer
from interview_app.openrouter import get_api_key
from interview_app.question_bank import FOCUSES, ROLES, get_questions
from interview_app.security_guard import GuardError, validate_text

st.set_page_config(page_title="Fieldnotes | Interview practice", page_icon=":material/code:", layout="wide")

def reset_session() -> None:
    for key in (
        "practice_questions",
        "practice_index",
        "practice_answers",
        "practice_feedback",
        "practice_mode",
        "practice_role",
        "practice_interviewer",
        "practice_pressure",
    ):
        st.session_state.pop(key, None)


def render_setup() -> None:
    st.badge("INTERVIEW PRACTICE", icon=":material/terminal:", color="blue")
    st.title("The interview room", icon=":material/record_voice_over:")
    st.caption("Build a focused round. Get a clear debrief. Turn the next answer into a stronger one.")
    left, right = st.columns([1.35, 1], gap="large")
    with left:
        jd_questions = st.session_state.get("jd_questions", [])
        with st.container(border=True):
            st.subheader("Set up your round")
            with st.form("practice_setup", border=False):
                role = st.selectbox("Role", ROLES)
                focus = st.segmented_control("Question focus", FOCUSES, default="Balanced")
                mode = st.segmented_control(
                    "Practice format",
                    ["Guided coaching", "Mock interview"],
                    default="Guided coaching",
                )
                interviewer = st.selectbox(
                    "Interviewer lens",
                    ["Encouraging coach", "Hiring manager", "Technical lead"],
                    help="Choose the perspective used to shape your answer feedback.",
                )
                pressure = st.segmented_control(
                    "Challenge level",
                    ["Supportive", "Standard", "Demanding"],
                    default="Standard",
                )
                count = st.select_slider("Questions in this round", options=[3, 5, 7, 10], value=5)
                use_jd = False
                if jd_questions:
                    use_jd = st.checkbox(f"Use my {len(jd_questions)} job-specific questions", value=True)
                start = st.form_submit_button("Start interview", type="primary", width="stretch")
        if start:
            if use_jd and jd_questions:
                questions = [{"question": item, "topic": "Job description"} for item in jd_questions[:count]]
            else:
                questions = get_questions(role, focus, count)
            st.session_state.practice_questions = questions
            st.session_state.practice_index = 0
            st.session_state.practice_answers = []
            st.session_state.practice_feedback = None
            st.session_state.practice_mode = mode
            st.session_state.practice_role = role
            st.session_state.practice_interviewer = interviewer
            st.session_state.practice_pressure = pressure
            st.rerun()
    with right:
        with st.container(border=True):
            st.subheader("Your interview brief")
            st.write("Every round is built around a role, not a generic quiz.")
            st.markdown(":material/looks_one: **Answer** one question at a time")
            st.markdown(":material/looks_two: **Debrief** on relevance, structure, and evidence")
            st.markdown(":material/looks_3: **Retry** with the feedback in mind")
            st.divider()
            st.caption("Guided coaching includes a structure prompt. Mock interview keeps that prompt hidden until after you answer.")
        if not get_api_key():
            st.warning("Add an OpenRouter API key to enable AI feedback.")
        st.page_link(
            "pages/1_Job_Description.py",
            label="Build a round from a job description",
            icon=":material/description:",
        )


def render_feedback(feedback: dict) -> None:
    st.subheader("Answer debrief")
    score_column, verdict_column = st.columns([1, 3], vertical_alignment="center")
    score_column.metric("Answer score", f"{feedback['score']} / 5")
    if feedback["verdict"]:
        verdict_column.write(feedback["verdict"])
    strengths, improvements = st.columns(2)
    with strengths:
        with st.container(border=True):
            st.markdown("**What landed**")
            for item in feedback["strengths"]:
                st.markdown(f"- {item}")
    with improvements:
        with st.container(border=True):
            st.markdown("**Your next improvement**")
            for item in feedback["improvements"]:
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


def render_practice() -> None:
    questions = st.session_state.practice_questions
    index = st.session_state.practice_index
    answers = st.session_state.practice_answers
    total = len(questions)
    interviewer = st.session_state.get("practice_interviewer", "Hiring manager")
    pressure = st.session_state.get("practice_pressure", "Standard")

    if index >= total:
        st.title("Your session debrief", icon=":material/analytics:")
        scores = [item["feedback"]["score"] for item in answers if item.get("feedback")]
        summary_columns = st.columns(3)
        summary_columns[0].metric("Questions answered", len(answers))
        summary_columns[1].metric(
            "Average answer score",
            f"{sum(scores) / len(scores):.1f} / 5" if scores else "—",
        )
        summary_columns[2].metric("Role", st.session_state.practice_role)
        st.caption(f"{interviewer} · {pressure} challenge")
        if answers:
            with st.expander("Review your answers"):
                for position, item in enumerate(answers, start=1):
                    st.markdown(f"**{position}. {item['question']}**")
                    st.caption(item["answer"])
                    st.markdown(f"Score: {item['feedback']['score']} / 5")
        if st.button("Set up another round", type="primary", icon=":material/refresh:"):
            reset_session()
            st.rerun()
        return

    mode = st.session_state.practice_mode
    question = questions[index]
    st.title(st.session_state.practice_role, icon=":material/record_voice_over:")
    st.caption(f"{mode} · {interviewer} · {pressure} challenge")
    st.progress(index / total, text=f"Question {index + 1} of {total}")
    with st.container(border=True):
        st.caption(question["topic"])
        st.subheader(html.escape(question["question"]))

    feedback = st.session_state.practice_feedback
    if feedback is None:
        if mode == "Guided coaching":
            with st.expander("Before you answer: a quick structure"):
                st.write("Set the context, explain your decision or approach, share the result, and reflect on what you learned.")
        answer = st.text_area("Your answer", height=220, placeholder="Take a breath, then write it as you would say it aloud.", key=f"answer_{index}")
        if st.button("Get feedback", type="primary", disabled=not bool(get_api_key())):
            try:
                clean_answer = validate_text(answer, "answer", 8000)
                with st.spinner("Reviewing your answer..."):
                    result = review_answer(
                        st.session_state.practice_role,
                        mode,
                        question["question"],
                        clean_answer,
                        interviewer,
                        pressure,
                    )
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
                st.session_state.practice_feedback = result
                st.rerun()
            except GuardError as error:
                st.error(str(error))
            except Exception as error:
                st.error(f"Could not get feedback: {error}")
    else:
        render_feedback(feedback)
        if st.button("Retry this answer"):
            st.session_state[f"answer_{index}"] = ""
            st.session_state.practice_feedback = None
            st.rerun()
        if st.button("Next question →", type="primary"):
            st.session_state.practice_index += 1
            st.session_state.practice_feedback = None
            st.rerun()

    if st.button("End session"):
        st.session_state.practice_index = total
        st.rerun()


with st.sidebar:
    st.title("Fieldnotes", icon=":material/graphic_eq:")
    st.caption("Interview practice for the next opportunity.")
    st.page_link("app.py", label="Practice room", icon=":material/record_voice_over:")
    st.page_link("pages/1_Job_Description.py", label="Job description", icon=":material/description:")
    st.caption("Sessions stay in this browser session; answers are sent to OpenRouter for feedback.")

if "practice_questions" in st.session_state:
    render_practice()
else:
    render_setup()
import streamlit as st

from interview_app.chains.interview_graph import run_config
from interview_app.progress import SKILLS, summarize
from interview_app.ui import render_sidebar

render_sidebar()

# ---------------------------------------------------------------------------
# Session progress (this browser session only)
# ---------------------------------------------------------------------------
chat_states = []
graph = st.session_state.get("chat_graph")
for thread in st.session_state.get("chat_threads", []):
    if graph is not None:
        chat_states.append(graph.get_state(run_config(thread["id"])).values)
progress = summarize(chat_states, st.session_state.get("practice_history", []))

st.title("Welcome back" if progress.has_activity else "Welcome to Interview App", icon=":material/waving_hand:")
st.caption("Ready for your next practice round? Pick up where you left off, or start something new.")

# ---------------------------------------------------------------------------
# Headline metrics
# ---------------------------------------------------------------------------
metrics = st.columns(4)
metrics[0].metric("Interviews completed", progress.interviews_completed, border=True,
                  help="Interview chat sessions that reached the summary.")
metrics[1].metric("Questions answered", progress.questions_answered, border=True,
                  help="Scored answers in the Interview chat and the Practice room.")
metrics[2].metric("Average score", f"{progress.average_score:.1f} / 5" if progress.average_score is not None else "—", border=True)
metrics[3].metric("Highest level reached", progress.highest_level or "—", border=True,
                  help="The hardest difficulty you have answered at. The interviewer raises it after two strong answers.")

# ---------------------------------------------------------------------------
# Skills and recent activity
# ---------------------------------------------------------------------------
skills_column, activity_column = st.columns([1, 1.3], gap="medium")
with skills_column.container(border=True, height="stretch"):
    st.markdown("**Skill breakdown**")
    if progress.skill_samples:
        for key, label in SKILLS:
            value = progress.skills[key]
            st.progress(value / 5, text=f"{label} · {value:.1f} / 5")
        if progress.strongest_skill:
            note = f"Strongest: {dict(SKILLS)[progress.strongest_skill].lower()}"
            if progress.weakest_skill:
                note += f" · focus next on {dict(SKILLS)[progress.weakest_skill].lower()}"
            st.caption(f"{note}. Based on {progress.skill_samples} interview answer{'s' if progress.skill_samples != 1 else ''}.")
    else:
        for _key, label in SKILLS:
            st.progress(0.0, text=f"{label} · not scored yet")
        st.caption("Answer questions in the Interview chat to see your skill breakdown.")

with activity_column.container(border=True, height="stretch"):
    st.markdown("**Recent activity**")
    if progress.recent:
        for item in progress.recent:
            row = st.container(horizontal=True, vertical_alignment="center")
            row.markdown(f"**{item['score']}/5**")
            row.markdown(item["question"] if len(item["question"]) <= 90 else item["question"][:87] + "...")
            st.caption(f"{item['source']} · {item['role']}" + (f" · {item['difficulty']}" if item["difficulty"] else ""))
    else:
        st.caption("Nothing yet. Your answered questions will appear here.")
    if progress.interviews_in_progress:
        st.page_link("app_pages/interview_chat.py", label=f"Resume your interview ({progress.interviews_in_progress} in progress)",
                     icon=":material/play_circle:")

# ---------------------------------------------------------------------------
# Start practising
# ---------------------------------------------------------------------------
st.subheader("Start practising")
CARDS = (
    ("app_pages/interview_chat.py", ":material/forum:", "AI mock interview",
     "A conversational interviewer that follows up on your answers and adapts the difficulty as you go."),
    ("app_pages/practice.py", ":material/record_voice_over:", "Practice room",
     "One question at a time with a score, a sample answer, and step-by-step coaching."),
    ("app_pages/job_description.py", ":material/description:", "Job description prep",
     "Paste or upload a job description to get the skills, likely questions, and a prep plan."),
)
for column, (path, icon, title, text) in zip(st.columns(len(CARDS)), CARDS):
    with column.container(border=True, height="stretch"):
        st.markdown(f"{icon} **{title}**")
        st.caption(text)
        st.page_link(path, label="Try now", icon=":material/arrow_forward:")

st.caption("Progress covers this browser session only; nothing about your answers is saved.")

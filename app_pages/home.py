import streamlit as st

from interview_app.chains.interview_graph import run_config
from interview_app.progress import SKILLS, summarize
from interview_app.theme import card, hero
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

with hero("home"):
    st.badge("INTERVIEW PREP", icon=":material/graphic_eq:", color="green")
    st.title("Welcome back" if progress.has_activity else "Welcome to Interview App", icon=":material/waving_hand:")
    st.caption("Get interview-ready before interview day: practice realistic mock interviews, "
               "get feedback on every answer, and see exactly where to improve.")
    st.page_link("app_pages/interview_chat.py", label="Start a mock interview", icon=":material/arrow_forward:")

# ---------------------------------------------------------------------------
# Headline metrics
# ---------------------------------------------------------------------------
METRICS = (
    ("Interviews completed", progress.interviews_completed, ":material/task_alt:",
     "Interview chat sessions that reached the summary."),
    ("Questions answered", progress.questions_answered, ":material/forum:",
     "Scored answers in the Interview chat and the Practice room."),
    ("Average score", f"{progress.average_score:.1f} / 5" if progress.average_score is not None else "—", ":material/star:", None),
    ("Highest level reached", progress.highest_level or "—", ":material/trending_up:",
     "The hardest difficulty you have answered at. The interviewer raises it after two strong answers."),
)
for index, (column, (label, value, icon, help_text)) in enumerate(zip(st.columns(4), METRICS)):
    with column, card(f"metric_{index}", height="stretch"):
        st.metric(label, value, icon=icon, help=help_text)

# ---------------------------------------------------------------------------
# Skills and recent activity
# ---------------------------------------------------------------------------
skills_column, activity_column = st.columns([1, 1.3], gap="medium")
with skills_column, card("skills", height="stretch"):
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

with activity_column, card("activity", height="stretch"):
    st.markdown("**Recent activity**")
    if progress.recent:
        for item in progress.recent:
            row = st.container(horizontal=True, vertical_alignment="center")
            score = item["score"]
            with row:
                st.badge(f"{score}/5", color="green" if score >= 4 else "orange" if score >= 3 else "red")
            row.markdown(item["question"] if len(item["question"]) <= 90 else item["question"][:87] + "...")
            st.caption(f"{item['source']} · {item['role']}" + (f" · {item['difficulty']}" if item["difficulty"] else ""))
    else:
        st.caption("Nothing yet. Your answered questions will appear here.")
    if progress.interviews_in_progress:
        st.page_link("app_pages/interview_chat.py", label=f"Resume your interview ({progress.interviews_in_progress} in progress)",
                     icon=":material/play_circle:")

# ---------------------------------------------------------------------------
# Start practicing
# ---------------------------------------------------------------------------
st.subheader("Start practicing")
# First card: dark green feature card; the others: white cards with a lime icon chip.
CARDS = (
    ("app_pages/interview_chat.py", ":material/forum:", "AI mock interviews that feel real",
     "A conversational interviewer that follows up on your answers and adapts the difficulty as you go."),
    ("app_pages/practice.py", ":material/record_voice_over:", "Practice room",
     "One question at a time with a score, a sample answer, and step-by-step coaching."),
    ("app_pages/job_description.py", ":material/description:", "Job description prep",
     "Paste or upload a job description to get the skills, likely questions, and a prep plan."),
)
for index, (column, (path, icon, title, text)) in enumerate(zip(st.columns(len(CARDS)), CARDS)):
    make_box = hero if index == 0 else card
    with column, make_box(f"feature_{index}", height="stretch"):  # created inside the column
        st.markdown(f":green-badge[{icon}]")
        st.markdown(f"#### {title}")
        st.caption(text)
        st.page_link(path, label="Try now", icon=":material/arrow_forward:")

st.caption("Progress covers this browser session only; nothing about your answers is saved.")

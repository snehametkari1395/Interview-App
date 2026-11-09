"""Shared Streamlit-side services: the persistent question memory and its thresholds."""

import streamlit as st

from interview_app.vectorstore import QuestionMemory, Thresholds


@st.cache_resource(show_spinner="Loading the question memory (first run downloads a small embedding model)...")
def get_question_memory() -> QuestionMemory:
    """One persistent ChromaDB collection shared by the app (stored in data/chroma, git-ignored)."""
    return QuestionMemory()


def current_thresholds() -> Thresholds:
    stored = st.session_state.get("dedupe_thresholds")
    return stored.validated() if isinstance(stored, Thresholds) else Thresholds()


def record_chain_usage(records: list[dict]) -> None:
    """Add LangChain call records to the session usage log shown on Model settings and the sidebar."""
    log = st.session_state.setdefault("usage_log", [])
    log.extend(records)
    del log[:-200]

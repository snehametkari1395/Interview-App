import streamlit as st

from interview_app.catalog import DOMAINS
from interview_app.chains.llm import spec_from_session
from interview_app.chains.workflows import generate_unique_questions
from interview_app.openrouter import get_api_key, reserve_calls
from interview_app.security_guard import GuardError, guard_untrusted_input
from interview_app.services import current_thresholds, get_question_memory, record_chain_usage
from interview_app.ui import profile_inputs, render_sidebar, require_api_key, show_error
from interview_app.vectorstore import DEFAULT_DUPLICATE_THRESHOLD, DEFAULT_SIMILAR_THRESHOLD, EMBEDDING_MODEL, Thresholds

LABEL_COLORS = {"duplicate": "red", "similar": "orange", "new": "green"}

render_sidebar()

st.badge("VECTOR DATABASE", icon=":material/database:", color="green")
st.title("Question memory", icon=":material/database:")
st.caption(
    f"Generated questions are embedded with `{EMBEDDING_MODEL}` via OpenRouter and stored in ChromaDB, "
    "so new questions can be checked for semantic repeats. Only question text is embedded; candidate answers are never stored."
)

memory = get_question_memory()

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
with st.container(border=True):
    st.markdown("**Similarity thresholds**")
    stored = current_thresholds()
    left, right = st.columns(2)
    duplicate = left.slider("Duplicate at or above", 0.50, 0.99, stored.duplicate, 0.01,
                            help="Cosine similarity at which a new question counts as the same question reworded. Duplicates are regenerated.")
    similar = right.slider("Similar at or above", 0.30, 0.95, stored.similar, 0.01,
                           help="Same sub-topic from a different angle. Similar questions are kept but labelled.")
    thresholds = Thresholds(duplicate, similar).validated()
    st.session_state.dedupe_thresholds = thresholds
    st.caption(
        f"Defaults {DEFAULT_DUPLICATE_THRESHOLD} / {DEFAULT_SIMILAR_THRESHOLD} were calibrated on labelled question pairs with this "
        "embedding model: reworded duplicates scored 0.83–0.96, related questions 0.70–0.83, different questions 0.34–0.69. Raise the duplicate "
        "threshold if useful questions are being rejected; lower it if rewordings slip through. Thresholds are specific to the embedding model."
    )

check_tab, demo_tab, browse_tab = st.tabs(["Check a question", "Generate without repeats", f"Stored questions ({memory.count()})"])

with check_tab:
    domain = st.selectbox("Domain", list(DOMAINS), key="mem_check_domain")
    text = st.text_area("Question to check", max_chars=600, height=80, placeholder="e.g. Can you explain how Python decorators work?")
    if st.button("Check similarity", type="primary", icon=":material/search:") and text.strip():
        try:
            clean, _ = guard_untrusted_input(text, "question", 600)
            check = memory.check(clean, thresholds, domain=domain)
            st.badge(f"{check.label.capitalize()} · best similarity {check.similarity:.2f}", color=LABEL_COLORS[check.label])
            if check.matches:
                st.dataframe(
                    [{"Similarity": match.similarity, "Stored question": match.text, "Difficulty": match.metadata.get("difficulty", ""),
                      "Role": match.metadata.get("role", ""), "Label": thresholds.label(match.similarity)} for match in check.matches],
                    hide_index=True,
                    column_config={"Similarity": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f")},
                    alt="Nearest stored questions",
                )
            else:
                st.caption("No stored questions in this domain yet.")
        except GuardError as error:
            st.error(str(error))

with demo_tab:
    st.write("Generate questions with chain B. The nearest stored questions are sent as \"avoid\", and each result is checked; duplicates are regenerated.")
    profile = profile_inputs("mem", show_persona=False, show_depth=False)
    topic = st.text_input("Topic", value="Python", max_chars=200, key="mem_topic")
    count = st.slider("Questions", 1, 5, 2, key="mem_count")
    if st.button("Generate", type="primary", icon=":material/auto_awesome:", disabled=not get_api_key()) and require_api_key("generation"):
        try:
            clean_topic, _ = guard_untrusted_input(topic, "topic", 200)
            reserve_calls(3)
            with st.spinner("Generating and checking for repeats..."):
                result = generate_unique_questions(spec_from_session(), profile, count=count, memory=memory, thresholds=thresholds,
                                                   topic_hint=clean_topic, source="question memory")
            record_chain_usage([output.usage_record() for output in result.outputs])
            st.session_state.mem_demo = result
        except GuardError as error:
            show_error(error, "generate questions")
        except Exception as error:
            show_error(error, "generate questions")
    result = st.session_state.get("mem_demo")
    if result:
        st.caption(f"Sent {len(result.avoid_used)} stored question(s) as \"avoid\" · {len(result.outputs)} generation round(s)")
        for item in result.rejected:
            with st.container(border=True):
                if item["novelty"] == "duplicate":
                    st.badge(f"Rejected duplicate · {item['similarity']:.2f}", color="red")
                else:
                    st.badge(f"Rejected · {item['novelty']}", color="red")
                st.markdown(f"~~{item['question']}~~")
                if item["nearest"]:
                    st.caption(f"Too close to: {item['nearest']}")
        for item in result.accepted:
            with st.container(border=True):
                st.badge(f"{item['novelty'].capitalize()} · {item['similarity']:.2f}", color=LABEL_COLORS[item["novelty"]])
                st.markdown(f"**{item['question']}**")
                if item["nearest"]:
                    st.caption(f"Nearest stored: {item['nearest']}")

with browse_tab:
    domain_filter = st.selectbox("Filter by domain", ["All domains", *DOMAINS], key="mem_browse_domain")
    rows = memory.list_questions(domain=None if domain_filter == "All domains" else domain_filter)
    if not rows:
        st.caption("No questions stored yet. Generate some in the practice room, interview chat, or the tab above.")
    else:
        selection = st.dataframe(
            [{"Question": row["question"], "Domain": row.get("domain", ""), "Role": row.get("role", ""), "Company": row.get("company", ""),
              "Difficulty": row.get("difficulty", ""), "Category": row.get("category", ""), "Source": row.get("source", ""),
              "Created": row.get("created_at", "")} for row in rows],
            hide_index=True,
            on_select="rerun",
            selection_mode="multi-row",
            key="mem_table",
            alt="Stored interview questions",
        )
        chosen = [rows[index]["id"] for index in selection.selection.rows]
        actions = st.container(horizontal=True)
        if actions.button(f"Delete selected ({len(chosen)})", disabled=not chosen, icon=":material/delete:"):
            memory.delete(chosen)
            st.rerun()
        with actions.popover("Clear all", icon=":material/delete_forever:"):
            st.write(f"Delete all {len(rows)} stored questions{'' if domain_filter == 'All domains' else ' in ' + domain_filter}?")
            if st.button("Delete all", type="primary", key="mem_clear"):
                memory.clear(None if domain_filter == "All domains" else domain_filter)
                st.rerun()

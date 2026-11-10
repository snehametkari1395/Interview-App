import streamlit as st

from interview_app.app_review import DOSSIER_FILES, PERSPECTIVES, build_dossier, critique_to_markdown, run_critique
from interview_app.security_guard import GuardError
from interview_app.ui import render_sidebar, require_api_key, show_error
from interview_app.theme import hero, panel

SEVERITY_BADGE = {"high": ("High", "red"), "medium": ("Medium", "orange"), "low": ("Low", "gray")}
PERSPECTIVE_ICON = {"Usability": ":material/touch_app:", "Security": ":material/shield:", "Prompt engineering": ":material/edit_note:"}

st.set_page_config(page_title="App review | Interview App", page_icon=":material/rate_review:", layout="wide")

params = render_sidebar()

with hero("app_review"):
    st.badge("APP REVIEW", icon=":material/rate_review:", color="green")
    st.title("AI critique of this app", icon=":material/rate_review:")
    st.caption("Ask the configured model to review Interview App for usability, security, and prompt engineering, with actionable recommendations.")

with panel(border=True):
    st.markdown("**What gets sent**")
    st.write(
        f"An allow-listed set of {len(DOSSIER_FILES)} source files (pages, prompts, guard, and API client) plus a short feature summary. "
        "Secrets files are never included, and anything resembling a credential is redacted before sending."
    )
    with st.expander("Files included"):
        # File names only: showing contents would expose the system prompts in the UI.
        dossier, files = build_dossier()
        st.caption(f"{len(files)} files · {len(dossier):,} characters after redaction")
        st.markdown("\n".join(f"- `{name}`" for name in files))
    st.caption("Uses at least 4,000 output tokens. One model call.")
    run = st.button("Run the review", type="primary", icon=":material/play_arrow:")

if run and require_api_key("the app review"):
    try:
        with st.spinner("Reviewing the application..."):
            critique, reviewed_files = run_critique(params)
        if not critique["perspectives"]:
            raise GuardError("The review came back without any perspectives. Please try again or raise max output tokens.")
        st.session_state.app_review = critique
    except GuardError as error:
        st.error(str(error))
    except Exception as error:
        show_error(error, "run the review")

critique = st.session_state.get("app_review")
if critique:
    st.divider()
    st.subheader("Review")
    st.write(critique["overall_summary"])
    score_row = st.columns(len(PERSPECTIVES))
    for column, name in zip(score_row, PERSPECTIVES):
        perspective = next((p for p in critique["perspectives"] if p["name"] == name), None)
        column.metric(name, f"{perspective['score']} / 5" if perspective else "—", border=True)

    if critique["top_priorities"]:
        with panel(border=True):
            st.markdown("**Top priorities**")
            for index, item in enumerate(critique["top_priorities"], start=1):
                st.markdown(f"{index}. {item}")

    tabs = st.tabs([p["name"] for p in critique["perspectives"]])
    for tab, perspective in zip(tabs, critique["perspectives"]):
        with tab:
            st.write(perspective["summary"])
            if perspective["strengths"]:
                st.markdown("**Strengths**")
                for item in perspective["strengths"]:
                    st.markdown(f"- {item}")
            st.markdown("**Issues and recommendations**")
            for issue in perspective["issues"]:
                label, color = SEVERITY_BADGE[issue["severity"]]
                with panel(border=True):
                    st.badge(label, color=color)
                    st.markdown(f"**{issue['title']}**")
                    if issue["evidence"]:
                        st.caption(issue["evidence"])
                    st.markdown(f":material/lightbulb: {issue['recommendation']}")
    st.download_button(
        "Download review as Markdown",
        data=critique_to_markdown(critique),
        file_name="interview-app-review.md",
        mime="text/markdown",
        icon=":material/download:",
        on_click="ignore",
    )

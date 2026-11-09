import streamlit as st

from interview_app.catalog import DOMAINS
from interview_app.coaching import analyze_job_description
from interview_app.file_ingest import ALLOWED_EXTENSIONS, MAX_FILE_BYTES, extract_text
from interview_app.openrouter import get_api_key
from interview_app.question_bank import ROLES
from interview_app.security_guard import GuardError, guard_untrusted_input
from interview_app.ui import render_sidebar, show_error

MAX_JD_CHARS = 12000

st.set_page_config(page_title="Job description | Fieldnotes", page_icon=":material/description:", layout="wide")

render_sidebar()

st.badge("ROLE INTELLIGENCE", icon=":material/description:", color="blue")
st.title("Build a role brief", icon=":material/description:")
st.caption("Turn the job description into a focused interview plan, then take those questions straight into practice.")

with st.container(border=True):
    with st.form("job_description_form", border=False):
        domain = st.selectbox("Domain", list(DOMAINS), help="Helps the analysis use the right vocabulary and priorities.")
        role = st.selectbox("Role title", ["Use the title in the description"] + ROLES + ["Other / not listed"])
        description = st.text_area("Paste the job description", height=220, max_chars=MAX_JD_CHARS, placeholder="Paste the role description here...")
        upload = st.file_uploader(
            "Or upload it",
            type=[extension.lstrip(".") for extension in ALLOWED_EXTENSIONS],
            help=f"Plain text, Markdown, PDF, or Word (.docx), up to {MAX_FILE_BYTES // 1024 // 1024} MB. An uploaded file takes priority over pasted text.",
        )
        submitted = st.form_submit_button("Build my prep plan", type="primary", width="stretch")

if not get_api_key():
    st.info("Add an OpenRouter API key to generate a tailored analysis. Your description is sent to OpenRouter and is not saved by this app.")

if submitted:
    try:
        source = description
        if upload is not None:
            extracted = extract_text(upload.name, upload.getvalue())
            source = extracted.text
            st.caption(f"Read {extracted.kind.upper()} file `{upload.name}` ({extracted.detail}).")
        clean_description, assessment = guard_untrusted_input(source, "job description", MAX_JD_CHARS)
        if not get_api_key():
            st.error("OpenRouter is not configured yet. Add OPENROUTER_API_KEY and try again.")
        else:
            if assessment.flags:
                st.warning(assessment.message, icon=":material/shield:")
            with st.spinner("Finding the signals in this role..."):
                analysis = analyze_job_description(role, clean_description, domain, input_flags=assessment.flags)
            st.session_state.jd_analysis = analysis
            st.session_state.jd_questions = analysis["likely_questions"] if analysis["is_job_description"] else []
    except GuardError as error:
        st.error(str(error))
    except Exception as error:
        show_error(error, "analyse this description")

analysis = st.session_state.get("jd_analysis")
if analysis and not analysis.get("is_job_description", True):
    st.warning(
        "This doesn't look like a job description, so no prep plan was built. "
        + (analysis.get("relevance_note") or "Try pasting the full role description."),
        icon=":material/help:",
    )
elif analysis:
    st.subheader("Role signal")
    st.write(analysis["role_summary"])

    metric_columns = st.columns(3)
    metric_columns[0].metric("Skills surfaced", len(analysis["skills"]))
    metric_columns[1].metric("Likely questions", len(analysis["likely_questions"]))
    metric_columns[2].metric("Prep steps", len(analysis["prep_plan"]))

    st.markdown("### Skills to prepare")
    if analysis["skills"]:
        skill_columns = st.columns(2)
        for index, skill in enumerate(analysis["skills"]):
            with skill_columns[index % 2].container(border=True):
                label = skill["name"]
                if skill["importance"]:
                    label += f" · {skill['importance']}"
                st.markdown(f"**{label}**")
                st.caption(skill["evidence"] or "Highlighted in the job description.")
    else:
        st.write("No clear skills were returned. Try a more complete job description.")

    st.markdown("### Likely interview questions")
    for index, question in enumerate(analysis["likely_questions"], start=1):
        with st.container(border=True):
            st.markdown(f"**{index:02d} / {question}**")

    st.markdown("### Preparation plan")
    for step in analysis["prep_plan"]:
        with st.container(border=True):
            st.markdown(f"**{step['step']}** · {step['focus']}")
            st.write(step["action"])

    if analysis["likely_questions"]:
        st.page_link(
            "app.py",
            label=f"Practice these {len(analysis['likely_questions'])} questions",
            icon=":material/arrow_forward:",
        )

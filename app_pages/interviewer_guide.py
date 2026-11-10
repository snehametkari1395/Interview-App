import streamlit as st

from interview_app.catalog import INTERVIEW_TYPES
from interview_app.guidelines import generate_guide, guide_to_markdown
from interview_app.security_guard import GuardError, guard_untrusted_input
from interview_app.ui import profile_inputs, remember_profile, render_sidebar, require_api_key, show_error
from interview_app.theme import hero, panel

MAX_FOCUS_CHARS = 300

st.set_page_config(page_title="Interviewer guide | Interview App", page_icon=":material/fact_check:", layout="wide")

params = render_sidebar()

with hero("interviewer_guide"):
    st.badge("FOR INTERVIEWERS", icon=":material/fact_check:", color="green")
    st.title("Interviewer guide", icon=":material/fact_check:")
    st.caption("Generate a structured, fair evaluation guide: criteria, competencies, a 1–5 rubric, indicators, red flags, and follow-ups.")

settings, output = st.columns([1, 2], gap="large")
with settings:
    with panel(border=True):
        profile = profile_inputs("guide", show_depth=True, show_persona=True)
        interview_types = st.pills(
            "Interview type",
            INTERVIEW_TYPES,
            selection_mode="multi",
            default=list(INTERVIEW_TYPES),
            help="Generate a technical guide, a behavioural guide, or both.",
        )
        focus_area = st.text_input(
            "Focus area (optional)",
            max_chars=MAX_FOCUS_CHARS,
            placeholder="e.g. stakeholder communication, SQL performance",
        )
        st.caption("Uses at least 3,000 output tokens per guide.")
        generate = st.button(
            "Generate guide",
            type="primary",
            width="stretch",
            icon=":material/auto_awesome:",
            disabled=not interview_types,
        )

with output:
    if generate and require_api_key("the interviewer guide"):
        try:
            clean_focus = ""
            if focus_area.strip():
                clean_focus, _ = guard_untrusted_input(focus_area, "focus area", MAX_FOCUS_CHARS)
            guides = {}
            for interview_type in [item for item in INTERVIEW_TYPES if item in interview_types]:
                with st.spinner(f"Writing the {interview_type.lower()} interview guide..."):
                    guides[interview_type] = generate_guide(profile, interview_type, clean_focus, params=params)
            remember_profile(profile)
            st.session_state.guide_result = {"profile": profile, "guides": guides}
        except GuardError as error:
            st.error(str(error))
        except Exception as error:
            show_error(error, "generate the guide")

    result = st.session_state.get("guide_result")
    if not result:
        with panel(border=True):
            st.markdown("**What you'll get**")
            st.markdown(
                "- Evaluation criteria with weights\n- Expected competencies\n- A 1–5 scoring rubric\n"
                "- Positive indicators, red flags, and common mistakes\n- A sample question with a strong answer\n- Follow-up questions"
            )
            st.caption("Guides adapt to the domain, role, and difficulty. The persona changes interviewer conduct only, never the rubric.")
    else:
        guide_profile = result["profile"]
        st.subheader(guide_profile.role)
        st.caption(f"{guide_profile.domain} · {guide_profile.difficulty} difficulty · {guide_profile.persona} interviewer · {guide_profile.depth} responses")
        st.download_button(
            "Download as Markdown",
            data=guide_to_markdown(guide_profile, result["guides"]),
            file_name="interviewer-guide.md",
            mime="text/markdown",
            icon=":material/download:",
            on_click="ignore",
        )
        tabs = st.tabs(list(result["guides"]))
        for tab, (interview_type, guide) in zip(tabs, result["guides"].items()):
            with tab:
                st.write(guide["overview"])
                st.markdown("#### Expected competencies")
                columns = st.columns(2)
                for index, competency in enumerate(guide["competencies"]):
                    with columns[index % 2], panel(border=True):
                        st.markdown(f"**{competency['name']}**")
                        st.caption(competency["description"])

                st.markdown("#### Evaluation criteria")
                st.dataframe(
                    [{"Criterion": c["criterion"], "Weight": c["weight"], "Look for": c["look_for"]} for c in guide["evaluation_criteria"]],
                    hide_index=True,
                    alt=f"{interview_type} evaluation criteria",
                )

                st.markdown("#### Scoring rubric")
                for row in guide["rubric"]:
                    with panel(border=True):
                        st.markdown(f"**{row['score']} · {row['label']}**")
                        st.caption(row["description"])

                good, bad = st.columns(2)
                with good, panel(border=True, height="stretch"):
                    st.markdown(":green[**Positive indicators**]")
                    for item in guide["positive_indicators"]:
                        st.markdown(f"- {item}")
                with bad, panel(border=True, height="stretch"):
                    st.markdown(":red[**Red flags**]")
                    for item in guide["red_flags"]:
                        st.markdown(f"- {item}")
                with st.expander("Common mistakes"):
                    for item in guide["common_mistakes"]:
                        st.markdown(f"- {item}")
                with st.expander("Example of a strong answer", expanded=True):
                    st.markdown(f"**Question:** {guide['sample_question']}")
                    st.write(guide["strong_answer_example"])
                st.markdown("#### Suggested follow-up questions")
                for item in guide["follow_up_questions"]:
                    st.markdown(f"- {item}")
                if guide["interviewer_conduct"]:
                    st.info(guide["interviewer_conduct"], icon=":material/record_voice_over:")

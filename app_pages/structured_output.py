import json

import streamlit as st

from interview_app.catalog import DOMAINS
from interview_app.openrouter import active_model, current_params, get_capabilities
from interview_app.pricing import format_usd
from interview_app.question_bank import get_questions
from interview_app.schemas import EVALUATION_DOCUMENT_SCHEMA, QA_DOCUMENT_SCHEMA
from interview_app.security_guard import GuardError, guard_untrusted_input
from interview_app.structured import (
    MAX_QA_COUNT,
    estimate_request_cost,
    evaluation_request,
    qa_request,
    run_evaluation,
    run_qa,
)
from interview_app.ui import profile_inputs, remember_profile, render_cost, render_sidebar, require_api_key, show_error

MAX_QUESTION_CHARS = 600
CATEGORY_LABELS = {"technical": "Technical", "scenario": "Scenario", "behavioral": "Behavioural"}
MAX_ANSWER_CHARS = 8000
MODE_LABELS = {
    "json_schema": "JSON Schema enforced by the provider (strict)",
    "json_object": "JSON mode + server-side schema validation",
    "prompt": "Prompted JSON + server-side schema validation",
}

st.set_page_config(page_title="Structured output | Interview App", page_icon=":material/data_object:", layout="wide")

params = render_sidebar()
model = active_model()
caps = get_capabilities(model)

st.badge("STRUCTURED JSON", icon=":material/data_object:", color="green")
st.title("Structured output", icon=":material/data_object:")
st.caption("Generate machine-readable interview material that is validated against a JSON Schema, then view or download it.")


def render_estimate(request) -> None:
    typical, worst = estimate_request_cost(request, caps, current_params())
    render_cost(typical, title="Estimated cost (typical response)")
    st.caption(
        f"Worst case if the full output budget is used ({worst.output_tokens:,} tokens): {format_usd(worst.total)}. "
        "Input tokens are approximated at ~4 characters per token; the provider's tokenizer may differ."
    )


def render_result_footer(document: dict, result, file_name: str) -> None:
    status = st.container(horizontal=True, vertical_alignment="center")
    status.badge("Schema valid", icon=":material/verified:", color="green")
    status.caption(MODE_LABELS[result.output_mode])
    if result.fallback_used:
        status.badge("Fallback model used", icon=":material/swap_horiz:", color="orange")
    if not result.params_guaranteed and caps.known:
        status.caption("Parameter support not guaranteed by the serving provider.")
    if result.attempts:
        with st.expander("Retries and failover"):
            for line in result.attempts:
                st.markdown(f"- {line}")
    render_cost(result.cost)
    with st.expander("JSON", icon=":material/data_object:"):
        st.json(document, expanded=2)
    st.download_button(
        "Download JSON",
        data=json.dumps(document, indent=2, ensure_ascii=False),
        file_name=file_name,
        mime="application/json",
        icon=":material/download:",
        on_click="ignore",
    )


qa_tab, evaluation_tab, schema_tab = st.tabs(["Format 1 · Q&A set", "Format 2 · Evaluation", "Schemas"])

with qa_tab:
    settings, output = st.columns([1, 2], gap="large")
    with settings, st.container(border=True):
        profile = profile_inputs("sq", show_persona=False)
        focus = st.segmented_control("Focus", DOMAINS[profile.domain].focuses, default="Balanced", required=True, key=f"sq_focus_{profile.domain}")
        count = st.slider("Number of questions", 1, MAX_QA_COUNT, 3, key="sq_count")
        request = qa_request(profile, focus, count)
        generate = st.button("Generate Q&A set", type="primary", width="stretch", icon=":material/auto_awesome:")
    with output:
        if generate and require_api_key("structured output"):
            try:
                with st.spinner(f"Generating {count} structured question{'s' if count != 1 else ''}..."):
                    document, result, warnings = run_qa(request, profile, params)
                remember_profile(profile)
                st.session_state.structured_qa = {"document": document, "result": result, "warnings": warnings}
            except Exception as error:
                show_error(error, "generate the Q&A set")
        saved = st.session_state.get("structured_qa")
        if not saved:
            render_estimate(request)
        else:
            if st.button("New estimate for the current settings", icon=":material/calculate:"):
                st.session_state.pop("structured_qa")
                st.rerun()
            document = saved["document"]
            for warning in saved["warnings"]:
                st.warning(warning)
            meta = document["metadata"]
            st.caption(f"{meta['role']} · {meta['domain']} · {meta['difficulty']} · {len(document['questions'])} questions")
            for item in document["questions"]:
                with st.expander(f"**{item['question_id']}** · {item['question']}", expanded=item["question_id"] == "Q1"):
                    st.caption(f"{CATEGORY_LABELS.get(item['category'], item['category'].capitalize())} · {item['difficulty']}")
                    st.markdown("**Expected answer**")
                    st.write(item["expected_answer"])
                    st.markdown("**Key concepts:** " + " · ".join(item["key_concepts"]))
                    st.markdown("**Example answer**")
                    st.write(item["example_answer"])
                    st.markdown("**Follow-up questions**")
                    for follow_up in item["follow_up_questions"]:
                        st.markdown(f"- {follow_up}")
                    st.markdown("**Evaluation criteria**")
                    for criterion in item["evaluation_criteria"]:
                        st.markdown(f"- **{criterion['criterion']}**: {criterion['description']}")
            render_result_footer(document, saved["result"], "interview-qa-set.json")

with evaluation_tab:
    settings, output = st.columns([1, 2], gap="large")
    with settings, st.container(border=True):
        profile = profile_inputs("se", show_persona=False)
        suggestion = get_questions(profile.role, "Balanced", 1, domain=profile.domain, difficulty=profile.difficulty)[0]["question"]
        if "se_question" not in st.session_state:
            st.session_state.se_question = suggestion
        question = st.text_area("Interview question", key="se_question", max_chars=MAX_QUESTION_CHARS, height=90)
        answer = st.text_area("Candidate answer", key="se_answer", max_chars=MAX_ANSWER_CHARS, height=200, placeholder="Write or paste the answer to evaluate...")
        evaluate = st.button("Evaluate answer", type="primary", width="stretch", icon=":material/grading:")
    with output:
        if evaluate and require_api_key("structured output"):
            try:
                clean_question, _ = guard_untrusted_input(question, "question", MAX_QUESTION_CHARS)
                clean_answer, assessment = guard_untrusted_input(answer, "answer", MAX_ANSWER_CHARS)
                if assessment.flags:
                    st.warning(assessment.message, icon=":material/shield:")
                with st.spinner("Evaluating the answer..."):
                    document, result = run_evaluation(evaluation_request(profile, clean_question, clean_answer, assessment.flags), profile, params)
                remember_profile(profile)
                st.session_state.structured_eval = {"document": document, "result": result}
            except GuardError as error:
                show_error(error, "evaluate the answer")
            except Exception as error:
                show_error(error, "evaluate the answer")
        saved = st.session_state.get("structured_eval")
        if not saved:
            preview_answer = answer.strip() or "x" * 600  # typical-length placeholder for the estimate
            render_estimate(evaluation_request(profile, question.strip() or suggestion, preview_answer))
        else:
            if st.button("New estimate for the current settings", icon=":material/calculate:", key="se_new"):
                st.session_state.pop("structured_eval")
                st.rerun()
            document = saved["document"]
            scores = st.columns(4)
            scores[0].metric("Overall score", f"{document['overall_score']} / 5", border=True)
            for column, (key, label) in zip(scores[1:], [("technical_accuracy", "Technical accuracy"), ("communication_skills", "Communication"), ("problem_solving", "Problem-solving")]):
                column.metric(label, f"{document[key]['score']} / 5", border=True)
            st.write(document["summary"])
            for key, label in [("technical_accuracy", "Technical accuracy"), ("communication_skills", "Communication skills"), ("problem_solving", "Problem-solving ability")]:
                st.markdown(f"**{label}:** {document[key]['comment']}")
            left, right = st.columns(2)
            with left.container(border=True, height="stretch"):
                st.markdown(":green[**Strengths**]")
                for item in document["strengths"]:
                    st.markdown(f"- {item}")
            with right.container(border=True, height="stretch"):
                st.markdown(":red[**Weaknesses**]")
                for item in document["weaknesses"]:
                    st.markdown(f"- {item}")
            if document["missing_concepts"]:
                st.markdown("**Missing concepts:** " + " · ".join(document["missing_concepts"]))
            st.markdown("**Improvement suggestions**")
            for item in document["improvement_suggestions"]:
                st.markdown(f"- {item}")
            st.markdown("**Recommended follow-up questions**")
            for item in document["recommended_follow_up_questions"]:
                st.markdown(f"- {item}")
            render_result_footer(document, saved["result"], "interview-evaluation.json")

with schema_tab:
    st.write(
        "Both formats are defined as JSON Schema (draft 2020-12). When the selected model supports structured outputs, "
        "the schema is sent to the provider in strict mode. Every response is then validated again on the server, including "
        "ranges and minimum sizes that strict mode may not enforce, before anything is displayed."
    )
    st.caption(f"Active model `{model}`: {MODE_LABELS['json_schema' if caps.supports_structured_outputs else ('json_object' if caps.supports('response_format') and caps.known else 'prompt')]}.")
    for title, schema, file_name in [
        ("Format 1 · Interview Q&A set", QA_DOCUMENT_SCHEMA, "interview-qa-set.schema.json"),
        ("Format 2 · Interview evaluation", EVALUATION_DOCUMENT_SCHEMA, "interview-evaluation.schema.json"),
    ]:
        with st.expander(title):
            st.json(schema, expanded=False)
            st.download_button("Download schema", data=json.dumps(schema, indent=2), file_name=file_name, mime="application/json", on_click="ignore", key=f"dl_{file_name}")

import statistics

import streamlit as st

from interview_app.comparison import (
    JUDGE_DIMENSIONS,
    MAX_RUNS,
    TASKS,
    RunConfig,
    judge_outputs,
    run_comparison,
    summarize,
)
from interview_app.model_config import PARAMETER_GUIDE, TEMPERATURE_RANGE, GenerationParams
from interview_app.openrouter import ALLOWED_MODELS, active_model, describe_error, get_api_key, get_capabilities, model_catalog, reserve_calls
from interview_app.question_bank import get_questions
from interview_app.security_guard import GuardError, guard_untrusted_input
from interview_app.ui import MAX_TOKEN_OPTIONS, profile_inputs, render_sidebar, require_api_key, show_error

MAX_QUESTION_CHARS = 600
MAX_ANSWER_CHARS = 4000
CONFIG_LABELS = ("A", "B", "C")
DEFAULT_TEMPERATURES = (0.0, 0.7, 1.3)
NO_EFFORT = "Model default"

st.set_page_config(page_title="Model lab | Fieldnotes", page_icon=":material/tune:", layout="wide")

render_sidebar()

st.badge("MODEL LAB", icon=":material/tune:", color="green")
st.title("Compare parameter settings", icon=":material/tune:")
st.caption("Run the same interview task under different settings, then compare quality, relevance, creativity, accuracy, length, and consistency.")

with st.expander("How each parameter affects the output", icon=":material/school:"):
    for name, text in PARAMETER_GUIDE.items():
        st.markdown(f"**{name}.** {text}")
    st.markdown(
        "**Reading the results.** *Consistency* compares repeated runs of the same configuration (1.0 means identical text); "
        "run each configuration at least twice to see it. *Lexical diversity* is the share of distinct words, a rough proxy "
        "for varied wording. *Score spread* (answer review only) shows how much the score moved between runs; a fair "
        "evaluator should be stable at low temperature. Quality, relevance, creativity, and accuracy come from an optional "
        "judge model and are estimates, not ground truth."
    )

catalog = model_catalog()
configured_model = active_model()
model_options = sorted(dict.fromkeys([*ALLOWED_MODELS, configured_model]))

setup, configs_column = st.columns([1, 1.6], gap="large")
with setup:
    with st.container(border=True):
        st.markdown("**Task**")
        task = st.segmented_control("What should the model do?", TASKS, default=TASKS[0], required=True, help="Model answer: write an ideal answer. Answer review: score and critique a candidate answer.")
        profile = profile_inputs("lab", show_persona=task == "Answer review")
        suggestion = get_questions(profile.role, "Balanced", 1, domain=profile.domain, difficulty=profile.difficulty)[0]["question"]
        if "lab_question" not in st.session_state:
            st.session_state.lab_question = suggestion
        if st.button("Suggest a question", icon=":material/casino:"):
            st.session_state.lab_question = suggestion
        question = st.text_area("Interview question", key="lab_question", max_chars=MAX_QUESTION_CHARS, height=90)
        answer = ""
        if task == "Answer review":
            answer = st.text_area("Candidate answer to review", max_chars=MAX_ANSWER_CHARS, height=160, placeholder="Paste or write an answer to evaluate...")

with configs_column:
    with st.container(border=True):
        top = st.container(horizontal=True, vertical_alignment="bottom")
        config_count = top.segmented_control("Configurations", [2, 3], default=2, required=True)
        runs = top.segmented_control("Runs per configuration", list(range(1, MAX_RUNS + 1)), default=2, required=True, help="Two or more runs are needed to measure consistency.")
        use_judge = top.toggle("Judge model", value=True, help="Adds one call where the configured model rates each output anonymously.")

        configs: list[RunConfig] = []
        columns = st.columns(config_count)
        for position, column in enumerate(columns):
            label = CONFIG_LABELS[position]
            with column.container(border=True):
                st.markdown(f"**Config {label}**")
                model = st.selectbox("Model", model_options, index=model_options.index(configured_model), key=f"lab_model_{label}")
                caps = get_capabilities(model)
                temperature = st.slider(
                    "Temperature",
                    TEMPERATURE_RANGE[0],
                    TEMPERATURE_RANGE[1],
                    DEFAULT_TEMPERATURES[position],
                    0.1,
                    key=f"lab_temp_{label}",
                    disabled=caps.known and not caps.supports("temperature"),
                )
                max_tokens = st.select_slider("Max output tokens", MAX_TOKEN_OPTIONS, value=2000, key=f"lab_tokens_{label}")
                effort = st.selectbox(
                    "Reasoning effort",
                    [NO_EFFORT, *caps.effort_options],
                    key=f"lab_effort_{label}",
                    disabled=not caps.supports_reasoning,
                    help=None if caps.supports_reasoning else "Not supported by this model; never sent.",
                )
                configs.append(RunConfig(
                    label=f"Config {label}",
                    model=model,
                    params=GenerationParams(
                        temperature=temperature,
                        max_tokens=max_tokens,
                        reasoning_effort=effort if effort in caps.effort_options else None,
                    ).validated(),
                ))
        total_calls = config_count * runs + (1 if use_judge else 0)
        st.caption(f"This comparison makes {total_calls} model calls.")
        run_clicked = st.button("Run comparison", type="primary", width="stretch", icon=":material/play_arrow:")

if run_clicked and require_api_key("the model lab"):
    try:
        clean_question, _ = guard_untrusted_input(question, "question", MAX_QUESTION_CHARS)
        clean_answer, flags = "", ()
        if task == "Answer review":
            clean_answer, assessment = guard_untrusted_input(answer, "answer", MAX_ANSWER_CHARS)
            flags = assessment.flags
        reserve_calls(total_calls)
        capabilities = {config.model: get_capabilities(config.model) for config in configs}
        api_key = get_api_key()
        with st.spinner(f"Running {config_count * runs} generations..."):
            outcomes = run_comparison(task, profile, clean_question, clean_answer, configs, runs, api_key, capabilities)
        judge_rows, judge_error = [], ""
        if use_judge:
            with st.spinner("Judging the outputs..."):
                try:
                    judge_rows = judge_outputs(profile, clean_question, outcomes, api_key=api_key, model=configured_model, capabilities=get_capabilities(configured_model))
                except Exception as error:
                    judge_error = describe_error(error)
        st.session_state.lab_result = {
            "task": task,
            "question": clean_question,
            "configs": configs,
            "outcomes": outcomes,
            "judge": judge_rows,
            "judge_error": judge_error,
            "flags": flags,
        }
    except GuardError as error:
        st.error(str(error))
    except Exception as error:
        show_error(error, "run the comparison")

result = st.session_state.get("lab_result")
if result:
    st.divider()
    st.subheader("Results")
    st.caption(f"{result['task']} · {result['question']}")
    rows = summarize(result["configs"], result["outcomes"])

    judge_by_config: dict[str, dict[str, float]] = {}
    for row in result["judge"]:
        bucket = judge_by_config.setdefault(row["Config"], {dimension: [] for dimension in JUDGE_DIMENSIONS})
        for dimension in JUDGE_DIMENSIONS:
            bucket[dimension].append(row[dimension.capitalize()])
    for row in rows:
        scores = judge_by_config.get(row["Config"])
        for dimension in JUDGE_DIMENSIONS:
            row[dimension.capitalize()] = round(statistics.mean(scores[dimension]), 2) if scores and scores[dimension] else None

    score_column = st.column_config.ProgressColumn(min_value=1, max_value=5, format="%.1f")
    st.dataframe(
        rows,
        hide_index=True,
        column_config={
            "Quality": score_column,
            "Relevance": score_column,
            "Creativity": score_column,
            "Accuracy": score_column,
            "Consistency": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f"),
            "Lexical diversity": st.column_config.NumberColumn(format="%.2f"),
        },
        alt="Comparison of parameter configurations",
    )
    if result["judge_error"]:
        st.warning(f"The judge step failed: {result['judge_error']}", icon=":material/gavel:")

    skipped = {(o.label, param) for o in result["outcomes"] for param in o.skipped_params}
    if skipped:
        st.caption("Not sent because the model does not support it: " + ", ".join(f"{label}: {param}" for label, param in sorted(skipped)))

    observations = []
    measured = [row for row in rows if row["Successful runs"]]
    if len(measured) >= 2:
        longest = max(measured, key=lambda row: row["Avg words"] or 0)
        shortest = min(measured, key=lambda row: row["Avg words"] or 0)
        observations.append(f"{longest['Config']} produced the longest responses (~{longest['Avg words']} words) and {shortest['Config']} the shortest (~{shortest['Avg words']}).")
        consistent = [row for row in measured if row["Consistency"] is not None]
        if len(consistent) >= 2:
            most = max(consistent, key=lambda row: row["Consistency"])
            least = min(consistent, key=lambda row: row["Consistency"])
            observations.append(f"{most['Config']} was the most consistent across runs ({most['Consistency']:.2f}) and {least['Config']} the least ({least['Consistency']:.2f}); higher temperature usually lowers consistency.")
        judged = [row for row in measured if row["Quality"] is not None]
        if judged:
            best = max(judged, key=lambda row: (row["Quality"], row["Accuracy"] or 0))
            observations.append(f"The judge rated {best['Config']} highest for quality ({best['Quality']:.1f}/5).")
    if observations:
        with st.container(border=True):
            st.markdown("**Observations**")
            for line in observations:
                st.markdown(f"- {line}")

    if result["judge"]:
        with st.expander("Judge ratings per run"):
            st.dataframe(result["judge"], hide_index=True, alt="Judge ratings for each run")

    st.markdown("#### Outputs")
    output_columns = st.columns(len(result["configs"]))
    for column, config in zip(output_columns, result["configs"]):
        with column:
            st.markdown(f"**{config.label}**")
            st.caption(f"{config.model} · {config.params.label()}")
            for outcome in [o for o in result["outcomes"] if o.label == config.label]:
                with st.container(border=True):
                    meta = f"Run {outcome.run}"
                    if outcome.ok:
                        meta += f" · {outcome.latency_s:.1f}s"
                        if outcome.score is not None:
                            meta += f" · score {outcome.score}/5"
                        if outcome.finish_reason == "length":
                            meta += " · cut off"
                    st.caption(meta)
                    if outcome.ok:
                        st.write(outcome.text)
                    else:
                        st.error(outcome.error)

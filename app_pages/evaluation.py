import json

import streamlit as st

from interview_app.evaluation.judge import DIMENSIONS, DIMENSION_KEYS, DIMENSION_LABELS
from interview_app.evaluation.report import (
    DETERMINISTIC_KEYS,
    LIMITATIONS,
    model_comparison,
    noise_level,
    prompt_comparison,
    recommendations,
    summarize,
    to_markdown,
)
from interview_app.evaluation.runner import EvalConfig, load_dataset, load_latest, run_evaluation, save_results
from interview_app.licensing import COMPARISON_MODELS, JUDGE_MODEL, classify
from interview_app.openrouter import get_api_key, model_catalog, reserve_calls
from interview_app.security_guard import GuardError
from interview_app.services import current_thresholds, get_question_memory
from interview_app.ui import render_sidebar, require_api_key, show_error

SCORE_COLUMN = st.column_config.ProgressColumn(min_value=1, max_value=5, format="%.2f")

render_sidebar()

st.badge("LLM AS A JUDGE", icon=":material/insights:", color="orange")
st.title("Prompt and model evaluation", icon=":material/insights:")
st.caption("Generated question sets are scored by deterministic checks first, then by an LLM judge on nine dimensions (1–5), twice per output.")

dataset = load_dataset()
results_tab, run_tab, dataset_tab, method_tab = st.tabs(["Results", "Run an evaluation", f"Dataset ({len(dataset)} cases)", "Methodology"])

with run_tab:
    catalog = model_catalog()
    options = sorted(set(catalog) | set(COMPARISON_MODELS) | {JUDGE_MODEL})
    open_options = [model for model in options if classify(model).is_open_weight]
    models = st.multiselect("Models to compare (improved prompt)", open_options or options, default=[m for m in COMPARISON_MODELS if m in (open_options or options)][:2],
                            help="Only open-weight models are listed. At least two are needed for a model comparison.")
    compare_prompts = st.checkbox("Also run the original (v1) prompt on the first model, for the prompt comparison", value=True)
    judge = st.selectbox("Judge model", ["None (deterministic checks only)", *options],
                         index=options.index(JUDGE_MODEL) + 1 if JUDGE_MODEL in options else 0,
                         help="Use a different model family from the models being compared, to reduce self-preference bias.")
    passes = st.segmented_control("Judge passes", [1, 2], default=2, required=True, help="Two passes (reversed order) measure judge consistency.")
    case_ids = st.multiselect("Cases", [case["id"] for case in dataset], default=[case["id"] for case in dataset][:3])
    configs = [EvalConfig(f"{model.split('/')[-1]} · v2", model, "v2-improved") for model in models]
    if compare_prompts and models:
        configs.append(EvalConfig(f"{models[0].split('/')[-1]} · v1", models[0], "v1-original"))
    judge_model = None if judge.startswith("None") else judge
    calls = len(configs) * len(case_ids) * (1 + (passes if judge_model else 0))
    st.caption(f"{len(configs)} configurations × {len(case_ids)} cases → {calls} model calls. The command-line runner (scripts/run_evaluation.py) prints a cost estimate.")
    if judge_model and any(judge_model.split("/")[0] == model.split("/")[0] for model in models):
        st.warning("The judge is from the same model family as a compared model; self-preference bias is more likely.", icon=":material/balance:")
    if st.button("Run evaluation", type="primary", icon=":material/play_arrow:", disabled=not (configs and case_ids and get_api_key())) and require_api_key("evaluation"):
        try:
            reserve_calls(calls)
            cases = [case for case in dataset if case["id"] in case_ids]
            with st.status(f"Running {calls} model calls...", expanded=True) as status:
                def progress(done, total, record):
                    status.update(label=f"{done}/{total} done · {record['config']} · {record['case_id']}")
                results = run_evaluation(configs, cases, api_key=get_api_key(), judge_model=judge_model,
                                         embed=get_question_memory().embed, thresholds=current_thresholds(), passes=passes, progress=progress)
                save_results(results)
                status.update(label="Evaluation complete", state="complete")
            st.session_state.eval_results = results
            st.success("Saved to docs/evaluation/latest.json. Open the Results tab.")
        except GuardError as error:
            st.error(str(error))
        except Exception as error:
            show_error(error, "run the evaluation")

with results_tab:
    results = st.session_state.get("eval_results") or load_latest()
    if not results:
        st.info("No evaluation results yet. Run one from the next tab or with scripts/run_evaluation.py.", icon=":material/info:")
    else:
        meta, summary = results["meta"], summarize(results)
        noise = noise_level(summary)
        st.caption(f"Run {meta['run_at']} · judge `{meta['judge_model']}` · {meta['judge_passes']} passes · differences under {noise} treated as noise")
        overview = [{"Config": row["config"], "Licence": row["licence"], "Overall": row["overall"], "Success": f"{row['success_rate']:.0%}",
                     "Latency (s)": row["latency_s"], "Output tokens": row["tokens_out"], "Cost per case": row["cost_per_case"],
                     "Judge disagreement": row["judge_disagreement"]} for row in summary]
        st.dataframe(overview, hide_index=True, column_config={"Overall": SCORE_COLUMN, "Cost per case": st.column_config.NumberColumn(format="$%.5f")},
                     alt="Overall results by configuration")

        st.markdown("#### Average score per dimension")
        st.dataframe([{"Dimension": DIMENSION_LABELS[key], **{row["config"]: row["dimensions"][key] for row in summary}} for key in DIMENSION_KEYS],
                     hide_index=True, column_config={row["config"]: SCORE_COLUMN for row in summary}, alt="Average judge score per dimension")
        for row in summary:
            if row["strongest"]:
                st.markdown(f"- **{row['config']}**: strongest *{DIMENSION_LABELS[row['strongest']]}* ({row['dimensions'][row['strongest']]}), "
                            f"weakest *{DIMENSION_LABELS[row['weakest']]}* ({row['dimensions'][row['weakest']]})")

        st.markdown("#### Deterministic checks")
        st.dataframe([{"Config": row["config"], **{label: row["deterministic"][key] for key, label in DETERMINISTIC_KEYS}} for row in summary],
                     hide_index=True, alt="Deterministic check results")

        comparison = prompt_comparison(summary)
        if comparison:
            st.markdown(f"#### Prompt comparison on `{comparison['model']}`")
            st.dataframe(comparison["rows"], hide_index=True, alt="Original versus improved prompt")
        if len(model_comparison(summary)) > 1:
            st.markdown("#### Model comparison (improved prompt)")
            st.dataframe([{"Config": r["config"], "Overall": r["overall"], "Latency (s)": r["latency_s"], "Cost per case": r["cost_per_case"]}
                          for r in model_comparison(summary)], hide_index=True,
                         column_config={"Overall": SCORE_COLUMN, "Cost per case": st.column_config.NumberColumn(format="$%.5f")}, alt="Model comparison")

        st.markdown("#### Recommendations")
        for item in recommendations(results, summary):
            st.markdown(f"- {item}")

        st.markdown("#### Individual results")
        labels = [f"{r['config']} · {r['case_id']}" for r in results["records"]]
        chosen = st.selectbox("Result", range(len(labels)), format_func=labels.__getitem__)
        record = results["records"][chosen]
        if not record["ok"]:
            st.error(record["error"])
        else:
            for question in record["generation"]["questions"]:
                st.markdown(f"- **{question['question']}**  \n  {question['difficulty']} · {question['topic']}")
            st.caption("Deterministic issues: " + (", ".join(record["deterministic"]["issues"]) or "none"))
            if record.get("judge"):
                st.dataframe([{"Dimension": DIMENSION_LABELS[k], "Score": record["judge"][k]["score"], "Passes": str(record["judge"][k]["passes"]),
                               "Explanation": record["judge"][k]["explanations"][0]} for k in DIMENSION_KEYS],
                             hide_index=True, column_config={"Score": SCORE_COLUMN}, alt="Judge scores for this result")
        downloads = st.container(horizontal=True)
        downloads.download_button("Download report (Markdown)", to_markdown(results), "evaluation-report.md", "text/markdown", on_click="ignore", icon=":material/download:")
        downloads.download_button("Download results (JSON)", json.dumps(results, indent=2), "evaluation-results.json", "application/json", on_click="ignore", icon=":material/data_object:")

with dataset_tab:
    st.write("Each case pairs a job description with the expected job context (chain A's ideal output) and the topics a good question set should cover.")
    for case in dataset:
        with st.expander(f"{case['id']} · {case['domain']} · {case['difficulty']}"):
            st.markdown(f"**{case['role']}**")
            st.write(case["job_description"])
            st.markdown("**Expected topics:** " + ", ".join(topic["topic"] for topic in case["expected_topics"]))
            st.caption(case["quality_notes"])

with method_tab:
    st.markdown("**Pipeline per configuration and case**")
    st.markdown("1. Generate questions with chain B (same job context, difficulty, and count for every configuration).\n"
                "2. Deterministic checks: schema validity, required fields, count, difficulty label, keyword coverage of expected topics, "
                "embedding similarity between questions (repetition), follow-up distinctness, question length.\n"
                "3. LLM judge, twice (second pass with the questions in reverse order), temperature 0, anchored rubric:")
    st.dataframe([{"Dimension": label, "Anchors": anchors} for _, label, anchors in DIMENSIONS], hide_index=True, alt="Judge rubric")
    st.markdown("Scale: 1 very poor · 2 needs significant improvement · 3 acceptable · 4 good · 5 excellent.")
    st.markdown("**Limitations and biases**")
    for item in LIMITATIONS:
        st.markdown(f"- {item}")

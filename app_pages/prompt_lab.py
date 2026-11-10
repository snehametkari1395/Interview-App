import streamlit as st

from interview_app.chains.llm import spec_from_session
from interview_app.openrouter import get_api_key, reserve_calls
from interview_app.prompt_techniques import PRODUCTION_TECHNIQUE, TECHNIQUE_BY_KEY, TECHNIQUES, TEST_CASES, load_results, rank, run_comparison, save_results, summarize
from interview_app.security_guard import GuardError
from interview_app.ui import render_sidebar, require_api_key, show_error
from interview_app.theme import hero, panel

render_sidebar()

with hero("prompt_lab"):
    st.badge("PROMPT ENGINEERING", icon=":material/science:", color="green")
    st.title("Prompt lab", icon=":material/science:")
    st.caption("Five system prompts that use different techniques for the same task, evaluating an interview answer, compared on human-labelled answers.")

columns = st.columns(len(TECHNIQUES))
for column, technique in zip(columns, TECHNIQUES):
    with column, panel(border=True, height="stretch"):
        st.markdown(f"**{technique.name}**")
        st.caption(technique.description)
        if technique.key == PRODUCTION_TECHNIQUE:
            st.badge("Used in the app", color="green", icon=":material/check:")

st.markdown(f"**Test set:** {len(TEST_CASES)} answers with human-assigned expected scores: "
            + "; ".join(f"`{case['id']}` expected {case['expected'][0]}–{case['expected'][1]}" for case in TEST_CASES) + ".")

runs = st.segmented_control("Runs per answer", [1, 2], default=2, required=True, help="Two runs measure whether a technique gives the same score twice.")
calls = len(TECHNIQUES) * len(TEST_CASES) * runs
if st.button(f"Run comparison ({calls} model calls)", type="primary", icon=":material/play_arrow:", disabled=not get_api_key()) and require_api_key("the prompt lab"):
    try:
        reserve_calls(calls)
        with st.status(f"Running {calls} evaluations...", expanded=False) as status:
            results = run_comparison(spec_from_session(), runs=runs,
                                     progress=lambda done, total: status.update(label=f"{done}/{total} evaluations done"))
            status.update(label="Comparison complete", state="complete")
        save_results(results)
        st.session_state.prompt_lab_results = results
    except GuardError as error:
        st.error(str(error))
    except Exception as error:
        show_error(error, "run the comparison")

results = st.session_state.get("prompt_lab_results") or load_results()
if not results:
    st.info("No comparison has been run yet.", icon=":material/info:")
else:
    rows = rank(summarize(results))
    st.subheader("Results")
    st.caption(f"Run {results['meta']['run_at']} · model `{results['meta']['model']}` · {results['meta']['runs']} run(s) per answer")
    st.success(f"Best technique: **{rows[0]['technique']}** (accuracy {rows[0]['accuracy']:.0%}). "
               f"The app currently uses **{TECHNIQUE_BY_KEY[PRODUCTION_TECHNIQUE].name}** for answer evaluation.", icon=":material/emoji_events:")
    st.dataframe(
        [{"Technique": r["technique"], "Valid": r["valid"], "Accuracy": r["accuracy"], "Mean distance from range": r["mean_abs_error"],
          "Consistency": r["consistency"], "Latency (s)": r["latency_s"], "Output tokens": r["output_tokens"], "Cost per call": r["cost_per_call"]}
         for r in rows],
        hide_index=True,
        column_config={"Accuracy": st.column_config.ProgressColumn(min_value=0, max_value=1, format="percent"),
                       "Consistency": st.column_config.ProgressColumn(min_value=0, max_value=1, format="percent"),
                       "Cost per call": st.column_config.NumberColumn(format="$%.5f")},
        alt="Prompt technique comparison",
    )
    st.markdown("**Scores per answer**")
    st.dataframe(
        [{"Technique": technique.name, **{f"{case['id']} ({case['expected'][0]}–{case['expected'][1]})":
          ", ".join(str(r["score"]) if r["ok"] else "error" for r in results["records"] if r["technique"] == technique.key and r["case"] == case["id"])
          for case in TEST_CASES}} for technique in TECHNIQUES],
        hide_index=True, alt="Scores each technique gave each answer",
    )
    st.caption("Accuracy: share of runs whose score falls in the expected range. Consistency: share of answers that got the same score in both runs. "
               "Full prompts and analysis: docs/PROMPT_TECHNIQUES.md.")

from concurrent.futures import ThreadPoolExecutor

import streamlit as st

from interview_app.openrouter import describe_error, get_api_key, get_capabilities, active_model, reserve_calls
from interview_app.security_guard import (
    FLAG_DESCRIPTIONS,
    GuardError,
    assess_input,
    clean_model_text,
    get_semantic_detector,
    sanitize_text,
)
from interview_app.security_lab import SAMPLE_CASES, is_detected, llm_screen
from interview_app.security_suite import DETERMINISTIC_TESTS, LIVE_TESTS, LiveContext, report_json, report_markdown, run_suite
from interview_app.ui import render_sidebar, require_api_key

MAX_CUSTOM_CHARS = 4000

st.set_page_config(page_title="Security lab | Interview App", page_icon=":material/shield:", layout="wide")

render_sidebar()

st.badge("SECURITY LAB", icon=":material/shield:", color="red")
st.title("Security lab", icon=":material/shield:")
st.caption("See how the app's deterministic guard handles risky input, and investigate whether an LLM screen catches what rules miss.")

with st.expander("How the app defends itself", icon=":material/layers:", expanded=False):
    st.markdown(
        """
1. **Deterministic input guard (enforcing).** Unicode normalisation, invisible-character and control-character removal,
   chat-token neutralisation, length limits, and pattern checks for instruction overrides, prompt extraction, role hijacking,
   score manipulation, fake role headers, and encoded payloads. Score-manipulation attempts are blocked; other flags are passed
   to the model as metadata so quoted attacks in legitimate answers still work.
   **Semantic layer:** each sentence is embedded with `qwen/qwen3-embedding-8b` and compared with known attack phrasings, so
   reworded attacks without trigger words are flagged too (calibrated threshold, fails open if the embedding call fails).
2. **Prompt structure.** Trusted settings live in the system prompt; untrusted text travels only as JSON data, with explicit
   rules never to follow it. Every system prompt carries a canary token, and any response that echoes it is discarded.
3. **Output validation.** Responses must be a JSON object; every field is type-checked, clamped, and length-capped. Markdown
   images, link targets, and HTML are stripped before rendering, which blocks image-based data exfiltration.
4. **Operational controls.** API keys stay server-side and are never displayed or logged; errors are mapped to fixed
   messages; each session is rate-limited to 40 AI calls per 10 minutes.
5. **LLM screen (advisory, this page only).** A second opinion. It is never the enforcing layer, because it is itself a model
   reading attacker-controlled text.
"""
    )

custom, benchmark, suite = st.tabs(["Check your own text", "Benchmark", "Test suite"])

with custom:
    text = st.text_area("Text to check", height=140, max_chars=MAX_CUSTOM_CHARS, placeholder="Paste an answer or job description...")
    row = st.container(horizontal=True, vertical_alignment="center")
    check = row.button("Check", type="primary", icon=":material/search:")
    with_llm = row.toggle("Also ask the LLM screen", value=False, disabled=not get_api_key())
    if check and text.strip():
        assessment = assess_input(text)
        verdict = {"low": "success", "medium": "warning", "high": "error"}[assessment.risk]
        getattr(st, verdict)(
            f"Deterministic guard: **{assessment.risk} risk**" + (" · would be blocked" if assessment.blocked else ""),
            icon=":material/rule:",
        )
        for flag in assessment.flags:
            st.markdown(f"- {FLAG_DESCRIPTIONS.get(flag, flag)}")
        detector = get_semantic_detector()
        if detector is not None and not assessment.blocked:
            semantic = detector(sanitize_text(text))
            if semantic is None:
                st.caption("Semantic layer: not available right now (the embedding call failed), so only the rules applied.")
            else:
                (st.warning if semantic.flagged else st.success)(
                    f"Semantic layer: **{'flagged' if semantic.flagged else 'not flagged'}** · similarity {semantic.similarity:.2f} "
                    f"to a known {semantic.category.replace('_', ' ')} attack (threshold {detector.threshold:.2f})",
                    icon=":material/hub:",
                )
                st.caption(f"Closest sentence: \"{semantic.sentence[:160]}\" · closest known attack: \"{semantic.exemplar}\"")
        if sanitize_text(text) != text.strip():
            with st.expander("Sanitised text sent to the model"):
                st.code(sanitize_text(text), language=None, wrap_lines=True)
        if with_llm and require_api_key("the LLM screen"):
            try:
                reserve_calls(1)
                model = active_model()
                with st.spinner("Asking the LLM screen..."):
                    screen = llm_screen(text, api_key=get_api_key(), model=model, capabilities=get_capabilities(model))
                st.info(
                    f"LLM screen: **{screen['risk']} risk**. {screen['rationale']}"
                    + (f" Categories: {', '.join(screen['categories'])}." if screen["categories"] else ""),
                    icon=":material/smart_toy:",
                )
            except GuardError as error:
                st.error(str(error))
            except Exception as error:
                st.error(describe_error(error))
        rendered = clean_model_text(text)
        if rendered != text.strip():
            st.caption("If a model returned this text, the output filter would remove images, link targets, and HTML before display.")

with benchmark:
    st.write(f"{len(SAMPLE_CASES)} test inputs: benign answers (including one that legitimately quotes an attack) and manipulation attempts.")
    deterministic = {case.name: assess_input(case.text) for case in SAMPLE_CASES}
    run_llm = st.button(
        f"Run the LLM screen on all {len(SAMPLE_CASES)} cases",
        icon=":material/smart_toy:",
        disabled=not get_api_key(),
        help=f"Makes {len(SAMPLE_CASES)} model calls at temperature 0.",
    )
    if run_llm:
        try:
            reserve_calls(len(SAMPLE_CASES))
            model, api_key = active_model(), get_api_key()
            caps = get_capabilities(model)

            def screen(case):
                try:
                    return case.name, llm_screen(case.text, api_key=api_key, model=model, capabilities=caps)
                except Exception as error:
                    return case.name, {"risk": "error", "categories": [], "rationale": describe_error(error)}

            with st.spinner("Screening test cases..."), ThreadPoolExecutor(max_workers=4) as pool:
                st.session_state.lab_llm_screen = dict(pool.map(screen, SAMPLE_CASES))
        except GuardError as error:
            st.error(str(error))

    llm_results = st.session_state.get("lab_llm_screen", {})
    rows = []
    for case in SAMPLE_CASES:
        guard = deterministic[case.name]
        llm = llm_results.get(case.name)
        rows.append({
            "Case": case.name,
            "Expected": case.expected,
            "Guard risk": guard.risk,
            "Guard action": "block" if guard.blocked else ("flag" if guard.flags else "allow"),
            "Guard flags": ", ".join(guard.flags) or "—",
            "LLM risk": llm["risk"] if llm else "not run",
            "LLM rationale": llm["rationale"] if llm else "",
        })
    st.dataframe(rows, hide_index=True, alt="Security benchmark: deterministic guard versus LLM screen")

    malicious = [case for case in SAMPLE_CASES if case.expected == "malicious"]
    benign = [case for case in SAMPLE_CASES if case.expected == "benign"]
    metric_row = st.columns(4)
    metric_row[0].metric("Guard detection", f"{sum(is_detected(deterministic[c.name].risk) for c in malicious)} / {len(malicious)}")
    metric_row[1].metric("Guard false positives", f"{sum(is_detected(deterministic[c.name].risk) for c in benign)} / {len(benign)}")
    if llm_results:
        scored = [c for c in malicious if llm_results.get(c.name, {}).get("risk") != "error"]
        metric_row[2].metric("LLM detection", f"{sum(is_detected(llm_results[c.name]['risk']) for c in scored)} / {len(scored)}")
        metric_row[3].metric("LLM false positives", f"{sum(is_detected(llm_results.get(c.name, {}).get('risk', '')) for c in benign)} / {len(benign)}")
    else:
        metric_row[2].metric("LLM detection", "—")
        metric_row[3].metric("LLM false positives", "—")

    with st.container(border=True):
        st.markdown("**What to look for**")
        st.markdown(
            "- **Paraphrased attack** has no trigger phrase, so the pattern rules miss it. In the app the semantic layer flags it "
            "(try it under *Check your own text*), and an LLM screen can add a further opinion.\n"
            "- **Classifier evasion** speaks directly to the security reviewer. It tests whether the LLM screen can itself be talked down.\n"
            "- **Answer that discusses injection** is benign. Rules flag it but do not block it; a good screen should rate it low.\n"
            "- **Data exfiltration** is not an input pattern at all. It is stopped at the output layer, where Markdown images are removed.\n"
            "- LLM results can change between runs and models. Deterministic results never do, which is why rules enforce and the LLM only advises."
        )

with suite:
    st.write(
        f"{len(DETERMINISTIC_TESTS)} deterministic tests exercise the real guard, file-ingest, and output-validation code with simulated "
        f"provider responses (free, repeatable). {len(LIVE_TESTS)} live tests send real jailbreak attempts through the same pipeline the app uses."
    )
    controls = st.container(horizontal=True, vertical_alignment="center")
    run_deterministic = controls.button("Run deterministic tests", type="primary", icon=":material/play_arrow:")
    run_live = controls.button(
        f"Run all tests, including {len(LIVE_TESTS)} live",
        icon=":material/bolt:",
        disabled=not get_api_key(),
        help=f"Makes {len(LIVE_TESTS)} model calls with the active model.",
    )
    if run_deterministic or run_live:
        try:
            context = None
            if run_live:
                reserve_calls(len(LIVE_TESTS))
                model = active_model()
                context = LiveContext(api_key=get_api_key(), model=model, capabilities=get_capabilities(model))
            with st.spinner("Running security tests..."):
                st.session_state.security_suite = {"records": run_suite(context), "model": context.model if context else None}
        except GuardError as error:
            st.error(str(error))

    outcome = st.session_state.get("security_suite")
    if outcome:
        records = outcome["records"]
        passed = sum(record.passed for record in records)
        summary = st.columns(3)
        summary[0].metric("Passed", f"{passed} / {len(records)}", border=True)
        summary[1].metric("Failed", len(records) - passed, border=True)
        live_cost = sum(record.cost_usd or 0 for record in records if record.live)
        summary[2].metric("Live test cost", f"${live_cost:.4f}" if outcome["model"] else "—", border=True)
        st.dataframe(
            [
                {
                    "ID": record.test_id,
                    "Category": record.category,
                    "Scenario": record.scenario + (" (live)" if record.live else ""),
                    "Result": record.status,
                    "Expected": record.expected,
                    "Actual": record.actual,
                    "Vulnerability": record.vulnerability,
                    "Recommendation": record.recommendation,
                }
                for record in records
            ],
            hide_index=True,
            column_config={"Result": st.column_config.TextColumn(width="small")},
            alt="Security test results",
        )
        downloads = st.container(horizontal=True)
        downloads.download_button("Download report (Markdown)", report_markdown(records, outcome["model"]), "security-test-report.md", "text/markdown", icon=":material/download:", on_click="ignore")
        downloads.download_button("Download results (JSON)", report_json(records), "security-test-results.json", "application/json", icon=":material/data_object:", on_click="ignore")

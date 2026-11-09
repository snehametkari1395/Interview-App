import streamlit as st

from interview_app.model_config import PARAM_SPECS, GenerationParams, build_request_body
from interview_app.openrouter import (
    ALLOWED_MODELS,
    active_model,
    current_params,
    describe_error,
    fallback_model,
    get_api_key,
    get_capabilities,
    get_key_info,
    get_model,
    model_catalog,
    refresh_model_catalog,
)
from interview_app.pricing import format_usd, price_per_million
from interview_app.ui import model_label, provider_label, render_sidebar

DEFAULT_EFFORT = "Model default"
NO_FALLBACK = ""

st.set_page_config(page_title="Model settings | Fieldnotes", page_icon=":material/settings:", layout="wide")

render_sidebar()


def _seed(key: str, value) -> None:
    if key not in st.session_state:
        st.session_state[key] = value


def _sync(source: str, target: str) -> None:
    st.session_state[target] = st.session_state[source]


def _reset_to_recommended() -> None:
    for spec in PARAM_SPECS:
        st.session_state[f"cfg_{spec.key}_s"] = st.session_state[f"cfg_{spec.key}_n"] = spec.recommended
    st.session_state.cfg_effort = DEFAULT_EFFORT
    st.session_state.cfg_use_seed = False


st.badge("ADVANCED", icon=":material/settings:", color="green")
st.title("Model settings", icon=":material/settings:")
st.caption("Choose the provider and model, tune generation parameters, and see exactly what will be sent. These settings apply to every AI feature.")

catalog = model_catalog()
configured = get_model()
toolbar = st.container(horizontal=True, vertical_alignment="center")
if toolbar.button("Refresh models and pricing", icon=":material/refresh:"):
    refresh_model_catalog()
    st.rerun()
if catalog:
    toolbar.caption(f"{len(catalog)} models loaded from the OpenRouter models endpoint · cached for up to 1 hour")
else:
    st.warning("Could not load the model list from OpenRouter. Only the configured model is available, and only temperature and max tokens will be sent.", icon=":material/cloud_off:")

# ---------------------------------------------------------------------------
# Provider and model
# ---------------------------------------------------------------------------
current = active_model()
# Only the project's approved models are offered (others are blocked by the account guardrail).
models = sorted(dict.fromkeys([*ALLOWED_MODELS, configured, current]))
providers = sorted({model.split("/", 1)[0] for model in models if "/" in model}, key=lambda p: provider_label(p).lower())
current_provider = current.split("/", 1)[0]

left, right = st.columns([1, 1.3], gap="large")
with left:
    with st.container(border=True):
        st.subheader("Model")
        _seed("cfg_provider", current_provider if current_provider in providers else providers[0])
        if st.session_state.cfg_provider not in providers:  # e.g. after the catalog refreshes
            st.session_state.cfg_provider = current_provider if current_provider in providers else providers[0]
        provider = st.selectbox("Provider", providers, key="cfg_provider", format_func=provider_label)
        provider_models = [model for model in models if model.startswith(f"{provider}/")]
        _seed(f"cfg_model_{provider}", current if current in provider_models else provider_models[0])
        if st.session_state[f"cfg_model_{provider}"] not in provider_models:
            st.session_state[f"cfg_model_{provider}"] = provider_models[0]
        model = st.selectbox("Model", provider_models, key=f"cfg_model_{provider}", format_func=model_label)
        st.session_state.selected_model = model
        if model != configured:
            st.caption(f"Overrides the configured default `{configured}` for this session.")

        _seed("cfg_fallback", fallback_model() or NO_FALLBACK)
        fallback = st.selectbox(
            "Fallback model",
            [NO_FALLBACK, *[m for m in models if m != model]],
            key="cfg_fallback",
            format_func=lambda m: "None" if m == NO_FALLBACK else model_label(m),
            help="Used automatically if the primary model is unavailable (after retries). Auth, credit, and moderation errors never fail over.",
        )
        st.session_state.fallback_model = fallback

caps = get_capabilities(model)
with right:
    with st.container(border=True):
        st.subheader(model_label(model))
        st.caption(f"`{model}`")
        if not caps.known:
            st.info("No capability metadata for this model. Only temperature and max tokens will be sent; costs cannot be calculated.", icon=":material/info:")
        else:
            facts = st.columns(4)
            facts[0].metric("Context", f"{caps.context_length:,}" if caps.context_length else "—")
            facts[1].metric("Max output", f"{caps.max_completion_tokens:,}" if caps.max_completion_tokens else "—")
            facts[2].metric("Input price", price_per_million(caps.pricing, "prompt"))
            facts[3].metric("Output price", price_per_million(caps.pricing, "completion"))
            st.caption(
                f"Inputs: {', '.join(caps.input_modalities) or '—'} · Outputs: {', '.join(caps.output_modalities) or '—'} · "
                f"Structured outputs: {'yes (JSON Schema)' if caps.supports_structured_outputs else 'no (JSON mode or prompting)'} · "
                f"Reasoning: {', '.join(caps.effort_options) if caps.supports_reasoning else 'not supported'}"
            )
            with st.expander("Supported parameters"):
                st.write(", ".join(sorted(caps.supported)) or "None listed.")

# ---------------------------------------------------------------------------
# Generation parameters
# ---------------------------------------------------------------------------
stored = current_params()
st.subheader("Generation parameters")
header = st.container(horizontal=True, vertical_alignment="center")
header.caption("Sliders and number fields stay in sync. Unsupported parameters are disabled and never sent.")
header.button("Reset to recommended", icon=":material/restart_alt:", on_click=_reset_to_recommended)

values: dict = {}
grid = st.columns(2, gap="large")
for index, spec in enumerate(PARAM_SPECS):
    optional = spec.provider_default is not None
    supported = (caps.known and caps.supports(spec.key)) if optional else caps.supports(spec.key)
    maximum = spec.maximum
    if spec.key == "max_tokens" and caps.max_completion_tokens:
        maximum = min(spec.maximum, caps.max_completion_tokens)
    cast = int if spec.kind == "int" else float
    minimum, maximum, step = cast(spec.minimum), cast(maximum), cast(spec.step)
    slider_key, number_key = f"cfg_{spec.key}_s", f"cfg_{spec.key}_n"
    start = cast(getattr(stored, spec.key))
    _seed(slider_key, start)
    _seed(number_key, start)
    for key in (slider_key, number_key):  # keep values inside this model's range
        st.session_state[key] = cast(min(maximum, max(minimum, st.session_state[key])))

    with grid[index % 2].container(border=True):
        st.markdown(f"**{spec.label}** · `{spec.key}`")
        slider_column, number_column = st.columns([3, 1.2], vertical_alignment="bottom")
        slider_column.slider(
            spec.label, min_value=minimum, max_value=maximum, step=step, key=slider_key,
            on_change=_sync, args=(slider_key, number_key), disabled=not supported, label_visibility="collapsed",
        )
        number_column.number_input(
            f"{spec.label} value", min_value=minimum, max_value=maximum, step=step, key=number_key,
            on_change=_sync, args=(number_key, slider_key), disabled=not supported, label_visibility="collapsed",
            format="%d" if spec.kind == "int" else "%.2f",
        )
        value = st.session_state[slider_key]
        status = ""
        if not supported:
            status = f" · :orange[not supported by {model_label(model)}; not sent]"
        elif optional and value == spec.provider_default:
            status = " · provider default; not sent"
        st.caption(f"Range {minimum:g}–{maximum:g} · recommended {spec.recommended:g}{status}")
        st.caption(spec.description)
        values[spec.key] = value

extra_left, extra_right = st.columns(2, gap="large")
with extra_left.container(border=True):
    st.markdown("**Reasoning effort** · `reasoning.effort`")
    options = [DEFAULT_EFFORT, *caps.effort_options]
    _seed("cfg_effort", stored.reasoning_effort or DEFAULT_EFFORT)
    if st.session_state.cfg_effort not in options:
        st.session_state.cfg_effort = DEFAULT_EFFORT
    effort = st.selectbox("Reasoning effort", options, key="cfg_effort", disabled=not caps.supports_reasoning, label_visibility="collapsed")
    st.caption(
        ("Options come from this model's published list. " if caps.supports_reasoning else ":orange[Not supported by this model; never sent.] ")
        + "Higher effort improves multi-step accuracy at the cost of latency and output tokens (reasoning tokens are billed as output)."
    )
with extra_right.container(border=True):
    st.markdown("**Seed** · `seed`")
    seed_supported = caps.known and caps.supports("seed")
    _seed("cfg_use_seed", stored.seed is not None)
    _seed("cfg_seed", stored.seed if stored.seed is not None else 42)
    use_seed = st.checkbox("Use a fixed seed", key="cfg_use_seed", disabled=not seed_supported)
    seed = st.number_input("Seed value", min_value=0, max_value=2**31 - 1, step=1, key="cfg_seed", disabled=not (seed_supported and use_seed))
    st.caption(("" if seed_supported else ":orange[Not supported by this model; never sent.] ") + "Makes sampling more repeatable for comparisons. Determinism is best-effort and not guaranteed by every provider.")

params = GenerationParams(
    **values,
    reasoning_effort=effort if effort in caps.effort_options else None,
    seed=int(seed) if (use_seed and seed_supported) else None,
).validated()
st.session_state.model_settings = params

# ---------------------------------------------------------------------------
# Request preview, account, and session usage
# ---------------------------------------------------------------------------
st.subheader("What will be sent")
plan = build_request_body(model, [], params, caps, schema={"type": "object"})
preview = {key: value for key, value in plan.body.items() if key not in ("messages", "response_format")}
preview["response_format"] = {
    "json_schema": "JSON Schema (strict), for structured-output features",
    "json_object": "JSON mode",
    "prompt": "none: JSON enforced by prompt and server-side validation",
}[plan.output_mode]
preview_column, notes_column = st.columns([1.2, 1], gap="large")
preview_column.json(preview)
with notes_column:
    if plan.skipped:
        st.warning("Not sent (unsupported by this model): " + ", ".join(plan.skipped), icon=":material/block:")
    st.caption(
        "`provider.require_parameters` asks OpenRouter to route only to providers that honour every parameter above; "
        "otherwise providers may silently ignore them. If no provider qualifies, the app retries once without it and labels the result. "
        "Failed requests are retried up to 3 times with exponential backoff."
    )

account, usage = st.columns(2, gap="large")
with account.container(border=True):
    st.markdown("**OpenRouter account**")
    if st.button("Check credits and limits", icon=":material/account_balance_wallet:", disabled=not get_api_key()):
        try:
            st.session_state.key_info = get_key_info(get_api_key())
        except Exception as error:
            st.error(describe_error(error))
    info = st.session_state.get("key_info")
    if info:
        row = st.columns(3)
        row[0].metric("Limit remaining", format_usd(info.get("limit_remaining")) if info.get("limit_remaining") is not None else "No limit")
        row[1].metric("Used today", format_usd(info.get("usage_daily")))
        row[2].metric("Used in total", format_usd(info.get("usage")))
with usage.container(border=True):
    st.markdown("**This session's AI calls**")
    log = st.session_state.get("usage_log", [])
    if log:
        st.dataframe(
            log,
            hide_index=True,
            column_config={"cost_usd": st.column_config.NumberColumn("Cost (USD)", format="$%.6f")},
            alt="AI calls made in this session with token counts and actual cost",
        )
    else:
        st.caption("No AI calls yet.")

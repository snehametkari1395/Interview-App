"""Shared Streamlit UI: sidebar navigation, model summary, and interview-profile controls."""

import streamlit as st

from interview_app.catalog import DEPTHS, DIFFICULTIES, DOMAINS, PERSONAS, PrepProfile
from interview_app.model_config import GenerationParams
from interview_app.openrouter import (
    active_model,
    get_capabilities,
    current_params,
    describe_error,
    get_api_key,
    model_catalog,
    session_spend,
)
from interview_app.pricing import CostBreakdown, format_usd

MAX_TOKEN_OPTIONS = [256, 512, 1000, 1500, 2000, 3000, 4000, 6000, 8000, 12000, 16000]

PROVIDER_LABELS = {
    "openai": "OpenAI",
    "anthropic": "Anthropic Claude",
    "google": "Google Gemini",
    "meta-llama": "Meta Llama",
    "mistralai": "Mistral AI",
    "deepseek": "DeepSeek",
    "x-ai": "xAI Grok",
    "qwen": "Qwen",
    "cohere": "Cohere",
    "amazon": "Amazon Nova",
    "microsoft": "Microsoft",
    "nvidia": "NVIDIA",
    "perplexity": "Perplexity",
    "moonshotai": "Moonshot AI",
    "z-ai": "Z.ai GLM",
}


def provider_label(provider: str) -> str:
    return PROVIDER_LABELS.get(provider, provider.replace("-", " ").title())


def model_label(model: str) -> str:
    return str(model_catalog().get(model, {}).get("name") or model)


def _seed(key: str, value) -> None:
    """Initialise a widget key from a persistent store (widget state is dropped on page switch)."""
    if key not in st.session_state:
        st.session_state[key] = value


def render_sidebar() -> GenerationParams:
    params = current_params()
    with st.sidebar:
        with st.container(border=True):
            st.caption("Active model")
            st.markdown(f"**{model_label(active_model())}**")
            st.caption(params.label(get_capabilities(active_model())))
            calls, spend = session_spend()
            st.caption(f"This session: {calls} AI call{'s' if calls != 1 else ''} · {format_usd(spend)} actual cost")
        st.caption("Sessions stay in this browser session; text you submit is sent to OpenRouter for AI features.")
    return params


def render_cost(cost: CostBreakdown | None, *, title: str | None = None) -> None:
    """Show an estimated or actual cost breakdown, clearly labelled as which it is."""
    if cost is None:
        return
    kind = "Estimated cost" if cost.is_estimate else "Actual cost"
    with st.container(border=True):
        st.markdown(f"**{title or kind}** · `{cost.model}`")
        columns = st.columns(4)
        columns[0].metric("Input tokens", f"{'~' if cost.is_estimate else ''}{cost.input_tokens:,}")
        columns[1].metric("Output tokens", f"{'≤ ' if cost.is_estimate else ''}{cost.output_tokens:,}")
        columns[2].metric("Input cost", format_usd(cost.input_cost))
        columns[3].metric("Output cost", format_usd(cost.output_cost))
        total = format_usd(cost.total)
        if cost.request_cost:
            total += f" (incl. {format_usd(cost.request_cost)} request fee)"
        line = f"**Total {'estimated' if cost.is_estimate else 'computed'} cost: {total}**"
        if not cost.is_estimate and cost.reported_cost is not None:
            line += f" · OpenRouter billed: **{format_usd(cost.reported_cost)}**"
        st.markdown(line)
        if cost.note:
            st.caption(cost.note)


# ---------------------------------------------------------------------------
# Interview profile controls
# ---------------------------------------------------------------------------


def remembered_profile() -> PrepProfile:
    profile = st.session_state.get("last_profile")
    return profile if isinstance(profile, PrepProfile) else PrepProfile()


def remember_profile(profile: PrepProfile) -> None:
    st.session_state.last_profile = profile


def profile_inputs(prefix: str, *, show_depth: bool = True, show_persona: bool = True) -> PrepProfile:
    """Domain, role, difficulty, depth, and persona controls (not inside a form: role depends on domain)."""
    last = remembered_profile()
    domain_names = list(DOMAINS)
    _seed(f"{prefix}_domain", last.domain)
    domain = st.selectbox("Domain", domain_names, key=f"{prefix}_domain")
    roles = list(DOMAINS[domain].roles)
    _seed(f"{prefix}_role_{domain}", last.role if last.role in roles else roles[0])
    role = st.selectbox("Role", roles, key=f"{prefix}_role_{domain}")

    _seed(f"{prefix}_difficulty", last.difficulty)
    difficulty = st.segmented_control(
        "Difficulty",
        list(DIFFICULTIES),
        key=f"{prefix}_difficulty",
        required=True,
        help=" ".join(f"**{level.name}**: {level.summary}" for level in DIFFICULTIES.values()),
    )
    depth = last.depth
    if show_depth:
        _seed(f"{prefix}_depth", last.depth)
        depth = st.segmented_control(
            "Response depth",
            list(DEPTHS),
            key=f"{prefix}_depth",
            required=True,
            help=" ".join(f"**{item.name}**: {item.summary}" for item in DEPTHS.values()),
        )
    persona = last.persona
    if show_persona:
        _seed(f"{prefix}_persona", last.persona)
        persona = st.segmented_control(
            "Interviewer persona",
            list(PERSONAS),
            key=f"{prefix}_persona",
            required=True,
            help=" ".join(f"**{item.name}**: {item.summary}" for item in PERSONAS.values()),
        )
    return PrepProfile(domain=domain, role=role, difficulty=difficulty, depth=depth, persona=persona).validated()


def show_error(error: Exception, action: str) -> None:
    """Display a safe message; raw exception text never reaches the page."""
    st.error(describe_error(error), title=f"Could not {action}")
    raw = getattr(error, "raw_text", None)
    details = getattr(error, "details", None)
    if details:
        with st.expander("Validation details"):
            for item in details:
                st.markdown(f"- `{item}`")
    if raw:
        with st.expander("Raw model response"):
            st.code(raw, language="json", wrap_lines=True)


def require_api_key(feature: str) -> bool:
    if get_api_key():
        return True
    st.info(f"Add an OpenRouter API key (OPENROUTER_API_KEY) to use {feature}.", icon=":material/key:")
    return False

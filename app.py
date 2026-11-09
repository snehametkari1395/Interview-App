"""Interview App entry point: optional access code, then grouped navigation for candidates and developer tools."""

import hmac

import streamlit as st

from interview_app.navigation import available_pages
from interview_app.semantic_guard import install_default_detector

st.set_page_config(page_title="Interview App", page_icon="assets/icon.svg", layout="wide")
st.logo("assets/logo.svg", icon_image="assets/icon.svg", size="large")

# Metric values never wrap and are cut off with "…" in narrow columns (e.g. "$0.000257", "1,047,576").
# Size each value to its own box instead, and let word values wrap at spaces.
st.html("""<style>
[data-testid="stMetric"] { container-type: inline-size; }
[data-testid="stMetricValue"] { font-size: clamp(1.1rem, 15cqi, 2.25rem); line-height: 1.2; }
[data-testid="stMetricValue"], [data-testid="stMetricValue"] *,
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] * { white-space: normal !important; overflow: visible !important; text-overflow: clip !important; }
</style>""")


def access_code() -> str:
    """Optional shared code (APP_ACCESS_CODE in secrets) that protects a public deployment's API credits."""
    try:
        return str(st.secrets.get("APP_ACCESS_CODE", "")).strip()
    except Exception:  # no secrets file: running locally without a code
        return ""


required = access_code()
if required and not st.session_state.get("access_granted"):
    st.title("Interview App", icon=":material/graphic_eq:")
    st.caption("Interview practice. This deployment is protected by an access code.")
    with st.form("access", border=True):
        entered = st.text_input("Access code", type="password")
        if st.form_submit_button("Enter", type="primary"):
            if hmac.compare_digest(entered.strip().encode(), required.encode()):
                st.session_state.access_granted = True
                st.rerun()
            st.error("That code is not correct.")
    st.stop()

# Semantic prompt-injection layer: flags reworded attacks that pattern rules miss (needs the API key).
install_default_detector()

sections: dict[str, list] = {}
for index, (path, title, icon, section) in enumerate(available_pages()):
    sections.setdefault(section, []).append(st.Page(path, title=title, icon=icon, default=index == 0))

st.navigation(sections, position="sidebar").run()

"""Fieldnotes entry point: optional access code, then grouped navigation for candidates and developer tools."""

import hmac

import streamlit as st

from interview_app.navigation import available_pages

st.set_page_config(page_title="Fieldnotes | Interview practice", page_icon="assets/icon.svg", layout="wide")
st.logo("assets/logo.svg", icon_image="assets/icon.svg", size="large")


def access_code() -> str:
    """Optional shared code (APP_ACCESS_CODE in secrets) that protects a public deployment's API credits."""
    try:
        return str(st.secrets.get("APP_ACCESS_CODE", "")).strip()
    except Exception:  # no secrets file: running locally without a code
        return ""


required = access_code()
if required and not st.session_state.get("access_granted"):
    st.title("Fieldnotes", icon=":material/graphic_eq:")
    st.caption("Interview practice. This deployment is protected by an access code.")
    with st.form("access", border=True):
        entered = st.text_input("Access code", type="password")
        if st.form_submit_button("Enter", type="primary"):
            if hmac.compare_digest(entered.strip().encode(), required.encode()):
                st.session_state.access_granted = True
                st.rerun()
            st.error("That code is not correct.")
    st.stop()

sections: dict[str, list] = {}
for index, (path, title, icon, section) in enumerate(available_pages()):
    sections.setdefault(section, []).append(st.Page(path, title=title, icon=icon, default=index == 0))

st.navigation(sections, position="sidebar").run()

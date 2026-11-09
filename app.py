"""Fieldnotes entry point: grouped navigation for candidates and developer tools."""

import streamlit as st

from interview_app.navigation import available_pages

st.set_page_config(page_title="Fieldnotes | Interview practice", page_icon=":material/graphic_eq:", layout="wide")

sections: dict[str, list] = {}
for index, (path, title, icon, section) in enumerate(available_pages()):
    sections.setdefault(section, []).append(st.Page(path, title=title, icon=icon, default=index == 0))

st.navigation(sections, position="sidebar").run()

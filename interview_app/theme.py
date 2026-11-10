"""Visual style shared by every page: deep green + lime accent, white cards on a soft background.

Colours, fonts and radii live in .streamlit/config.toml. The few looks the theme cannot express
(a dark green banner, white cards, a lime panel, the lime highlight on the active menu item) are
added here with CSS that only targets containers created with a known ``key`` (Streamlit gives
them the class ``st-key-<key>``), plus the sidebar link marked ``aria-current="page"``.
"""

import streamlit as st

GREEN = "#1F5130"
GREEN_LIGHT = "#2E6B3F"
LIME = "#D9F27E"
LIME_SOFT = "#ECF8C6"
CARD_BORDER = "#E1E7D8"

STYLES = f"""<style>
/* Metric values never wrap and are cut off with "..." in narrow columns (e.g. "$0.000257").
   Size each value to its own box instead, and let word values wrap at spaces. */
[data-testid="stMetric"] {{ container-type: inline-size; }}
[data-testid="stMetricValue"] {{ font-size: clamp(1.1rem, 15cqi, 2.25rem); line-height: 1.2; }}
[data-testid="stMetricValue"], [data-testid="stMetricValue"] *,
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] * {{ white-space: normal !important; overflow: visible !important; text-overflow: clip !important; }}

/* Dark green banner (page headers, feature card). */
[class*="st-key-hero"] {{
  background: linear-gradient(135deg, {GREEN} 0%, {GREEN_LIGHT} 100%);
  border-radius: 1.1rem; padding: 1.5rem 1.75rem;
}}
[class*="st-key-hero"] h1, [class*="st-key-hero"] h1 *, [class*="st-key-hero"] h2, [class*="st-key-hero"] h3,
[class*="st-key-hero"] h4, [class*="st-key-hero"] h4 *, [class*="st-key-hero"] p, [class*="st-key-hero"] strong {{ color: #FFFFFF; }}
/* Captions are dimmed with opacity, which turns them green-grey on the banner: use solid light text instead. */
[class*="st-key-hero"] [data-testid="stCaptionContainer"] {{ opacity: 1; }}
[class*="st-key-hero"] [data-testid="stCaptionContainer"], [class*="st-key-hero"] [data-testid="stCaptionContainer"] * {{ color: #DCE9D5 !important; }}
[class*="st-key-hero"] [data-testid="stPageLink-NavLink"] {{ background: {LIME}; border-radius: 0.6rem; padding: 0.15rem 0.75rem; }}
[class*="st-key-hero"] [data-testid="stPageLink-NavLink"] * {{ color: {GREEN} !important; font-weight: 600; }}

/* White cards on the soft page background. */
[class*="st-key-card"] {{
  background: #FFFFFF; border: 1px solid {CARD_BORDER}; border-radius: 1rem; padding: 1rem 1.15rem;
  box-shadow: 0 1px 2px rgba(23, 37, 27, 0.04);
}}

/* Bordered panels on every page (created with panel()): white, like cards in the reference design. */
[class*="st-key-panel_"] {{ background: #FFFFFF; box-shadow: 0 1px 2px rgba(23, 37, 27, 0.04); border-color: {CARD_BORDER} !important; }}

/* Banner titles a step smaller than the default page title. */
[class*="st-key-hero"] h1 {{ font-size: 2.1rem; }}

/* Selected option in segmented controls and pills: lime, like the active items in the reference. */
section.main button[aria-checked="true"], [data-testid="stMain"] button[aria-checked="true"] {{
  background: {LIME} !important; border-color: #B9D95A !important; color: {GREEN} !important; font-weight: 600;
}}

/* Lime panel (sidebar model box, highlights). */
[class*="st-key-lime"] {{ background: {LIME_SOFT}; border: 1px solid #D5EA9C; border-radius: 1rem; padding: 0.85rem 1rem; }}

/* Active page in the sidebar menu: lime pill, like the reference design. */
[data-testid="stSidebarNavLink"][aria-current="page"] {{ background: {LIME}; }}
[data-testid="stSidebarNavLink"][aria-current="page"] * {{ color: {GREEN} !important; font-weight: 600; }}
</style>"""


def apply_styles() -> None:
    st.session_state["_panel_seq"] = 0  # panel() numbers its containers from 0 on every run
    st.html(STYLES)


def panel(**kwargs):
    """A white bordered panel. Same arguments as st.container; a unique key is added automatically."""
    seq = st.session_state.get("_panel_seq", 0)
    st.session_state["_panel_seq"] = seq + 1
    return st.container(key=f"panel_{seq}", **kwargs)


def hero(name: str, **kwargs):
    """Dark green banner. ``name`` must be unique on the page."""
    return st.container(key=f"hero_{name}", **kwargs)


def card(name: str, **kwargs):
    """White card container. ``name`` must be unique on the page."""
    return st.container(key=f"card_{name}", **kwargs)


def lime(name: str, **kwargs):
    """Soft lime panel. ``name`` must be unique on the page."""
    return st.container(key=f"lime_{name}", **kwargs)

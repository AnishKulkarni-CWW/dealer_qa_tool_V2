"""
SaaS/Startup visual theme for the Dealer Panel QA Tool.

This module ONLY changes appearance (CSS injected via st.markdown, plus
two small opt-in layout helpers — section_start()/section_end() — that
wrap existing content in a styled <div>). It does not add, remove, or
alter any widget, any return value, any session_state key, or any control
flow anywhere else in the app. app.py's logic is completely untouched by
this file's existence; app.py only gained two extra, purely-cosmetic
calls around its existing st.subheader() blocks (see THEME_CHANGES.md).

Usage in app.py (added once, near the top, right after st.set_page_config):

    from modules import theme
    theme.inject()

Design tokens (see inline comments for the reasoning behind each choice):
  - Background:      cool slate-white, not stark white or a gradient
  - Accent:           confident indigo — the standard "trustworthy SaaS
                       dashboard" blue-violet (Linear/Vercel/Stripe-adjacent)
  - Semantic colors:  success / warning / danger map 1:1 onto this app's
                       existing Pass / Warn / Fail vocabulary
  - Type:             Inter throughout — a QA tool is read all day, so
                       legibility and restraint beat personality here

--------------------------------------------------------------------------
Section cards (added)
--------------------------------------------------------------------------
Every distinct report section (Content QA, Exact Match QA, Styling QA,
Advanced QA, the Excel Report) now renders inside its own bordered,
shadowed "card" with a colored top accent strip and a small eyebrow label
— the same visual grammar the hero banner already used, just applied
consistently to every section instead of only the page header. This is
pure CSS + a thin div wrapper: section_start(kind, label) opens the
styled div (with an eyebrow), the caller renders its existing widgets
exactly as before, then section_end() closes the div. No widget inside
the section changes in any way.

Five "kind" values, one accent per section family, chosen from colors
already in this palette (no new hues introduced):
  - "content"  -> accent (indigo)   — Content QA
  - "exact"    -> a violet-leaning accent variant — Exact Match QA
  - "style"    -> warning (amber)   — Styling QA
  - "advanced" -> a teal accent     — Advanced QA
  - "report"   -> success (green)   — Consolidated Excel QA Report
  - "neutral"  -> border-strong grey — generic/utility sections
"""

import base64
from pathlib import Path

import streamlit as st


# =========================================================
# Design tokens
# =========================================================

_CSS_VARS = """:root {
    --bg: #F8FAFC;
    --surface: #FFFFFF;
    --surface-raised: #FFFFFF;
    --border: #E2E8F0;
    --border-strong: #CBD5E1;

    --text: #0F172A;
    --text-muted: #64748B;
    --text-faint: #94A3B8;

    --accent: #4F46E5;
    --accent-hover: #4338CA;
    --accent-bg: #D6D2F9;
    --accent-border: #C7D2FE;

    --success: #059669;
    --success-bg: #B9F3D9;
    --success-border: #A7F3D0;

    --warning: #D97706;
    --warning-bg: #FDE9B8;
    --warning-border: #FDE68A;

    --danger: #DC2626;
    --danger-bg: #FBC8C8;
    --danger-border: #FECACA;

    /* Section-card accents — additions beyond the existing accent/
       success/warning/danger set, used ONLY as top-border/eyebrow colors
       on section cards, so every recurring section family (Content /
       Exact Match / Styling / Advanced / Report, plus the input-setup
       cards like Excel & Mode / Email Input / Master JPG / Master PDF /
       Master HTML ZIP) reads as visually distinct at a glance without
       introducing an unrelated, chaotic palette — every added hue still
       sits in the same restrained, professional family.
       (*_bg values darkened from their original very-pale tints per
       request, so each section's background tint is clearly visible
       against a plain white page background rather than nearly blending
       into it.) */
    --section-violet: #7C3AED;
    --section-violet-bg: #DFD5FB;
    --section-teal: #0D9488;
    --section-teal-bg: #B7EEE7;
    --section-rose: #E11D74;
    --section-rose-bg: #FBCFE3;
    --section-gold: #B45309;
    --section-gold-bg: #FDE9B8;
    --section-slate-blue: #2563EB;
    --section-slate-blue-bg: #C6DCFC;
    --neutral-section-bg: #DDE4EC;

    --shadow-sm: 0 1px 2px rgba(15, 23, 42, 0.06);
    --shadow-md: 0 4px 12px rgba(15, 23, 42, 0.08);
    --shadow-lg: 0 12px 28px rgba(15, 23, 42, 0.10);

    --radius-sm: 6px;
    --radius-md: 10px;
    --radius-lg: 14px;

    --font: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}"""


_GLOBAL_CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"] {
    font-family: var(--font) !important;
}

/* ---- Page shell ---- */
/* Flat white body background — per request, the diagonal wash was
   competing with (and muddying) the section cards' own background
   tints, making it harder to tell one card's color apart from another
   at a glance. A plain white page now makes every section card's tint
   read cleanly against a neutral backdrop. */
.stApp {
    background: #FFFFFF !important;
    background-attachment: fixed !important;
}
header[data-testid="stHeader"] {
    background: transparent !important;
}
.block-container {
    max-width: 1200px !important;
    padding-top: 1.5rem !important;
    padding-bottom: 3rem !important;
}

/* ---- Base text contrast ---- */
.stMarkdown p, .stMarkdown span, .stMarkdown div,
.stMarkdown h1, .stMarkdown h2, .stMarkdown h3, .stMarkdown h4,
div[data-testid="stMarkdownContainer"] p {
    color: var(--text) !important;
}
.stCaption, [data-testid="stCaptionContainer"] {
    color: var(--text-muted) !important;
}

/* ---- App title / hero band ---- */
.qa-hero {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 22px 26px;
    margin-bottom: 22px;
    box-shadow: var(--shadow-sm);
}
.qa-hero-eyebrow {
    color: var(--accent);
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-bottom: 6px;
}
.qa-hero-title {
    color: var(--text);
    font-size: 1.5rem;
    font-weight: 800;
    letter-spacing: -0.01em;
    line-height: 1.2;
    margin-bottom: 4px;
}
.qa-hero-subtitle {
    color: var(--text-muted);
    font-size: 0.86rem;
    line-height: 1.5;
    max-width: 640px;
}
.qa-hero-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: var(--accent-bg);
    color: var(--accent);
    border: 1px solid var(--accent-border);
    border-radius: 999px;
    padding: 7px 14px;
    font-size: 0.72rem;
    font-weight: 700;
    white-space: nowrap;
}

/* ---- Section headers (st.subheader / st.header used throughout results) ---- */
.stApp h1 {
    color: var(--text) !important;
    font-weight: 800 !important;
    letter-spacing: -0.01em !important;
}
.stApp h2 {
    color: var(--text) !important;
    font-weight: 700 !important;
    font-size: 1.15rem !important;
    letter-spacing: -0.005em !important;
    padding-bottom: 8px !important;
    margin-top: 4px !important;
    border-bottom: 1px solid var(--border) !important;
}
.stApp h3 {
    color: var(--text) !important;
    font-weight: 700 !important;
    font-size: 1.02rem !important;
}

/* ---- Sidebar ---- */
section[data-testid="stSidebar"] {
    background: var(--surface) !important;
    border-right: 1px solid var(--border) !important;
}
section[data-testid="stSidebar"] .stMarkdown p,
section[data-testid="stSidebar"] label p,
section[data-testid="stSidebar"] label span {
    color: var(--text) !important;
}
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 {
    color: var(--text) !important;
    font-weight: 700 !important;
}
section[data-testid="stSidebar"] .stCaption {
    color: var(--text-muted) !important;
}

/* ---- Buttons ---- */
div[data-testid="stButton"] button[kind="primary"],
div[data-testid="stButton"] button[data-testid="stBaseButton-primary"] {
    background: var(--accent) !important;
    color: #FFFFFF !important;
    border: none !important;
    border-radius: var(--radius-sm) !important;
    font-weight: 600 !important;
    font-size: 0.88rem !important;
    padding: 10px 18px !important;
    box-shadow: var(--shadow-sm) !important;
    transition: background 0.15s ease, box-shadow 0.15s ease !important;
}
div[data-testid="stButton"] button[kind="primary"]:hover,
div[data-testid="stButton"] button[data-testid="stBaseButton-primary"]:hover {
    background: var(--accent-hover) !important;
    box-shadow: var(--shadow-md) !important;
}
div[data-testid="stButton"] button[kind="primary"] *,
div[data-testid="stButton"] button[data-testid="stBaseButton-primary"] * {
    color: #FFFFFF !important;
}

button[data-testid="stBaseButton-secondary"],
div[data-testid="stDownloadButton"] button {
    background: var(--surface) !important;
    color: var(--text) !important;
    border: 1px solid var(--border-strong) !important;
    border-radius: var(--radius-sm) !important;
    font-weight: 600 !important;
    font-size: 0.85rem !important;
    box-shadow: none !important;
}
button[data-testid="stBaseButton-secondary"]:hover,
div[data-testid="stDownloadButton"] button:hover {
    border-color: var(--accent) !important;
    color: var(--accent) !important;
}

/* ---- File uploader ---- */
div[data-testid="stFileUploader"] {
    background: var(--surface) !important;
    border: 1.5px dashed var(--border-strong) !important;
    border-radius: var(--radius-md) !important;
    padding: 14px !important;
    transition: border-color 0.15s ease !important;
}
div[data-testid="stFileUploader"]:hover {
    border-color: var(--accent) !important;
}
div[data-testid="stFileUploader"] section {
    background: transparent !important;
    border: none !important;
}
div[data-testid="stFileUploader"] label p,
div[data-testid="stFileUploader"] label span {
    color: var(--text) !important;
    font-weight: 600 !important;
}
div[data-testid="stFileUploader"] small {
    color: var(--text-muted) !important;
}
div[data-testid="stFileUploader"] button {
    background: var(--surface) !important;
    color: var(--text) !important;
    border: 1px solid var(--border-strong) !important;
    border-radius: var(--radius-sm) !important;
    font-size: 0.78rem !important;
}
div[data-testid="stFileUploader"] button:hover {
    border-color: var(--accent) !important;
    color: var(--accent) !important;
}

/* ---- Metrics (st.metric — used for Total/Present/Missing, Passed/Warn/Failed) ---- */
[data-testid="stMetric"] {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius-md) !important;
    padding: 14px 18px !important;
    box-shadow: var(--shadow-sm) !important;
}
[data-testid="stMetricValue"] {
    color: var(--text) !important;
    font-weight: 800 !important;
}
[data-testid="stMetricLabel"] {
    color: var(--text-muted) !important;
    font-weight: 600 !important;
    font-size: 0.78rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.03em !important;
}

/* ---- Alerts (st.success / st.warning / st.error / st.info) ---- */
div[data-testid="stAlert"] {
    border-radius: var(--radius-md) !important;
    border: 1px solid var(--border) !important;
    box-shadow: var(--shadow-sm) !important;
    padding: 12px 16px !important;
}
div[data-testid="stAlert"] p {
    font-size: 0.86rem !important;
}

/* ---- Tabs (Body QA / Banner QA / Summary) ---- */
div[data-testid="stTabs"] button[data-baseweb="tab"] {
    color: var(--text-muted) !important;
    font-weight: 600 !important;
    font-size: 0.88rem !important;
}
div[data-testid="stTabs"] button[aria-selected="true"] {
    color: var(--accent) !important;
}
div[data-testid="stTabs"] [data-baseweb="tab-highlight"] {
    background-color: var(--accent) !important;
}
div[data-testid="stTabs"] [data-baseweb="tab-border"] {
    background-color: var(--border) !important;
}

/* ---- Expanders (Pass rows, Advanced QA options) ---- */
div[data-testid="stExpander"] {
    border: 1px solid var(--border) !important;
    border-radius: var(--radius-md) !important;
    box-shadow: none !important;
    background: var(--surface) !important;
    overflow: hidden;
}
div[data-testid="stExpander"] summary {
    background: var(--surface) !important;
    color: var(--text) !important;
    font-weight: 600 !important;
    font-size: 0.86rem !important;
}
div[data-testid="stExpander"] summary:hover {
    background: var(--accent-bg) !important;
}
div[data-testid="stExpander"] summary svg {
    fill: var(--text-muted) !important;
}

/* ---- Dividers ---- */
hr, div[data-testid="stDivider"] {
    border-color: var(--border) !important;
    margin: 1.4rem 0 !important;
}

/* ---- Text inputs / textareas / number inputs / selects ---- */
div[data-testid="stTextInput"] input,
div[data-testid="stTextArea"] textarea,
div[data-testid="stNumberInput"] input,
div[data-baseweb="select"] > div {
    background: var(--surface) !important;
    color: var(--text) !important;
    border-color: var(--border-strong) !important;
    border-radius: var(--radius-sm) !important;
}
div[data-testid="stTextInput"] input:focus,
div[data-testid="stTextArea"] textarea:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 1px var(--accent) !important;
}
label[data-testid="stWidgetLabel"] p {
    color: var(--text) !important;
    font-weight: 600 !important;
    font-size: 0.82rem !important;
}

/* ---- Checkboxes / radio / toggle ---- */
div[data-testid="stCheckbox"] label p,
div[data-testid="stRadio"] label p {
    color: var(--text) !important;
}
/* Streamlit's native radio control renders its actual <input> visually
   hidden (clip-rect, for accessibility) and draws the visible dot via
   TWO nested divs on the selected option: an outer "ring" div (which
   Streamlit gives its own red rgb(255,75,75) background by default) and
   an inner "dot" div. Confirmed via computed-style inspection of the
   live DOM — targeting only the inner dot left the outer red ring
   showing around its edge, so both layers need the theme color. */
label[data-testid="stRadioOption"][data-selected="true"] div[class*="etak9234"],
label[data-testid="stRadioOption"][data-selected="true"] > div > div > div:first-child {
    background-color: var(--accent) !important;
}
label[data-testid="stRadioOption"][data-selected="true"] div[class*="etak9235"],
label[data-testid="stRadioOption"][data-selected="true"] > div > div > div:first-child > div {
    background-color: var(--accent) !important;
}

/* ---- Dataframes ---- */
div[data-testid="stDataFrame"] {
    border: 1px solid var(--border) !important;
    border-radius: var(--radius-md) !important;
    box-shadow: var(--shadow-sm) !important;
}

/* ---- Dialog (st.dialog — full QA table popup) ---- */
div[data-testid="stDialog"] div[role="dialog"] {
    border-radius: var(--radius-lg) !important;
}

/* ---- QA results table (rendered by modules/results_ui.py) ---- */
.qa-table-wrap {
    background: #FFFFFF !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius-md) !important;
    box-shadow: var(--shadow-sm) !important;
}
.qa-table-wrap table {
    font-family: var(--font) !important;
}
.qa-table-wrap thead th {
    background: #F1F5F9 !important;
    color: var(--text-muted) !important;
    font-size: 0.72rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.03em !important;
    border-bottom: 1px solid var(--border) !important;
}
.qa-table-wrap tbody td {
    color: var(--text) !important;
    font-size: 0.86rem !important;
    border-bottom: 1px solid var(--border) !important;
}
.qa-row-pass  { background-color: var(--success-bg) !important; border-left: 3px solid var(--success) !important; }
.qa-row-warn  { background-color: var(--warning-bg) !important; border-left: 3px solid var(--warning) !important; }
.qa-row-fail  { background-color: var(--danger-bg)  !important; border-left: 3px solid var(--danger)  !important; }
.qa-row-none  { border-left: 3px solid transparent !important; }

/* ---- Spinner overlay ---- */
div[data-testid="stSpinner"] {
    color: var(--accent) !important;
}

/* =========================================================
   Section cards
   ---------------------------------------------------------
   Wraps a whole section (Content QA / Exact Match QA / Styling
   QA / Advanced QA / Excel Report / any generic block) in a
   bordered, shadowed card with a colored top strip and a small
   uppercase eyebrow, so the eye can tell at a glance where one
   section ends and the next begins — the exact problem being
   solved is long pages where every section shared the same flat
   background and only a thin 1px divider separated them.

   Mechanism: theme.section_start(kind, label) opens a genuine
   st.container(border=True) — a first-party, version-stable
   Streamlit primitive that produces a real
   div[data-testid="stVerticalBlockBorderWrapper"] wrapping
   everything rendered inside it — and, as the very first thing
   inside that container, renders a tiny invisible marker div
   carrying a per-kind class (e.g. qa-marker-content). The CSS
   below uses :has() (supported in every evergreen browser) to
   reach from that marker back up to its nearest
   stVerticalBlockBorderWrapper ancestor and color IT, so the
   whole card — not just the marker — gets the accent. Nothing
   about this depends on Streamlit's auto-generated emotion-cache
   class names (the exact fragility this file's own radio-button
   CSS already had to work around), and nothing about it requires
   a Streamlit version newer than this project's own
   requirements.txt floor (st.container(border=True) predates it).
   ========================================================= */
/* -----------------------------------------------------------------
   IMPORTANT — testid correction (verified against Streamlit's own
   source, not guessed from screenshots):
   Older Streamlit versions wrapped st.container(border=True) in an
   OUTER div[data-testid="stVerticalBlockBorderWrapper"] with an INNER
   div[data-testid="stVerticalBlock"] doing the actual bordering. This
   project's requirements.txt floor (Streamlit >= 1.31) plus the
   version actually installed at test time no longer has that outer
   wrapper at all — st.container(border=True) renders the border
   directly on div[data-testid="stVerticalBlock"] (confirmed by
   reading Streamlit's own frontend source, ContainerContentsWrapper /
   StyledFlexContainerBlock in Block.tsx: the border style is applied
   straight onto the element carrying data-testid="stVerticalBlock").
   Every rule below previously only matched
   "stVerticalBlockBorderWrapper", which no longer exists in the
   installed Streamlit version — so NONE of these rules ever matched
   anything, which is why the border never visibly changed no matter
   how bold/black it was set. Every selector now targets BOTH testids
   (comma-separated) so this keeps working across older AND current
   Streamlit versions, whichever one is actually installed. */
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div [data-testid="stMarkdownContainer"] .qa-marker),
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div [data-testid="stMarkdownContainer"] .qa-marker) > div[data-testid="stVerticalBlock"],
div[data-testid="stVerticalBlock"]:has(> div [data-testid="stMarkdownContainer"] .qa-marker) {
    border-radius: var(--radius-lg) !important;
    box-shadow: var(--shadow-md) !important;
    border-top-width: 2px !important;
    border-top-style: solid !important;
    border-top-color: #000000 !important;
    border-right-width: 2px !important;
    border-right-style: solid !important;
    border-right-color: #000000 !important;
    border-bottom-width: 2px !important;
    border-bottom-style: solid !important;
    border-bottom-color: #000000 !important;
    border-left-width: 2px !important;
    border-left-style: solid !important;
    border-left-color: #000000 !important;
    padding: 14px 16px 10px 16px !important;
    margin: 22px 0 26px 0 !important;
}
.qa-marker { display: none; }

.qa-section-eyebrow {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    font-size: 0.92rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    padding: 5px 14px;
    border-radius: 999px;
    margin: 2px 0 12px 0;
}
.qa-section-eyebrow-dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    flex-shrink: 0;
}

/* Kind: content (indigo, matches the primary accent) */
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div [data-testid="stMarkdownContainer"] .qa-marker-content),
div[data-testid="stVerticalBlock"]:has(> div [data-testid="stMarkdownContainer"] .qa-marker-content) {
    background: var(--accent-bg) !important;
}
.qa-section-eyebrow.qa-eyebrow-content { background: #FFFFFF; color: var(--accent); }
.qa-eyebrow-content .qa-section-eyebrow-dot { background: var(--accent); }

/* Kind: email (slate-blue — a cooler, distinct blue from the primary
   indigo accent, so the "Email Input" card doesn't read as identical
   to the "Excel & Mode" card right above it even though both are in
   the same broad "input setup" family) */
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div [data-testid="stMarkdownContainer"] .qa-marker-email),
div[data-testid="stVerticalBlock"]:has(> div [data-testid="stMarkdownContainer"] .qa-marker-email) {
    background: var(--section-slate-blue-bg) !important;
}
.qa-section-eyebrow.qa-eyebrow-email { background: #FFFFFF; color: var(--section-slate-blue); }
.qa-eyebrow-email .qa-section-eyebrow-dot { background: var(--section-slate-blue); }

/* Kind: exact-match (violet — distinct from but adjacent to indigo,
   signals "a stricter pass over the same content" relationship) */
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div [data-testid="stMarkdownContainer"] .qa-marker-exact),
div[data-testid="stVerticalBlock"]:has(> div [data-testid="stMarkdownContainer"] .qa-marker-exact) {
    background: var(--section-violet-bg) !important;
}
.qa-section-eyebrow.qa-eyebrow-exact { background: #FFFFFF; color: var(--section-violet); }
.qa-eyebrow-exact .qa-section-eyebrow-dot { background: var(--section-violet); }

/* Kind: style (amber — echoes the Warn semantic color, since styling
   issues are so often warn-severity in this app) */
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div [data-testid="stMarkdownContainer"] .qa-marker-style),
div[data-testid="stVerticalBlock"]:has(> div [data-testid="stMarkdownContainer"] .qa-marker-style) {
    background: var(--warning-bg) !important;
}
.qa-section-eyebrow.qa-eyebrow-style { background: #FFFFFF; color: var(--warning); }
.qa-eyebrow-style .qa-section-eyebrow-dot { background: var(--warning); }

/* Kind: advanced (teal — a clearly separate hue signals this whole
   block is an optional, opt-in tier of checks layered on top). Used
   for the Manual Text Mode card and the results-side "Advanced QA"
   section. */
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div [data-testid="stMarkdownContainer"] .qa-marker-advanced),
div[data-testid="stVerticalBlock"]:has(> div [data-testid="stMarkdownContainer"] .qa-marker-advanced) {
    background: var(--section-teal-bg) !important;
}
.qa-section-eyebrow.qa-eyebrow-advanced { background: #FFFFFF; color: var(--section-teal); }
.qa-eyebrow-advanced .qa-section-eyebrow-dot { background: var(--section-teal); }

/* Kind: master-b (rose — used for Manual Body Comparison and Master
   PDF, so these two sibling cards don't share the exact same tint as
   their neighbours Manual Text Mode / Master Image (JPG), which
   otherwise would have made every "advanced" input-setup card look
   identical once Master Assets was split into individual cards) */
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div [data-testid="stMarkdownContainer"] .qa-marker-master-b),
div[data-testid="stVerticalBlock"]:has(> div [data-testid="stMarkdownContainer"] .qa-marker-master-b) {
    background: var(--section-rose-bg) !important;
}
.qa-section-eyebrow.qa-eyebrow-master-b { background: #FFFFFF; color: var(--section-rose); }
.qa-eyebrow-master-b .qa-section-eyebrow-dot { background: var(--section-rose); }

/* Kind: master-c (gold — used for Master HTML (ZIP), the third and
   final Master-asset card, completing a distinct rotation of teal /
   rose / gold across the five sibling "master mode" cards so each one
   is identifiable at a glance without introducing an unrelated,
   chaotic palette) */
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div [data-testid="stMarkdownContainer"] .qa-marker-master-c),
div[data-testid="stVerticalBlock"]:has(> div [data-testid="stMarkdownContainer"] .qa-marker-master-c) {
    background: var(--section-gold-bg) !important;
}
.qa-section-eyebrow.qa-eyebrow-master-c { background: #FFFFFF; color: var(--section-gold); }
.qa-eyebrow-master-c .qa-section-eyebrow-dot { background: var(--section-gold); }

/* Kind: report (success green — this is the "you're done, here's your
   deliverable" section) */
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div [data-testid="stMarkdownContainer"] .qa-marker-report),
div[data-testid="stVerticalBlock"]:has(> div [data-testid="stMarkdownContainer"] .qa-marker-report) {
    background: var(--success-bg) !important;
}
.qa-section-eyebrow.qa-eyebrow-report { background: #FFFFFF; color: var(--success); }
.qa-eyebrow-report .qa-section-eyebrow-dot { background: var(--success); }

/* Kind: neutral (generic utility wrapper, e.g. per-job header block) */
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div [data-testid="stMarkdownContainer"] .qa-marker-neutral),
div[data-testid="stVerticalBlock"]:has(> div [data-testid="stMarkdownContainer"] .qa-marker-neutral) {
    background: var(--neutral-section-bg) !important;
}
.qa-section-eyebrow.qa-eyebrow-neutral { background: #FFFFFF; color: var(--text-muted); }
.qa-eyebrow-neutral .qa-section-eyebrow-dot { background: var(--text-faint); }


/* A section card's OWN st.subheader/h2 should sit flush against the
   card, without the global h2 bottom-border rule fighting the card's
   own border — the card boundary already does that job. */
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div [data-testid="stMarkdownContainer"] .qa-marker) h2,
div[data-testid="stVerticalBlock"]:has(> div [data-testid="stMarkdownContainer"] .qa-marker) h2 {
    border-bottom: none !important;
    padding-bottom: 0 !important;
    margin-top: 0 !important;
}
/* (Old-Streamlit-only "double padding" rule removed — the base card
   rule above now sets padding directly and unconditionally, since it
   targets the real bordered element in the currently installed
   Streamlit version. Kept as a comment for anyone diffing history.) */

/* =========================================================
   Outer page-level GROUPS (theme.group()) — exactly two of these on
   the page: one wrapping every input/upload section() card (Excel &
   Mode through Master HTML ZIP), one wrapping every results section()
   card (per-job Content QA / Exact Match QA / Styling QA / Advanced QA
   / Excel Report). Same real-testid fix as the section-card rule above
   (targets div[data-testid="stVerticalBlock"], the element Streamlit
   actually puts the border on in the installed version, plus the older
   stVerticalBlockBorderWrapper testid as a harmless fallback) — but
   with its own marker class (qa-group-marker) so this outer border
   never collides with the inner per-card rules; a group card CONTAINS
   several section() cards, each of which keeps its own independent
   border/background exactly as already styled above.
   ========================================================= */
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div [data-testid="stMarkdownContainer"] .qa-group-marker),
div[data-testid="stVerticalBlock"]:has(> div [data-testid="stMarkdownContainer"] .qa-group-marker) {
    border-radius: var(--radius-lg) !important;
    box-shadow: var(--shadow-lg) !important;
    border-top-width: 2px !important;
    border-top-style: solid !important;
    border-top-color: #000000 !important;
    border-right-width: 2px !important;
    border-right-style: solid !important;
    border-right-color: #000000 !important;
    border-bottom-width: 2px !important;
    border-bottom-style: solid !important;
    border-bottom-color: #000000 !important;
    border-left-width: 2px !important;
    border-left-style: solid !important;
    border-left-color: #000000 !important;
    background: #FFFFFF !important;
    padding: 18px 18px 14px 18px !important;
    margin: 26px 0 32px 0 !important;
}
.qa-group-marker { display: none; }
.qa-group-label {
    display: inline-flex;
    align-items: center;
    font-size: 3.05rem;
    font-weight: 800;
    letter-spacing: 0.02em;
    text-transform: uppercase;
    color: var(--text);
    padding: 4px 0 14px 2px;
}

/* =========================================================
   Sticky page-level top navigation bar
   ---------------------------------------------------------
   theme.top_nav() renders its st.tabs() call as a sibling of a tiny
   invisible marker (.qa-topnav-marker), both inside one shared
   container — see top_nav()'s own docstring for why this scoping is
   necessary (there is a second, unrelated st.tabs() call later on the
   page for the Body QA / Banner QA / Summary results tabs, which must
   NOT be affected). The CSS below uses :has() to reach from that
   marker to their shared parent block and apply the sticky/styled
   treatment ONLY to the tab strip that sits alongside the marker.

   The strip sticks to the very top of the browser viewport (not a
   sidebar's own internal scroll area, since these tabs now live on the
   main page) as the person scrolls down through a long report, so
   jumping to a different input section stays a single click away
   instead of requiring a scroll back to the top of the page.
   ========================================================= */
div[data-testid="stVerticalBlock"]:has(> div [data-testid="stMarkdownContainer"] .qa-topnav-marker) div[data-testid="stTabs"] > div[data-baseweb="tab-list"] {
    position: sticky !important;
    top: 0 !important;
    z-index: 999 !important;
    background: var(--surface) !important;
    border-bottom: 1px solid var(--border) !important;
    border-radius: var(--radius-md) var(--radius-md) 0 0 !important;
    box-shadow: var(--shadow-sm) !important;
    padding: 6px 10px 0 10px !important;
    margin-bottom: 4px !important;
    gap: 4px !important;
}
div[data-testid="stVerticalBlock"]:has(> div [data-testid="stMarkdownContainer"] .qa-topnav-marker) div[data-testid="stTabs"] button[data-baseweb="tab"] {
    font-size: 0.92rem !important;
    font-weight: 600 !important;
    padding: 12px 20px !important;
}
.qa-topnav-marker { display: none; }
</style>"""


def _loader_data_uri() -> str:
    """Base64-encodes loader.gif (if present in the project root) into a
    data: URI so a custom spinner overlay can reference it without any
    network dependency. Returns "" if the file isn't found — callers must
    handle that gracefully (never a hard failure)."""
    for candidate in (Path("loader.gif"), Path(__file__).resolve().parent.parent / "loader.gif"):
        if candidate.exists():
            b64 = base64.b64encode(candidate.read_bytes()).decode("utf-8")
            return f"data:image/gif;base64,{b64}"
    return ""


def inject() -> None:
    """Injects the full theme (CSS variables + component overrides) once.
    Call this exactly once, near the top of app.py, right after
    st.set_page_config(). Safe to call multiple times (Streamlit dedupes
    identical <style> blocks visually), but one call is all that's needed.
    """
    st.markdown(f"<style>{_CSS_VARS}</style>", unsafe_allow_html=True)
    st.markdown(_GLOBAL_CSS, unsafe_allow_html=True)


def render_hero(title: str, subtitle: str, badge: str) -> None:
    """Renders the branded hero header used at the top of the app, in
    place of a plain st.title()/st.caption() pair. Purely presentational —
    takes no app state and returns nothing for app.py to store."""
    st.markdown(
        f"""
        <div class="qa-hero">
            <div>
                <div class="qa-hero-eyebrow">Dealer Panel QA</div>
                <div class="qa-hero-title">{title}</div>
                <div class="qa-hero-subtitle">{subtitle}</div>
            </div>
            <div class="qa-hero-badge">{badge}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# =========================================================
# Section cards (opt-in layout helper)
# =========================================================

_SECTION_KIND_ICONS = {
    "content": "📋",
    "email": "📧",
    "exact": "🎯",
    "style": "🎨",
    "advanced": "🧪",
    "master-b": "📄",
    "master-c": "🗂️",
    "report": "📊",
    "neutral": "▫️",
}
_SECTION_KIND_LABELS = {
    "content": "Content QA",
    "email": "Email Input",
    "exact": "Exact Match QA",
    "style": "Styling QA",
    "advanced": "Advanced QA",
    "master-b": "Master Asset",
    "master-c": "Master Asset",
    "report": "Report",
    "neutral": "Section",
}

_section_counter = {"n": 0}


def section(kind: str, label: str = ""):
    """
    Opens a visually distinct "section card" and returns it as a context
    manager — used exactly like st.container():

        with theme.section("content", "Content QA"):
            st.subheader("Content QA")
            ...existing widgets, completely unchanged...

    `kind` picks the accent color family (see the qa-section-eyebrow CSS
    rules above): "content" | "email" | "exact" | "style" | "advanced" |
    "master-b" | "master-c" | "report" | "neutral". `label` is shown as
    a small eyebrow chip at the top of the card (defaults to a sensible
    label per kind if omitted).

    Implementation note: this wraps a genuine st.container(border=True)
    (see the CSS block's own comment for why this specific primitive was
    chosen over alternatives) — every widget rendered inside the `with`
    block behaves exactly as if it had been rendered with no wrapper at
    all: same widget type, same key, same return value, same
    session_state behavior. This function only adds visual framing
    around EXISTING calls; it never changes what those calls do.
    """
    kind = kind if kind in _SECTION_KIND_ICONS else "neutral"
    _section_counter["n"] += 1
    marker_id = _section_counter["n"]

    box = st.container(border=True)
    with box:
        st.markdown(
            f'<div class="qa-marker qa-marker-{kind}" data-marker-id="{marker_id}"></div>',
            unsafe_allow_html=True,
        )
        chip_label = label or _SECTION_KIND_LABELS.get(kind, "Section")
        icon = _SECTION_KIND_ICONS.get(kind, "▫️")
        st.markdown(
            f'<div class="qa-section-eyebrow qa-eyebrow-{kind}">'
            f'<span class="qa-section-eyebrow-dot"></span>{icon} {chip_label}'
            f'</div>',
            unsafe_allow_html=True,
        )
    return box


# =========================================================
# Page-level group wrapper (opt-in layout helper)
# ---------------------------------------------------------
# Wraps SEVERAL existing section() cards together in one outer bordered
# group — used to give the page exactly two outer borders: one around
# the whole "Inputs / Uploads" area (Excel & Mode through Master HTML
# ZIP) and one around the whole "Results" area (per-job Content QA /
# Exact Match QA / Styling QA / Advanced QA / Excel Report). The
# section() cards rendered INSIDE a group keep their own individual
# borders/colors exactly as before — group() only adds one more,
# visually distinct border around the outside of the whole cluster, the
# same :has()-marker technique section() itself uses, just with its own
# marker class (qa-group-marker) so the CSS for the outer group border
# never collides with or overrides the inner per-section-card rules.
# =========================================================

_group_counter = {"n": 0}


def group(label: str = ""):
    """
    Opens an outer "group" wrapper — used like section():

        with theme.group("Inputs"):
            with theme.section("content", "Excel & Mode"):
                ...
            with theme.section("email", "Email Input"):
                ...

    Renders a genuine st.container(border=True) (same primitive
    section() uses) with an invisible marker as the first child, so the
    CSS can reach it via :has() and draw ONE outer border around
    everything placed inside the `with` block — the individual
    section() cards inside keep rendering with their own borders/colors
    unchanged, nested inside this outer border.
    """
    _group_counter["n"] += 1
    marker_id = _group_counter["n"]
    box = st.container(border=True)
    with box:
        st.markdown(
            f'<div class="qa-group-marker" data-marker-id="{marker_id}"></div>',
            unsafe_allow_html=True,
        )
        if label:
            st.markdown(f'<div class="qa-group-label">{label}</div>', unsafe_allow_html=True)
    return box


# =========================================================
# Page-level top navigation bar (opt-in layout helper)
# =========================================================

def top_nav(tab_labels):
    """
    Renders a page-level, sticky top navigation bar — a normal-website-
    style horizontal tab strip sitting in the main content column, above
    everything else — and returns the same list of tab objects
    st.tabs(tab_labels) would, so callers use it as a drop-in
    replacement:

        ext_top_nav_tabs = theme.top_nav(["📊 Excel & Mode", "🏪 Dealer", "✍️ Manual & Masters"])
        with ext_top_nav_tabs[0]:
            ...existing widgets, completely unchanged...

    Implementation note: this app also has a SECOND, unrelated
    st.tabs() call further down the page (the Body QA / Banner QA /
    Summary results tabs inside Advanced QA) that must NOT become sticky
    or otherwise be affected — a blanket CSS rule targeting every
    div[data-testid="stTabs"] on the page would incorrectly grab that
    one too. To keep the two fully independent, this function renders
    its own tiny invisible marker (the same :has()-based technique
    section() uses above) as a sibling of the st.tabs() call, both
    inside one st.container(); the CSS then uses :has() to reach from
    that marker to their shared parent block and scope the sticky/
    styled treatment to ONLY this specific tabs instance, leaving every
    other st.tabs() call on the page — including the unrelated results
    tabs — completely untouched.
    """
    box = st.container()
    with box:
        st.markdown('<div class="qa-topnav-marker"></div>', unsafe_allow_html=True)
        tabs = st.tabs(tab_labels)
    return tabs

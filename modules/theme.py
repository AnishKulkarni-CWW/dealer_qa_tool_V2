"""
Visual theme — the original colourful card layout.

Every section is a pastel card with a heavy dark border, rounded corners
and a white pill label carrying a coloured dot. Colour is assigned per
section KIND, and the kinds added by the multi-adapt work get their own
colours from the same palette so the new cards sit alongside the old ones
instead of looking bolted on:

    content   lavender    Excel & Mode, Content QA
    email     sky         Email Input
    exact     lavender    Dealer Name Validation, Exact Match QA
    style     amber       Styling QA
    advanced  mint        Manual Text Mode, Master Image, Advanced QA
    master-b  pink        Manual Body Comparison, Master PDF
    master-c  yellow      Master HTML (ZIP)
    routing   peach       Master PDF - Emailer Routing        (new)
    multi     periwinkle  Per-Adapt Masters                   (new)
    neutral   slate       per-email job header
    report    green       Consolidated Excel report

Status colour (Pass green / Warn amber / Fail red) is deliberately kept
separate from the card palette and is only ever used inside result rows.

WHICH ELEMENT GETS THE CARD CHROME
----------------------------------
Which DOM node carries a bordered container moved between Streamlit
releases: up to ~1.4x it was the outer stVerticalBlockBorderWrapper,
1.6x puts it straight on the inner stVerticalBlock. The inner
stVerticalBlock exists in BOTH, so the chrome is attached there and the
legacy outer wrapper is flattened — one consistent card element on every
version instead of a double border on one and none on the other.

`:has(> [data-testid="stElementContainer"] .oq-head)` is what marks a
block as one of ours: .oq-head is rendered as the first element inside
section(), and requiring it under a DIRECT child element container stops
an outer block from also matching a nested card's head.
"""

from __future__ import annotations

import html as _html
from contextlib import contextmanager

import streamlit as st

# --------------------------------------------------------------------------
# Palette
# --------------------------------------------------------------------------

INK = "#12141C"
INK_SOFT = "#2C3140"
MUTED = "#6B7280"
BORDER = "#12141C"          # the heavy card outline
LINE_SOFT = "#E3E7EE"
WHITE = "#FFFFFF"
CANVAS = "#FFFFFF"

BRAND = "#4F46E5"
BRAND_DARK = "#3730A3"

OK = "#166534"
OK_BG = "#DCFCE7"
WARN = "#92400E"
WARN_BG = "#FDECC8"
BAD = "#991B1B"
BAD_BG = "#FBD5D5"

# kind -> (card fill, dot / accent colour)
KINDS = {
    "content":  ("#DDD8FB", "#5B4BE0"),   # lavender
    "email":    ("#D3E6FC", "#1F6FD0"),   # sky
    "exact":    ("#DDD8FB", "#6D28D9"),   # lavender
    "style":    ("#FCE6B0", "#B45309"),   # amber
    "advanced": ("#B6EBDA", "#0F766E"),   # mint
    "master-b": ("#FBD2DF", "#BE185D"),   # pink
    "master-c": ("#FCE3A6", "#A16207"),   # yellow
    "routing":  ("#FBDCC0", "#C2410C"),   # peach   (new)
    "multi":    ("#CFD8FA", "#3730A3"),   # periwinkle (new)
    "neutral":  ("#D8DFE7", "#475569"),   # slate
    "report":   ("#B7EEC9", "#15803D"),   # green
}

# Kind names other code may still pass in, mapped onto the palette above.
_ALIASES = {
    "input": "content",
    "master": "advanced",
    "result": "content",
    "job": "neutral",
}


def _kind(name: str) -> str:
    k = (name or "").strip().lower()
    k = _ALIASES.get(k, k)
    return k if k in KINDS else "neutral"


# --------------------------------------------------------------------------
# CSS
# --------------------------------------------------------------------------

def _css() -> str:
    per_kind = "\n".join(
        f"""
        [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .oq-k-{k}) {{
            background:{fill} !important;
        }}
        .oq-head.oq-k-{k} .oq-dot {{ background:{dot}; }}
        """
        for k, (fill, dot) in KINDS.items()
    )

    return f"""
    <style>
    /* ---------- page ---------- */
    .stApp {{ background:{CANVAS}; }}
    /* Streamlit's toolbar is fixed at the top of the viewport and is
       roughly 60px tall, so the content column must start below it.
       Overriding padding-top with too small a value is what left the
       hero card tucked under the toolbar at the topmost scroll
       position. 4.75rem = 76px clears 60px with a little breathing
       room, and the sticky Run QA bar uses a matching `top` offset. */
    .block-container {{
        padding-top:4.75rem !important;
        padding-bottom:4rem;
        max-width:1400px;
    }}
    header[data-testid="stHeader"] {{
        background:rgba(255,255,255,.92); backdrop-filter:blur(6px);
    }}

    html, body, [class*="css"] {{ color:{INK}; }}

    h1, h2, h3, h4, h5,
    [data-testid="stHeading"] h1, [data-testid="stHeading"] h2,
    [data-testid="stHeading"] h3 {{
        color:{INK} !important; letter-spacing:-0.01em; font-weight:700 !important;
    }}
    h1, [data-testid="stHeading"] h1 {{ font-size:1.5rem !important; }}
    h2, [data-testid="stHeading"] h2 {{ font-size:1.15rem !important; }}
    h3, [data-testid="stHeading"] h3 {{ font-size:1.0rem !important; padding-top:0 !important; }}
    [data-testid="stCaptionContainer"], .stCaption {{ color:{MUTED}; }}

    /* ---------- hero ---------- */
    .oq-hero {{
        background:{WHITE}; border:2px solid {BORDER}; border-radius:14px;
        padding:1.15rem 1.4rem; margin:.25rem 0 1.2rem 0;
        display:flex; align-items:center; justify-content:space-between; gap:1.5rem;
    }}
    .oq-hero-eyebrow {{
        font-size:.66rem; font-weight:800; letter-spacing:.16em;
        text-transform:uppercase; color:{MUTED}; margin-bottom:.3rem;
    }}
    .oq-hero-title {{ font-size:1.45rem; font-weight:750; color:{INK}; line-height:1.2; }}
    .oq-hero-sub {{ font-size:.85rem; color:{MUTED}; margin-top:.35rem; max-width:78ch; line-height:1.5; }}
    .oq-hero-badge {{
        flex:none; font-size:.7rem; font-weight:800; letter-spacing:.09em;
        color:{BRAND}; background:#EEEBFE; border:2px solid {BORDER};
        padding:.35rem .8rem; border-radius:999px; white-space:nowrap;
    }}

    /* ---------- section cards ---------- */
    [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .oq-head) {{
        border:3px solid {BORDER} !important;
        border-radius:14px !important;
        padding:1rem 1.1rem !important;
        box-shadow:none !important;
        overflow:hidden;
    }}
    [data-testid="stVerticalBlockBorderWrapper"]:has([data-testid="stElementContainer"] .oq-head) {{
        background:transparent !important; border:none !important;
        box-shadow:none !important; padding:0 !important;
    }}
    {per_kind}

    .oq-head {{ margin:0 0 .7rem 0; }}
    .oq-pill {{
        display:inline-flex; align-items:center; gap:.45rem;
        background:{WHITE}; border:2px solid {BORDER}; border-radius:999px;
        padding:.24rem .7rem; font-size:.66rem; font-weight:800;
        letter-spacing:.1em; text-transform:uppercase; color:{INK};
    }}
    .oq-dot {{ width:.5rem; height:.5rem; border-radius:50%; display:inline-block; }}

    /* ---------- group heading ---------- */
    .oq-group {{
        font-size:1.5rem; font-weight:800; letter-spacing:.06em;
        text-transform:uppercase; color:{INK};
        padding-bottom:.5rem; border-bottom:3px solid {BORDER};
        margin:.6rem 0 1.1rem 0;
    }}

    /* ---------- sticky action bar ----------
       Holds Run QA so it stays reachable however far down the page you
       have scrolled. `top` clears Streamlit's own sticky toolbar; without
       that offset the two overlap at the topmost scroll position, which
       is exactly the overlap reported against the previous build. */
    /* The action bar is lifted out of the page flow and pinned onto
       Streamlit's own top toolbar - the strip that carries the Deploy
       button - so Run QA and Clear Masters sit in the chrome rather than
       scrolling with the report. `right` stops short of Deploy so the two
       never collide, and the z-index is above Streamlit's header (which
       sits in the 999990s). Being `fixed` it occupies no vertical space,
       which is why the content column keeps its own top padding. */
    [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .oq-sticky) {{
        position:fixed !important;
        top:.55rem;
        left:1.25rem;
        right:11.5rem;
        z-index:999995 !important;
        background:transparent !important;
        border:none !important;
        border-radius:0 !important;
        padding:0 !important;
        margin:0 !important;
        gap:.5rem !important;
        /* Streamlit sets an explicit width on its vertical blocks, which
           overrides the left/right pair and let the bar run past the
           viewport edge and under the Deploy button. */
        width:auto !important;
        max-width:none !important;
        min-width:0 !important;
    }}
    /* Compact enough to sit inside a ~60px toolbar. */
    [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .oq-sticky) .stButton > button {{
        min-height:2.3rem; height:2.3rem; padding:0 .9rem;
        font-size:.85rem; border-width:2px;
    }}
    .oq-sticky {{ display:none; }}

    /* ---------- native disclosure (Passed / Present rows) ----------
       A <details> element rather than a Streamlit widget, so opening it
       is instant and never re-runs the script. */
    details.oq-details {{
        border:2px solid {BORDER}; border-radius:12px; background:{WHITE};
        margin:.5rem 0; overflow:hidden;
    }}
    details.oq-details > summary {{
        cursor:pointer; list-style:none; padding:.55rem .9rem;
        font-weight:650; font-size:.86rem; color:{INK};
        display:flex; align-items:center; gap:.5rem;
    }}
    details.oq-details > summary::-webkit-details-marker {{ display:none; }}
    details.oq-details > summary::before {{
        content:"\\25b8"; font-size:.8rem; transition:transform .15s ease;
    }}
    details.oq-details[open] > summary::before {{ transform:rotate(90deg); }}
    details.oq-details > summary:hover {{ background:#F2F1FE; }}
    .oq-details-body {{ border-top:2px solid {BORDER}; }}
    .oq-details-body .oq-table-wrap {{ border:none; border-radius:0; }}

    /* ---------- collapsible job group ---------- */
    .oq-jobhead {{
        display:flex; align-items:center; gap:.55rem; flex-wrap:wrap;
        font-weight:750; font-size:1.02rem; color:{INK};
    }}
    .oq-jobsub {{ font-size:.82rem; color:{MUTED}; font-weight:500; }}
    .oq-chip {{
        display:inline-block; font-size:.66rem; font-weight:800;
        letter-spacing:.05em; padding:.12rem .45rem; border-radius:6px;
        border:1px solid {BORDER};
    }}
    .oq-chip.ok   {{ color:{OK};   background:#BBF7D0; }}
    .oq-chip.warn {{ color:{WARN}; background:#FDE68A; }}
    .oq-chip.bad  {{ color:{BAD};  background:#FCA5A5; }}

    /* ---------- buttons ---------- */
    .stButton > button {{
        border-radius:10px; font-weight:650; border:2px solid {BORDER};
        background:{WHITE}; color:{INK}; transition:all .12s ease;
    }}
    .stButton > button:hover {{ background:#F2F1FE; color:{BRAND_DARK}; border-color:{BORDER}; }}
    .stButton > button[kind="primary"],
    .stButton > button[data-testid="baseButton-primary"] {{
        background:{BRAND}; border-color:{BORDER}; color:#fff; font-weight:750;
    }}
    .stButton > button[kind="primary"]:hover,
    .stButton > button[data-testid="baseButton-primary"]:hover {{
        background:{BRAND_DARK}; color:#fff;
    }}
    .stDownloadButton > button {{
        border-radius:10px; font-weight:650; border:2px solid {BORDER};
        background:{WHITE}; color:{INK};
    }}

    /* ---------- inputs (white on the pastel card) ---------- */
    div[data-baseweb="input"] > div, div[data-baseweb="select"] > div,
    .stTextArea textarea {{
        border-radius:10px !important; border-color:{BORDER} !important;
        background:{WHITE} !important;
    }}
    div[data-baseweb="input"] > div:focus-within,
    div[data-baseweb="select"] > div:focus-within,
    .stTextArea textarea:focus {{
        box-shadow:0 0 0 3px {BRAND}33 !important;
    }}
    label, .stTextInput label, .stTextArea label, .stSelectbox label {{
        font-weight:650 !important; color:{INK_SOFT} !important; font-size:.82rem !important;
    }}

    [data-testid="stFileUploader"] section,
    [data-testid="stFileUploaderDropzone"] {{
        background:{WHITE}; border:2px dashed {BORDER};
        border-radius:12px; padding:.8rem 1rem;
    }}

    [data-testid="stMetric"] {{
        background:{WHITE}; border:2px solid {BORDER};
        border-radius:12px; padding:.7rem .9rem;
    }}
    [data-testid="stMetricLabel"] {{
        font-size:.66rem !important; font-weight:800 !important;
        letter-spacing:.1em; text-transform:uppercase; color:{MUTED} !important;
    }}
    [data-testid="stMetricValue"] {{
        font-size:1.7rem !important; font-weight:750 !important; color:{INK} !important;
    }}

    .stTabs [data-baseweb="tab-list"] {{ gap:.25rem; }}
    .stTabs [data-baseweb="tab"] {{ font-weight:650; color:{MUTED}; padding:.45rem .8rem; }}
    .stTabs [aria-selected="true"] {{ color:{BRAND} !important; }}
    .stTabs [data-baseweb="tab-highlight"] {{ background:{BRAND} !important; }}

    [data-testid="stExpander"] {{
        border:2px solid {BORDER}; border-radius:12px; background:{WHITE};
    }}
    [data-testid="stExpander"] summary {{ font-weight:650; color:{INK}; }}

    [data-testid="stAlert"] {{ border-radius:12px; border:2px solid {BORDER}; }}

    /* ---------- QA tables ---------- */
    .oq-table-wrap {{
        border:2px solid {BORDER}; border-radius:12px; overflow:hidden; background:{WHITE};
    }}
    table.oq-table {{ width:100%; border-collapse:collapse; font-size:.83rem; }}
    table.oq-table thead th {{
        background:#EFF1F6; color:{INK_SOFT};
        font-size:.66rem; font-weight:800; letter-spacing:.08em; text-transform:uppercase;
        text-align:left; padding:.6rem .75rem; border-bottom:2px solid {BORDER};
        white-space:nowrap;
    }}
    table.oq-table td {{
        padding:.6rem .75rem; vertical-align:top; color:{INK_SOFT};
        border-bottom:1px solid {LINE_SOFT}; line-height:1.5;
        overflow-wrap:anywhere; word-break:break-word;
    }}
    table.oq-table tr:last-child td {{ border-bottom:none; }}
    table.oq-table td:first-child {{ border-left:5px solid transparent; font-weight:650; color:{INK}; }}

    table.oq-table tr.oq-pass td {{ background:{OK_BG}; }}
    table.oq-table tr.oq-pass td:first-child {{ border-left-color:{OK}; }}
    table.oq-table tr.oq-warn td {{ background:{WARN_BG}; }}
    table.oq-table tr.oq-warn td:first-child {{ border-left-color:{WARN}; }}
    table.oq-table tr.oq-fail td {{ background:{BAD_BG}; }}
    table.oq-table tr.oq-fail td:first-child {{ border-left-color:{BAD}; }}

    .oq-status {{
        display:inline-block; font-size:.7rem; font-weight:800; letter-spacing:.04em;
        padding:.15rem .5rem; border-radius:6px; white-space:nowrap; border:1px solid {BORDER};
    }}
    .oq-status.pass {{ color:{OK};   background:#BBF7D0; }}
    .oq-status.warn {{ color:{WARN}; background:#FDE68A; }}
    .oq-status.fail {{ color:{BAD};  background:#FCA5A5; }}

    .oq-empty {{
        padding:.7rem .9rem; border-radius:10px; background:rgba(255,255,255,.78);
        color:{INK_SOFT}; font-size:.85rem; border:2px solid {BORDER};
    }}
    .oq-note {{
        font-size:.85rem; color:{INK_SOFT}; line-height:1.6;
        background:rgba(255,255,255,.78); border:2px solid {BORDER};
        border-radius:10px; padding:.7rem .9rem; margin:.4rem 0;
    }}

    [data-testid="stDataFrame"] {{ width:100% !important; }}
    [data-testid="stDataFrame"] > div {{ overflow:auto !important; }}

    footer, #MainMenu {{ visibility:hidden; }}
    </style>
    """


def inject() -> None:
    st.markdown(_css(), unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Building blocks
# --------------------------------------------------------------------------

def render_hero(title: str, subtitle: str = "", badge: str = "") -> None:
    badge_html = f'<div class="oq-hero-badge">{_html.escape(badge)}</div>' if badge else ""
    sub_html = f'<div class="oq-hero-sub">{_html.escape(subtitle)}</div>' if subtitle else ""
    st.markdown(
        f"""
        <div class="oq-hero">
          <div>
            <div class="oq-hero-eyebrow">Dealer Panel QA</div>
            <div class="oq-hero-title">{_html.escape(title)}</div>
            {sub_html}
          </div>
          {badge_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


@contextmanager
def section(kind: str = "neutral", label: str = ""):
    k = _kind(kind)
    box = st.container(border=True)
    with box:
        pill = (
            f'<span class="oq-pill"><span class="oq-dot"></span>{_html.escape(str(label))}</span>'
            if label else ""
        )
        st.markdown(f'<div class="oq-head oq-k-{k}">{pill}</div>', unsafe_allow_html=True)
        yield box


@contextmanager
def sticky_bar():
    """A container pinned below Streamlit's toolbar — used for Run QA."""
    box = st.container(border=True)
    with box:
        st.markdown('<div class="oq-sticky"></div>', unsafe_allow_html=True)
        yield box


@contextmanager
def group(label: str = ""):
    box = st.container()
    with box:
        if label:
            st.markdown(
                f'<div class="oq-group">{_html.escape(str(label))}</div>',
                unsafe_allow_html=True,
            )
        yield box

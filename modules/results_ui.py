"""
Shared Streamlit rendering for every QA result table.

Why the implementation lives here rather than in app.py: the same three
shapes of result get rendered in half a dozen places (Content QA, Exact
Match QA, Styling QA, and each Advanced QA module), and they must all
behave identically — otherwise a reviewer learns one table's rules and is
then surprised by the next one.

The behaviour every table shares:

  * Fail / Warn / Missing rows are ALWAYS visible, in a full-width table
    that wraps long text instead of truncating it. These are the only
    rows anyone actually needs to act on, so they are never hidden behind
    a click.
  * Pass / Present rows are collapsed into a closed expander labelled
    "<pass_label> (n) — click to view". They are still one click away,
    but a run where everything passed shows a short confirmation instead
    of two hundred green rows.
  * An "Expand" button opens the COMPLETE table (passes included) in a
    modal dialog with its own close button, for when someone does want to
    read the whole thing without scrolling the page.

Rendering uses plain HTML tables rather than st.dataframe because a
dataframe truncates long detail text to a single clipped line and adds
its own inner scrollbar — which is exactly wrong for cells that routinely
contain a full sentence explaining why a check failed. Status colours
come from the classes defined in theme.py, so the palette lives in one
place.
"""

from __future__ import annotations

import html as _html
from typing import List, Optional, Sequence

import pandas as pd
import streamlit as st

try:
    from .results import ModuleResult, PASS, FAIL, WARN
except ImportError:  # pragma: no cover - standalone use
    from results import ModuleResult, PASS, FAIL, WARN


# Status vocabulary used across the app. "Present" is Content QA's word
# for a pass; "Missing" is its word for a fail.
_PASS_WORDS = {"pass", "passed", "present", "ok", "found"}
_WARN_WORDS = {"warn", "warning"}
_FAIL_WORDS = {"fail", "failed", "missing", "error"}


def _status_class(value: object) -> str:
    v = str(value or "").strip().lower()
    if v in _PASS_WORDS:
        return "pass"
    if v in _WARN_WORDS:
        return "warn"
    if v in _FAIL_WORDS:
        return "fail"
    return ""


def _is_attention(value: object) -> bool:
    return _status_class(value) in ("warn", "fail")


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    text = str(value)
    if text.strip().lower() == "nan":
        return ""
    return _html.escape(text).replace("\n", "<br>")


def _table_html(df: pd.DataFrame, status_col: str) -> str:
    if df is None or not len(df):
        return ""

    cols = list(df.columns)
    head = "".join(f"<th>{_html.escape(str(c))}</th>" for c in cols)

    rows_html = []
    for _, row in df.iterrows():
        cls = _status_class(row.get(status_col, ""))
        cells = []
        for c in cols:
            val = row.get(c, "")
            if c == status_col and cls:
                cells.append(
                    f'<td><span class="oq-status {cls}">{_cell(val)}</span></td>'
                )
            else:
                cells.append(f"<td>{_cell(val)}</td>")
        row_cls = f' class="oq-{cls}"' if cls else ""
        rows_html.append(f"<tr{row_cls}>{''.join(cells)}</tr>")

    return (
        '<div class="oq-table-wrap"><table class="oq-table">'
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody>"
        "</table></div>"
    )


def _render_table(df: pd.DataFrame, status_col: str) -> None:
    html = _table_html(df, status_col)
    if html:
        st.markdown(html, unsafe_allow_html=True)



def _disclosure_html(label: str, inner_html: str) -> str:
    """A native <details>/<summary> dropdown.

    This was briefly a Streamlit button plus a session-state flag, because
    st.expander refuses to nest inside the per-email result groups. But a
    button round-trips to the server and re-runs the whole script just to
    show rows that were already computed, so every click flashed the
    "Running..." indicator and rebuilt the page.

    A plain <details> element is opened by the browser itself: instant, no
    rerun, and no nesting restriction either, since it is ordinary HTML
    rather than a Streamlit container. The table markup is already
    generated as a string, so it simply goes inside.
    """
    return (
        f'<details class="oq-details"><summary>{_html.escape(label)}</summary>'
        f'<div class="oq-details-body">{inner_html}</div></details>'
    )


def render_qa_table(
    df: pd.DataFrame,
    status_col: str,
    table_key: str,
    pass_label: str = "Passed",
) -> None:
    """The single shared QA table renderer — see the module docstring."""
    if df is None or not len(df):
        st.markdown(
            '<div class="oq-empty">No checks were produced for this section.</div>',
            unsafe_allow_html=True,
        )
        return

    if status_col not in df.columns:
        _render_table(df, status_col)
        return

    mask = df[status_col].apply(_is_attention)
    attention_df = df[mask]
    passed_df = df[~mask]

    # "Expand" opens the complete table in a modal.
    spacer, btn = st.columns([6, 1])
    with btn:
        expand_clicked = st.button(
            "↗ Expand", key=f"{table_key}__expand", use_container_width=True
        )

    if expand_clicked:
        st.session_state[f"{table_key}__dialog_open"] = True

    if st.session_state.get(f"{table_key}__dialog_open"):
        _open_dialog(df, status_col, table_key)

    if len(attention_df):
        _render_table(attention_df, status_col)
    else:
        st.markdown(
            '<div class="oq-empty">Nothing needs attention here — every check passed.</div>',
            unsafe_allow_html=True,
        )

    if len(passed_df):
        st.markdown(
            _disclosure_html(
                f"{pass_label} ({len(passed_df)}) — click to view",
                _table_html(passed_df, status_col),
            ),
            unsafe_allow_html=True,
        )


def _open_dialog(df: pd.DataFrame, status_col: str, table_key: str) -> None:
    """st.dialog needs a decorated function; it arrived in Streamlit 1.31,
    which is this app's documented minimum. On anything older the full
    table is rendered inline instead of in a modal, so the button still
    does something useful rather than raising."""
    dialog_fn = getattr(st, "dialog", None)
    if dialog_fn is None:
        st.markdown("**Full table**")
        _render_table(df, status_col)
        if st.button("Close", key=f"{table_key}__dialog_close_inline"):
            st.session_state[f"{table_key}__dialog_open"] = False
            st.rerun()
        return

    @dialog_fn("Full QA table", width="large")
    def _show():
        _render_table(df, status_col)
        if st.button("Close", key=f"{table_key}__dialog_close"):
            st.session_state[f"{table_key}__dialog_open"] = False
            st.rerun()

    _show()


def render_module_result(result: ModuleResult, table_key: str) -> None:
    """Renders one ModuleResult: heading, Pass/Warn/Fail metrics, its item
    table, then any notes and images the module attached."""
    if result is None:
        return

    st.markdown(f"**{_html.escape(result.module_name)}**")

    items = result.items or []
    if items:
        p, f, w = result.counts()
        c1, c2, c3 = st.columns(3)
        c1.metric("Passed", p)
        c2.metric("Warnings", w)
        c3.metric("Failed", f)

        df = pd.DataFrame([{
            "category": i.category,
            "rule": i.rule,
            "status": i.status,
            "detail": i.detail,
            "expected": i.expected,
            "found": i.found,
        } for i in items])
        render_qa_table(df, status_col="status", table_key=table_key, pass_label="Passed")

    for note in (result.notes or []):
        st.markdown(f'<div class="oq-note">{note}</div>', unsafe_allow_html=True)

    images = result.images or []
    if images:
        cols = st.columns(min(len(images), 4))
        for i, art in enumerate(images):
            with cols[i % len(cols)]:
                st.image(art.png_bytes, caption=art.label, use_container_width=True)

    if not items and not result.notes and not images:
        st.markdown(
            '<div class="oq-empty">This check did not run — nothing to report.</div>',
            unsafe_allow_html=True,
        )


def render_summary(results: Sequence[ModuleResult], table_key: str) -> None:
    """One row per module: its overall verdict plus Pass/Warn/Fail counts."""
    results = [r for r in (results or []) if r is not None]
    if not results:
        st.markdown(
            '<div class="oq-empty">No Advanced QA modules produced results for this email.</div>',
            unsafe_allow_html=True,
        )
        return

    rows = []
    tot_p = tot_w = tot_f = 0
    for r in results:
        p, f, w = r.counts()
        tot_p += p
        tot_w += w
        tot_f += f
        rows.append({
            "module": r.module_name,
            "status": r.overall_status() if r.items else WARN,
            "passed": p,
            "warnings": w,
            "failed": f,
        })

    c1, c2, c3 = st.columns(3)
    c1.metric("Passed", tot_p)
    c2.metric("Warnings", tot_w)
    c3.metric("Failed", tot_f)

    render_qa_table(
        pd.DataFrame(rows), status_col="status",
        table_key=table_key, pass_label="Modules fully passed",
    )

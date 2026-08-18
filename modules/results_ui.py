"""
Feature 15 — Result Screen (tabs).

Reusable rendering helpers so app.py doesn't need to hand-roll Streamlit
widgets for every module — one function renders a ModuleResult consistently
everywhere it's used (Dealer Panel QA / Body QA / Banner QA / Visual QA /
OCR QA / Summary).

Table rendering (render_qa_table, qa_table_html, split_pass_fail) is the
SINGLE shared implementation for every QA results table in the app,
including the ones app.py renders directly for Content QA / Exact Match
QA / Styling QA — app.py imports and calls these rather than keeping its
own separate copy, specifically to avoid two independent implementations
of the same rendering logic silently drifting apart (exactly what
happened with the Excel-column-reading logic before it was consolidated
into one shared function).
"""

import html as html_escape_module
from typing import List, Tuple

import pandas as pd
import streamlit as st

from .results import ModuleResult, PASS, FAIL, WARN


# CSS class names only — the actual colors live in modules/theme.py's
# --success/--warning/--danger tokens, injected once by theme.inject().
# Kept here as a lookup so _qa_row_html's logic (branching on status) is
# unchanged; only what gets emitted (a class instead of an inline hex) is
# different.
_STATUS_ROW_CLASS = {
    "Pass": "qa-row-pass", "Present": "qa-row-pass",
    "Warn": "qa-row-warn",
    "Fail": "qa-row-fail", "Missing": "qa-row-fail",
}


def _qa_row_html(record: dict, columns: List[str]) -> str:
    """One <tr> — every cell wraps normally (white-space:normal +
    word-break:break-word) instead of truncating or forcing a horizontal
    scrollbar to read, and all text is HTML-escaped since QA detail text
    can itself contain literal HTML snippets (e.g. quoting an href value)
    that must render as visible text, not be interpreted as markup.

    The status/severity column is always a single short word (Pass /
    Fail / Warn / Present / Missing) — it never needs word-break/wrap,
    and forcing normal wrapping on a column with no min-width let it
    collapse to a sliver, breaking "Present" onto two lines ("Presen" /
    "t"). That column gets its own no-wrap, fixed-min-width styling;
    every other column (Item/Detail/etc., which are genuinely long free
    text) keeps the original wrapping behaviour unchanged.
    """
    status_val = record.get("status") or record.get("severity") or ""
    row_class = _STATUS_ROW_CLASS.get(str(status_val), "qa-row-none")
    cells = []
    for c in columns:
        is_status_col = c.strip().lower() in ("status", "severity")
        if is_status_col:
            cell_style = (
                "padding:10px 14px;vertical-align:top;"
                "white-space:nowrap;min-width:100px;width:1%;"
            )
        else:
            cell_style = (
                "padding:10px 14px;vertical-align:top;"
                "white-space:normal;word-break:break-word;"
            )
        cells.append(
            f'<td style="{cell_style}">'
            f'{html_escape_module.escape(str(record.get(c, "")))}</td>'
        )
    return f'<tr class="{row_class}">{"".join(cells)}</tr>'


def qa_table_html(records: List[dict], columns: List[str]) -> str:
    """Full <table> (with header) for a list of QA row dicts. Only ONE
    scrollbar (overflow-x:auto on the wrapping <div>) rather than the
    nested "double scroll" produced by st.dataframe's own internal
    scroll area sitting inside Streamlit's page-level scroll."""
    if not records:
        return '<p style="color:var(--text-muted);padding:8px 0;">No rows.</p>'
    header_cells = "".join(
        f'<th style="padding:10px 14px;text-align:left;font-weight:600;'
        f'{"white-space:nowrap;min-width:100px;width:1%;" if c.strip().lower() in ("status", "severity") else ""}">'
        f'{html_escape_module.escape(c)}</th>'
        for c in columns
    )
    body_rows = "".join(_qa_row_html(r, columns) for r in records)
    return (
        f'<div class="qa-table-wrap" style="overflow-x:auto;max-width:100%;">'
        f'<table style="width:100%;border-collapse:collapse;font-size:14px;">'
        f'<thead><tr>{header_cells}</tr></thead>'
        f'<tbody>{body_rows}</tbody>'
        f'</table></div>'
    )


def split_pass_fail(df: pd.DataFrame, status_col: str) -> Tuple[List[dict], List[dict]]:
    """Splits a QA DataFrame's rows into (attention_rows, pass_rows) —
    attention_rows is everything that needs a person's eyes (Fail, Warn,
    Missing); pass_rows is everything already fine (Pass, Present)."""
    if df is None or not len(df):
        return [], []
    records = df.to_dict("records")
    pass_like = {"pass", "present"}
    attention = [r for r in records if str(r.get(status_col, "")).strip().lower() not in pass_like]
    passing = [r for r in records if str(r.get(status_col, "")).strip().lower() in pass_like]
    return attention, passing


@st.dialog("Full QA table", width="large")
def _show_qa_table_dialog(records: List[dict], columns: List[str]) -> None:
    """Full-width popup showing every row together. st.dialog renders
    with its own native close (X) button in the top-right corner and a
    smooth built-in open/close transition — no custom overlay/JS needed."""
    st.markdown(qa_table_html(records, columns), unsafe_allow_html=True)


def render_qa_table(df: pd.DataFrame, status_col: str, table_key: str, pass_label: str = "Passed") -> None:
    """
    Renders one QA results table:
      - Fail/Warn/Missing rows: always visible, full-width HTML table,
        cells wrap instead of truncating.
      - Pass/Present rows: collapsed inside a closed-by-default expander
        — visible only if the person chooses to open it.
      - An "Expand" button opens the COMPLETE table (attention + pass
        rows together) full-width in a popup, with its own native close
        button.
    `table_key` must be unique per table on the page.
    """
    if df is None or not len(df):
        st.info("No checks were run for this table.")
        return

    columns = list(df.columns)
    attention_rows, pass_rows = split_pass_fail(df, status_col)

    top = st.columns([0.85, 0.15])
    with top[1]:
        expand_clicked = st.button("⤢ Expand", key=f"expand_{table_key}", use_container_width=True)

    if attention_rows:
        st.markdown(qa_table_html(attention_rows, columns), unsafe_allow_html=True)
    else:
        st.success("Nothing needs attention here — every check passed.")

    if pass_rows:
        with st.expander(f"{pass_label} ({len(pass_rows)}) — click to view", expanded=False):
            st.markdown(qa_table_html(pass_rows, columns), unsafe_allow_html=True)

    if expand_clicked:
        _show_qa_table_dialog(df.to_dict("records"), columns)


def render_module_result(result: ModuleResult, show_header: bool = True, table_key: str = "") -> None:
    if show_header:
        st.subheader(result.module_name)

    if not result.items and not result.images and not result.notes:
        st.info("No checks were run for this module (all related inputs were empty/disabled).")
        return

    if result.items:
        p, f, w = result.counts()
        c1, c2, c3 = st.columns(3)
        c1.metric("Passed", p)
        c2.metric("Warnings", w)
        c3.metric("Failed", f)

        df = pd.DataFrame([i.__dict__ for i in result.items])
        key = table_key or f"module_{result.module_name}"
        render_qa_table(df, status_col="status", table_key=key, pass_label="Passed")

    if result.images:
        cols = st.columns(min(4, len(result.images)))
        for i, artifact in enumerate(result.images):
            with cols[i % len(cols)]:
                st.image(artifact.png_bytes, caption=artifact.label, use_container_width=True)

    for note in result.notes:
        if "<span" in note:
            st.markdown(note, unsafe_allow_html=True)
        else:
            st.caption(note)


def render_summary(results: List[ModuleResult], table_key: str = "advanced_summary") -> None:
    st.subheader("Summary")
    rows = []
    for r in results:
        p, f, w = r.counts()
        rows.append({
            "Module": r.module_name,
            "Overall": r.overall_status(),
            "Passed": p,
            "Warnings": w,
            "Failed": f,
        })
    if not rows:
        st.info("No modules ran for this email.")
        return
    df = pd.DataFrame(rows)
    render_qa_table(df, status_col="Overall", table_key=table_key, pass_label="Passed")

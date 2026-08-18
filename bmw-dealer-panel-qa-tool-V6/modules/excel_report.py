"""
Feature — Consolidated Excel QA Report.

Collects the Normal QA (Content + Styling) results AND, when enabled, every
Advanced QA module's results (Body QA, Banner QA, Summary, etc.) for EVERY
uploaded email/job in the run, and exports them all into a single,
professionally formatted .xlsx workbook — one workbook for the whole run,
not one file per job.

Design:
  - One "Overview" sheet: one row per job with headline Pass/Fail/Warn
    counts across Content + Style + every Advanced QA module that ran.
  - One "<JobName> - Content" sheet per job: the content QA table.
  - One "<JobName> - Style" sheet per job: the styling QA table.
  - One "<JobName> - Advanced QA" sheet per job (only if advanced QA ran):
    every ModuleResult's items, stacked with a "Module" column, plus a
    small module-level summary block at the top.
  - Sheet names are sanitized/truncated/de-duplicated to respect Excel's
    31-character, no-special-character sheet name limits.

No formulas are needed here (this is a data export, not a financial
model) — everything is written as plain values/styles via openpyxl.
"""

import re
from dataclasses import dataclass
from io import BytesIO
from typing import Dict, List, Optional

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

try:
    from .results import ModuleResult, PASS, FAIL, WARN
except ImportError:  # pragma: no cover - allows standalone use/testing
    from results import ModuleResult, PASS, FAIL, WARN


# =========================================================
# Styling constants
# =========================================================

FONT_NAME = "Arial"

HEADER_FILL = PatternFill("solid", fgColor="1C2B4A")
HEADER_FONT = Font(name=FONT_NAME, size=11, bold=True, color="FFFFFF")

TITLE_FONT = Font(name=FONT_NAME, size=16, bold=True, color="1C2B4A")
SUBTITLE_FONT = Font(name=FONT_NAME, size=10, italic=True, color="595959")
SECTION_FONT = Font(name=FONT_NAME, size=12, bold=True, color="1C2B4A")

STATUS_FILL = {
    "Pass": PatternFill("solid", fgColor="C6EFCE"),
    "Present": PatternFill("solid", fgColor="C6EFCE"),
    "Fail": PatternFill("solid", fgColor="FFC7CE"),
    "Missing": PatternFill("solid", fgColor="FFC7CE"),
    "Warn": PatternFill("solid", fgColor="FFEB9C"),
}
STATUS_FONT = {
    "Pass": Font(name=FONT_NAME, size=10, color="006100"),
    "Present": Font(name=FONT_NAME, size=10, color="006100"),
    "Fail": Font(name=FONT_NAME, size=10, color="9C0006"),
    "Missing": Font(name=FONT_NAME, size=10, color="9C0006"),
    "Warn": Font(name=FONT_NAME, size=10, color="9C6500"),
}

THIN_BORDER = Border(
    left=Side(style="thin", color="D9D9D9"),
    right=Side(style="thin", color="D9D9D9"),
    top=Side(style="thin", color="D9D9D9"),
    bottom=Side(style="thin", color="D9D9D9"),
)

BODY_FONT = Font(name=FONT_NAME, size=10)
WRAP_ALIGN = Alignment(vertical="top", wrap_text=True)
CENTER_ALIGN = Alignment(vertical="center", horizontal="center", wrap_text=True)


# =========================================================
# Data model collected by app.py as each job runs
# =========================================================

@dataclass
class JobReportData:
    """Everything one uploaded email/job contributes to the final workbook."""
    job_name: str
    dealer: str = ""
    region: str = ""
    content_df: Optional[pd.DataFrame] = None            # columns: item, status
    style_df: Optional[pd.DataFrame] = None               # columns: rule, severity, detail
    advanced_module_results: Optional[List[ModuleResult]] = None


# =========================================================
# Helpers
# =========================================================

def _sanitize_sheet_name(name: str, used: Dict[str, int]) -> str:
    """Excel sheet names: max 31 chars, no [ ] : * ? / \\, must be unique."""
    cleaned = re.sub(r"[\[\]\:\*\?\/\\]", "-", name).strip() or "Sheet"
    cleaned = cleaned[:31]
    base = cleaned
    if base not in used:
        used[base] = 0
        return base
    used[base] += 1
    suffix = f" ({used[base]})"
    return base[: 31 - len(suffix)] + suffix


def _autosize_columns(ws: Worksheet, df_columns: List[str], max_width: int = 60, min_width: int = 12) -> None:
    for idx, col_name in enumerate(df_columns, start=1):
        letter = get_column_letter(idx)
        longest = max([len(str(col_name))] + [len(str(v)) for v in []])
        width = min(max(longest + 4, min_width), max_width)
        ws.column_dimensions[letter].width = width


def _write_title_block(ws: Worksheet, title: str, subtitle: str = "", start_row: int = 1) -> int:
    ws.cell(row=start_row, column=1, value=title).font = TITLE_FONT
    row = start_row + 1
    if subtitle:
        ws.cell(row=row, column=1, value=subtitle).font = SUBTITLE_FONT
        row += 1
    return row + 1  # blank row after title block


def _write_table(
    ws: Worksheet,
    start_row: int,
    headers: List[str],
    rows: List[List],
    status_col_indexes: Optional[List[int]] = None,
    col_widths: Optional[List[int]] = None,
) -> int:
    """
    Writes a header row + data rows starting at `start_row`, applying
    banded rows, borders, wrap text, and status-cell color coding.
    Returns the row number just after the table.
    """
    status_col_indexes = status_col_indexes or []

    for c_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=start_row, column=c_idx, value=header)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = CENTER_ALIGN
        cell.border = THIN_BORDER

    r = start_row + 1
    for row_idx, row_vals in enumerate(rows):
        band_fill = PatternFill("solid", fgColor="F2F2F2") if row_idx % 2 == 1 else None
        for c_idx, val in enumerate(row_vals, start=1):
            cell = ws.cell(row=r, column=c_idx, value=val)
            cell.border = THIN_BORDER
            cell.alignment = WRAP_ALIGN
            if c_idx in status_col_indexes and isinstance(val, str) and val in STATUS_FILL:
                cell.fill = STATUS_FILL[val]
                cell.font = STATUS_FONT[val]
            else:
                cell.font = BODY_FONT
                if band_fill is not None:
                    cell.fill = band_fill
        r += 1

    if col_widths:
        for c_idx, width in enumerate(col_widths, start=1):
            ws.column_dimensions[get_column_letter(c_idx)].width = width

    ws.freeze_panes = ws.cell(row=start_row + 1, column=1).coordinate
    return r + 1


def _counts_from_status_series(statuses: List[str]) -> Dict[str, int]:
    counts = {"Pass": 0, "Fail": 0, "Warn": 0}
    for s in statuses:
        if s in ("Pass", "Present"):
            counts["Pass"] += 1
        elif s in ("Fail", "Missing"):
            counts["Fail"] += 1
        elif s == "Warn":
            counts["Warn"] += 1
    return counts


# =========================================================
# Sheet builders
# =========================================================

def _build_overview_sheet(wb: Workbook, jobs: List[JobReportData]) -> None:
    ws = wb.active
    ws.title = "Overview"

    row = _write_title_block(
        ws, "Dealer Panel QA — Consolidated Report",
        f"{len(jobs)} email(s)/model(s) processed.",
    )

    headers = [
        "Email / Model", "Dealer", "Region",
        "Content Present", "Content Missing",
        "Style Pass", "Style Warn", "Style Fail",
        "Advanced QA Pass", "Advanced QA Warn", "Advanced QA Fail",
        "Overall",
    ]
    rows = []
    for job in jobs:
        content_present = content_missing = 0
        if job.content_df is not None and len(job.content_df):
            # "Present"/"Missing" cover the original fuzzy-match rows; the
            # website-link QA rows (Feature 16) use "Pass"/"Fail" for the
            # same content_df, meaning the same thing ("correct"/"wrong"),
            # so both status vocabularies are counted together here.
            content_present = int(job.content_df["status"].isin(["Present", "Pass"]).sum())
            content_missing = int(job.content_df["status"].isin(["Missing", "Fail"]).sum())

        style_pass = style_warn = style_fail = 0
        if job.style_df is not None and len(job.style_df):
            style_pass = int((job.style_df["severity"] == "Pass").sum())
            style_warn = int((job.style_df["severity"] == "Warn").sum())
            style_fail = int((job.style_df["severity"] == "Fail").sum())

        adv_pass = adv_warn = adv_fail = 0
        if job.advanced_module_results:
            for mr in job.advanced_module_results:
                p, f, w = mr.counts()
                adv_pass += p
                adv_warn += w
                adv_fail += f

        overall = "Fail" if (content_missing or style_fail or adv_fail) else (
            "Warn" if (style_warn or adv_warn) else "Pass"
        )

        rows.append([
            job.job_name, job.dealer, job.region,
            content_present, content_missing,
            style_pass, style_warn, style_fail,
            adv_pass, adv_warn, adv_fail,
            overall,
        ])

    _write_table(
        ws, row, headers, rows,
        status_col_indexes=[len(headers)],
        col_widths=[30, 20, 14, 14, 14, 12, 12, 12, 16, 16, 16, 12],
    )


def _build_content_sheet(wb: Workbook, job: JobReportData, sheet_name: str) -> None:
    ws = wb.create_sheet(sheet_name)
    row = _write_title_block(ws, f"{job.job_name} — Content QA", "Dealer panel lines present in HTML.")

    df = job.content_df if job.content_df is not None else pd.DataFrame(columns=["item", "status"])
    headers = ["Item", "Status"]
    rows = [[r["item"], r["status"]] for _, r in df.iterrows()]
    _write_table(ws, row, headers, rows, status_col_indexes=[2], col_widths=[80, 14])


def _build_style_sheet(wb: Workbook, job: JobReportData, sheet_name: str) -> None:
    ws = wb.create_sheet(sheet_name)
    row = _write_title_block(ws, f"{job.job_name} — Styling QA", "Dealer panel + module directly above it, plus image sizes.")

    df = job.style_df if job.style_df is not None else pd.DataFrame(columns=["rule", "severity", "detail"])
    headers = ["Rule", "Severity", "Detail"]
    rows = [[r["rule"], r["severity"], r["detail"]] for _, r in df.iterrows()]
    _write_table(ws, row, headers, rows, status_col_indexes=[2], col_widths=[40, 12, 80])


def _build_advanced_sheet(wb: Workbook, job: JobReportData, sheet_name: str) -> None:
    ws = wb.create_sheet(sheet_name)
    row = _write_title_block(ws, f"{job.job_name} — Advanced QA", "Banner / Body / Dealer Name / Visual / OCR checks.")

    module_results = job.advanced_module_results or []

    if not module_results:
        ws.cell(
            row=row, column=1,
            value=(
                "Advanced QA did not run for this email — tick 'Enable Advanced QA tabs for "
                "this run' in the sidebar before clicking Run QA to populate this sheet."
            ),
        ).font = BODY_FONT
        return

    # Module-level summary block first.
    summary_headers = ["Module", "Pass", "Warn", "Fail", "Overall"]
    summary_rows = []
    for mr in module_results:
        p, f, w = mr.counts()
        summary_rows.append([mr.module_name, p, w, f, mr.overall_status()])
    row = _write_table(
        ws, row, summary_headers, summary_rows,
        status_col_indexes=[5], col_widths=[30, 10, 10, 10, 12],
    )
    row += 1  # extra gap before the detail table

    ws.cell(row=row, column=1, value="Detailed Checks").font = SECTION_FONT
    row += 1

    detail_headers = ["Module", "Category", "Rule", "Status", "Detail", "Expected", "Found"]
    detail_rows = []
    for mr in module_results:
        for item in mr.items:
            detail_rows.append([
                mr.module_name, item.category, item.rule, item.status,
                item.detail, item.expected, item.found,
            ])

    if detail_rows:
        _write_table(
            ws, row, detail_headers, detail_rows,
            status_col_indexes=[4], col_widths=[22, 16, 22, 12, 50, 30, 30],
        )
    else:
        ws.cell(row=row, column=1, value="No individual check items were recorded (all inputs empty/disabled).").font = BODY_FONT


# =========================================================
# Public entry point
# =========================================================

def build_qa_workbook(jobs: List[JobReportData]) -> bytes:
    """
    Builds the full consolidated workbook for every job in the run and
    returns it as raw .xlsx bytes, ready for a Streamlit download button.
    """
    wb = Workbook()
    _build_overview_sheet(wb, jobs)

    used_names: Dict[str, int] = {"Overview": 0}
    for job in jobs:
        base = job.job_name or "Email"

        content_sheet_name = _sanitize_sheet_name(f"{base} - Content", used_names)
        _build_content_sheet(wb, job, content_sheet_name)

        style_sheet_name = _sanitize_sheet_name(f"{base} - Style", used_names)
        _build_style_sheet(wb, job, style_sheet_name)

        adv_sheet_name = _sanitize_sheet_name(f"{base} - Advanced QA", used_names)
        _build_advanced_sheet(wb, job, adv_sheet_name)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()

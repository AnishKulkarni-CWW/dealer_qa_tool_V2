"""
Feature 1 — Excel Sheet Selection.

Replaces implicit/hardcoded sheet detection with an explicit dropdown of
every sheet in the workbook. Only the sheet the user selects is parsed.

This module is intentionally generic: it does not know about "Dealer",
"Region", or "Dealer Panels" columns — that parsing still happens in the
existing app.py `read_dealer_panels_from_excel`-style logic. This module's
job is only: list sheets -> return the chosen sheet's raw DataFrame.
"""

from dataclasses import dataclass
from typing import List, Optional

import pandas as pd


@dataclass
class ExcelWorkbook:
    file_obj: object
    sheet_names: List[str]

    def load_sheet(self, sheet_name: str, header: Optional[int] = None) -> pd.DataFrame:
        """Load exactly one sheet, nothing else."""
        xl = pd.ExcelFile(self.file_obj)
        return xl.parse(sheet_name, header=header, dtype=str)


def open_workbook(uploaded_file) -> ExcelWorkbook:
    """
    Open the workbook and list its sheets without loading any data yet.
    Never assumes a hardcoded sheet name exists.
    """
    xl = pd.ExcelFile(uploaded_file)
    return ExcelWorkbook(file_obj=uploaded_file, sheet_names=list(xl.sheet_names))


def find_header_row(df_raw: pd.DataFrame, required_columns_lower: List[str], scan_rows: int = 10) -> Optional[int]:
    """
    Generic header-row finder: scans the first `scan_rows` rows of a
    headerless DataFrame for one row containing all `required_columns_lower`
    (case-insensitive). Used once a sheet has been selected, to locate the
    real header row beneath any title row(s).
    """
    for i in range(min(scan_rows, len(df_raw))):
        row_vals = [str(v).strip().lower() for v in df_raw.iloc[i].tolist()]
        if all(col in row_vals for col in required_columns_lower):
            return i
    return None


def load_selected_sheet_with_header(
    workbook: ExcelWorkbook,
    sheet_name: str,
    required_columns_lower: List[str],
) -> pd.DataFrame:
    """
    Loads ONLY `sheet_name`, auto-detects the header row (by scanning for
    `required_columns_lower`), and returns a properly-headered DataFrame.
    Raises ValueError with a clear message if the header can't be found —
    no silent fallback to a different/hardcoded sheet.
    """
    raw = workbook.load_sheet(sheet_name, header=None)
    header_row_idx = find_header_row(raw, required_columns_lower)
    if header_row_idx is None:
        raise ValueError(
            f"Could not find a header row containing {required_columns_lower} "
            f"in sheet '{sheet_name}'. This sheet may not be the right one — "
            f"pick a different sheet from the dropdown."
        )
    df = workbook.load_sheet(sheet_name, header=header_row_idx)
    df.columns = [str(c).strip() for c in df.columns]
    return df

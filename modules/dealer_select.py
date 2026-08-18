"""
Feature 2 — Dealer Selection Module.
Feature 3 — Dealer Name Validation.

When a dealer is chosen from the dropdown, that dealer becomes the
"master" dealer for the run: the Excel Dealer/Region columns are filtered
down to that single row, and (if enabled) HTML auto-detection of dealer
is skipped entirely in favour of this explicit selection.
"""

import re
from dataclasses import dataclass
from typing import List, Optional

from .results import ModuleResult, PASS, FAIL


@dataclass
class DealerRecord:
    dealer: str
    region: str
    panel_text: str
    raw_row: dict


def build_dealer_options(dealer_rows) -> List[str]:
    """
    dealer_rows: list of objects/rows with a `.dealer` (and optionally
    `.region`) attribute — e.g. the existing app.py `DealerRow` list.
    Returns display labels; never hardcodes dealer names.
    """
    labels = []
    for row in dealer_rows:
        dealer = getattr(row, "dealer", "") or ""
        region = getattr(row, "region", "") or ""
        if not dealer:
            continue
        label = f"{dealer} - {region}" if region else dealer
        labels.append(label)
    # de-duplicate while preserving order
    seen = set()
    ordered = []
    for lbl in labels:
        if lbl not in seen:
            seen.add(lbl)
            ordered.append(lbl)
    # Alphabetical A-Z by dealer name (case-insensitive), independent of
    # whatever row order the Excel sheet happens to use.
    ordered.sort(key=lambda lbl: lbl.casefold())
    return ordered


def resolve_selected_dealer(dealer_rows, selected_label: str):
    """
    Maps a dropdown label back to the underlying dealer row object.
    Filters ONLY that dealer's row (Dealer + Region columns), per spec —
    this becomes the single source of truth for Dealer Panel QA when used.
    """
    if not selected_label:
        return None
    for row in dealer_rows:
        dealer = getattr(row, "dealer", "") or ""
        region = getattr(row, "region", "") or ""
        label = f"{dealer} - {region}" if region else dealer
        if label == selected_label:
            return row
    return None


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def validate_dealer_in_text(dealer_name: str, haystack_text: str) -> bool:
    """Simple, dependency-free substring/token check for dealer presence."""
    d = _normalize(dealer_name)
    h = _normalize(haystack_text)
    if not d:
        return False
    if d in h:
        return True
    # token overlap fallback (handles minor punctuation/ordering differences)
    d_tokens = set(re.findall(r"[a-z0-9]+", d))
    h_tokens = set(re.findall(r"[a-z0-9]+", h))
    if not d_tokens:
        return False
    overlap = d_tokens & h_tokens
    return len(overlap) / len(d_tokens) >= 0.7


def run_dealer_name_validation(
    dealer_name: str,
    check_in_banner: bool,
    check_in_body: bool,
    banner_ocr_text: Optional[str],
    body_text: Optional[str],
) -> ModuleResult:
    """
    Feature 3. Both checks are OPT-IN via booleans (radio buttons in the UI).
    If a check is disabled, it is skipped entirely (no item is added), per spec.
    """
    result = ModuleResult(module_name="Dealer Name Validation")

    if not dealer_name:
        result.notes.append("No dealer name available to validate (no dealer selected/entered).")
        return result

    if check_in_banner:
        if banner_ocr_text is None:
            result.add("Dealer Name", "Dealer in Banner", FAIL,
                        detail="Banner OCR text not available — cannot validate dealer name in banner.")
        else:
            ok = validate_dealer_in_text(dealer_name, banner_ocr_text)
            result.add(
                "Dealer Name", "Dealer in Banner",
                PASS if ok else FAIL,
                detail=f"Dealer '{dealer_name}' {'found' if ok else 'NOT found'} in banner OCR text.",
                expected=dealer_name,
                found=banner_ocr_text[:200],
            )

    if check_in_body:
        if body_text is None:
            result.add("Dealer Name", "Dealer in Body", FAIL,
                        detail="Body text not available — cannot validate dealer name in body.")
        else:
            ok = validate_dealer_in_text(dealer_name, body_text)
            result.add(
                "Dealer Name", "Dealer in Body",
                PASS if ok else FAIL,
                detail=f"Dealer '{dealer_name}' {'found' if ok else 'NOT found'} in email body.",
                expected=dealer_name,
                found=body_text[:200],
            )

    return result

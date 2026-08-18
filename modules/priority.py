"""
Feature 14 — QA Priority.

Priority (highest wins), never combined:
    1. Manual Text
    2. Master JPG
    3. Master PDF
    4. Master HTML ZIP
    5. Dealer Dropdown
    6. Excel

This module is the single place that decides which Master source is
"active" for a given run. Every other module should ask this module
"is my source active?" rather than re-implementing priority logic.
"""

from dataclasses import dataclass
from typing import Optional

from .config import DEFAULT_CONFIG


@dataclass
class MasterSources:
    """Presence flags for each possible master source, filled in by the UI layer."""
    manual_text_active: bool = False
    master_jpg_active: bool = False
    master_pdf_active: bool = False
    master_html_zip_active: bool = False
    dealer_dropdown_active: bool = False
    excel_active: bool = False

    def as_dict(self):
        return {
            "manual_text": self.manual_text_active,
            "master_jpg": self.master_jpg_active,
            "master_pdf": self.master_pdf_active,
            "master_html_zip": self.master_html_zip_active,
            "dealer_dropdown": self.dealer_dropdown_active,
            "excel": self.excel_active,
        }


def resolve_active_source(sources: MasterSources, order=None) -> Optional[str]:
    """
    Returns the key of the single highest-priority active source, or None
    if nothing is active. Never returns more than one — conflicting
    masters are never combined per spec.
    """
    order = order or DEFAULT_CONFIG.priority_order
    flags = sources.as_dict()
    for key in order:
        if flags.get(key):
            return key
    return None


def explain_priority(sources: MasterSources, order=None) -> str:
    """Human-readable explanation of which source was chosen and why, for UI display."""
    active = resolve_active_source(sources, order)
    order = order or DEFAULT_CONFIG.priority_order
    labels = {
        "manual_text": "Manual Text",
        "master_jpg": "Master JPG",
        "master_pdf": "Master PDF",
        "master_html_zip": "Master HTML ZIP",
        "dealer_dropdown": "Dealer Dropdown",
        "excel": "Excel",
    }
    if active is None:
        return "No Master source is active yet."
    active_others = [labels[k] for k in order if sources.as_dict().get(k) and k != active]
    msg = f"Active Master source: **{labels[active]}** (highest priority available)."
    if active_others:
        msg += f" Ignoring lower-priority source(s) also provided: {', '.join(active_others)}."
    return msg

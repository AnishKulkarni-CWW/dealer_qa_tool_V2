"""
Feature 4 — Manual Text Mode.

--------------------------------------------------------------------------
Per-field granularity fix
--------------------------------------------------------------------------
Previously, filling in ANY ONE of Headline / Subheadline / Dealer Name /
Body Text made the whole of Manual Mode "active", and the UI layer then
disabled Dealer Dropdown / Master JPG / Master PDF / Master HTML entirely
for that run. That's wrong whenever someone wants to mix sources — e.g.
type the Dealer Name manually (because they know it's right) but still
pull Headline/Subheadline from an uploaded Master JPG, or override just
the Body Text while everything else comes from a Master PDF.

Manual Text Mode no longer disables the master-asset uploaders as a whole
unit. Instead, each of the four fields is independent:
  - A field the user typed a value into is ALWAYS used as-is for that
    field (highest priority, per spec) — it is never overwritten by OCR
    or by another master source.
  - A field left blank falls through to whatever the active visual/HTML
    master source provides for that same field (Master JPG / Master PDF
    / Master HTML ZIP's OCR'd or HTML-derived value), if any.
  - The master-asset uploaders (JPG/PDF/HTML ZIP) are therefore NEVER
    disabled just because one Manual field has a value — they stay
    available so their non-overridden fields can still be sourced from
    them. They're only meaningfully "used" for the specific fields the
    person left blank in Manual Text.

`is_active()` is kept (some callers may still want a single "is manual
mode doing anything at all" flag, e.g. for a status caption), but it no
longer drives any uploader's `disabled=` state — that per-field logic now
lives in the four `*_is_manual()` / `resolve_*()` helpers below, which
app.py should use per-field instead of gating the whole uploader block on
`is_active()`.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ManualMasterText:
    headline: str = ""
    subheadline: str = ""
    dealer_name: str = ""
    body_text: str = ""

    def is_active(self) -> bool:
        """True if ANY manual field has a value. Kept for callers that
        just want a general "is manual text being used at all" status
        flag (e.g. a summary caption) — NOT for gating uploader
        disabled= state, which should be per-field (see the *_is_manual
        helpers below)."""
        return any([
            self.headline.strip(),
            self.subheadline.strip(),
            self.dealer_name.strip(),
            self.body_text.strip(),
        ])

    def headline_is_manual(self) -> bool:
        return bool(self.headline.strip())

    def subheadline_is_manual(self) -> bool:
        return bool(self.subheadline.strip())

    def dealer_name_is_manual(self) -> bool:
        return bool(self.dealer_name.strip())

    def body_text_is_manual(self) -> bool:
        return bool(self.body_text.strip())

    def combined_banner_text(self) -> str:
        """What the banner OCR text should be compared against, if used as Master."""
        parts = [p for p in [self.headline, self.subheadline, self.dealer_name] if p.strip()]
        return "\n".join(parts)

    def resolve_headline(self, master_derived_headline: str) -> str:
        """Manual value wins if present; otherwise falls through to
        whatever the active visual/HTML master source derived for
        Headline (OCR clustering, etc.)."""
        return self.headline.strip() if self.headline_is_manual() else master_derived_headline

    def resolve_subheadline(self, master_derived_subheadline: str) -> str:
        return self.subheadline.strip() if self.subheadline_is_manual() else master_derived_subheadline

    def resolve_dealer_name(self, master_derived_dealer_name: str) -> str:
        return self.dealer_name.strip() if self.dealer_name_is_manual() else master_derived_dealer_name

    def resolve_body_text(self, master_derived_body_text: str) -> str:
        return self.body_text.strip() if self.body_text_is_manual() else master_derived_body_text

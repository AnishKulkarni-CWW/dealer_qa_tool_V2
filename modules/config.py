"""
Central configuration for the extended QA modules.
Nothing in the other modules should hardcode a magic number/string —
everything tunable lives here so behaviour can be changed in one place.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class QAConfig:
    # ---- Banner detection ----
    banner_min_width_px: int = 250
    banner_min_height_px: int = 80
    banner_max_candidates: int = 5

    # ---- OCR crop (Master JPG / PDF): crop from top until the word "Dear" ----
    crop_anchor_word: str = "dear"
    crop_anchor_fallback_ratio: float = 0.35  # if anchor not found, crop this fraction of image height

    # ---- Visual comparison ----
    ssim_pass_threshold: float = 0.90
    ssim_warn_threshold: float = 0.75
    orb_min_good_matches: int = 15
    orb_ratio_test: float = 0.75
    diff_min_contour_area: int = 40
    resize_target_width: int = 900

    # ---- OCR text QA ----
    ocr_token_match_min_ratio: float = 0.60  # fraction of tokens that must match to call it "Present"

    # ---- Body diff ----
    body_diff_context: int = 3

    # ---- CTA button background color ----
    # Every CTA button (the same "linked, colored <td> wrapping a nested
    # button table" element already located by the border-radius check)
    # must use this exact background color.
    cta_button_expected_bg: str = "#1867b2"

    # ---- Double-space check ----
    # Two or more consecutive literal space characters (or a run of
    # &nbsp;/regular-space that renders as a double space) anywhere in the
    # email's visible text is flagged. This is independent of
    # normalize_text()'s whitespace collapsing, which is only used for
    # fuzzy line-matching, not for detecting the underlying authoring bug.
    double_space_min_run: int = 2

    # ---- Dealer panel exact-match QA (case-sensitive, space-sensitive) ----
    # The fuzzy Content QA table (compare_source_to_html) intentionally
    # lowercases and collapses whitespace so it can still find a line that
    # moved position or has trivial formatting differences. That fuzziness
    # is exactly what must NOT apply here: this second, stricter pass
    # confirms the matched HTML line is byte-for-byte identical to the
    # Excel cell's line, casing and internal spacing included, so a
    # dealer's real name/address text is never silently "Present" with a
    # wrong capital letter or a missing/extra space baked in.
    dealer_panel_exact_match: bool = True

    # ---- Dealer phone/landline number format ----
    # Exactly three accepted formats, matched by pattern (the digits
    # themselves always come from the Excel cell, never hardcoded here):
    #   Format 1 (mobile, +91):     "Tel.: +91 82228 22201"
    #   Format 2 (toll-free/1800):  "Tel.: 1800 103 2211"
    #   Format 3 (STD landline):    "040-27676946"
    # Regexes are anchored to the whole string (after trim) so a number
    # with the right digits but wrong grouping/spacing/punctuation still
    # fails, e.g. "+918222822201" or "Tel: +91-82228-22201" or
    # "040 27676946" are all rejected even though the digits match.
    phone_format_mobile_intl: str = r"^Tel\.:\s\+91\s\d{5}\s\d{5}$"
    phone_format_tollfree: str = r"^Tel\.:\s1800\s\d{3}\s\d{4}$"
    phone_format_std_landline: str = r"^\d{2,5}-\d{6,8}$"

    # ---- "Follow Us" footer font (WARN-only, never FAIL) ----
    # Some (not all) email templates render "Follow Us" above the social
    # icon row using bmwtypenextregular. When the text is present but the
    # font isn't declared, this is only ever a WARN (never a Fail) — see
    # app.py's run_style_qa "Follow Us font" rule.
    follow_us_expected_font: str = "bmwtypenextregular"

    # ---- Priority order (highest wins). Do not reorder without intent. ----
    priority_order = (
        "manual_text",
        "master_jpg",
        "master_pdf",
        "master_html_zip",
        "dealer_dropdown",
        "excel",
    )


DEFAULT_CONFIG = QAConfig()

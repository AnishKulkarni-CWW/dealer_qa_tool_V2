"""
Feature 11 — Banner Text QA.

Compares expected Headline / Subheadline / Dealer Name against the OCR'd
text of the (already-cropped) banner image, highlighting missing / extra /
wrong words at the token level.

--------------------------------------------------------------------------
Headline vs Subheadline vs Dealer Name fix
--------------------------------------------------------------------------
Previously this module compared BOTH the expected Headline and the
expected Subheadline against the *same* flat, whole-banner OCR string.
That's fine when a banner only has one line of text, but real banners
stack a large-font Headline directly above a smaller-font Subheadline
(e.g. "DOMINATE EVERYDAY. YOUR WAY." over "DRIVE YOUR MATCH."). Comparing
both fields against one undivided blob meant a genuine subheadline-only
issue (or headline-only issue) could read as a failure on both fields, or
mask a real mismatch in one field with a lucky token match from the
other field's words appearing nearby in the blob.

`run_banner_text_qa` accepts the *clustered* OCR output from
`ocr_engine.cluster_lines_by_size()` (see ocr_engine.py) — three
font-size bands are used:
  - Band 1 (largest font)  -> Headline
  - Band 2 (next size down) -> Subheadline
  - Band 3+ (smallest)      -> Dealer Name

This matters because a banner commonly stacks Headline / Subheadline /
Dealer Name in three progressively smaller font sizes (e.g. "ENGINEERED
TO DELIVER OPTIMAL PERFORMANCE EVERY DAY." / "BMW FUEL ADDITIVES." /
"Bavaria Motors") — without a dedicated third band, the Dealer Name text
gets swept into the Subheadline band's OCR text since it's the next
distinct line, which then either fails the Subheadline check outright
(unexpected extra words) or wrongly counts as passing it.

--------------------------------------------------------------------------
Content-aware Dealer Name line matching (font-size-tie fix)
--------------------------------------------------------------------------
Font-size banding alone still isn't enough on its own: real banners
frequently render Subheadline and Dealer Name at THE SAME font size
(e.g. "BMW FUEL ADDITIVES." and "Bavaria Motors" both OCR at a matching
17px line height), which collapses them into a single band with no
dedicated Dealer Name band at all — a plain "split the last line off"
positional guess then risks wrongly chopping a genuinely multi-line
Subheadline that has no dealer name on it at all.

Instead, whenever `expected_dealer_name` is known, this module calls
`ocr_engine.find_dealer_line()` directly against every raw OCR'd line
available on `clustered_lines` (across ALL bands, not just Subheadline's)
to find the one line whose words actually match the expected dealer
name by content, not by position. This is strictly additive: a banner
with no dealer name rendered at all will simply find no match and fall
through to the prior band-based behaviour unchanged, so nothing is ever
invented that isn't really there.

Backward compatibility: `run_banner_text_qa` still accepts a plain OCR
string via `ocr_text` for the Dealer Name check and as a fallback if no
clustered data is supplied (old call sites keep working, just without
the headline/subheadline/dealer-name band separation).
"""

import re
from dataclasses import dataclass
from typing import List, Optional

from . import ocr_engine as _ocr_engine
from .config import DEFAULT_CONFIG
from .results import ModuleResult, PASS, FAIL, WARN


def _tokenize(text: str, match_case: bool = False) -> List[str]:
    """
    Tokenizes into words for comparison. By default (match_case=False)
    everything is lowercased first, same as before. When match_case=True,
    casing is preserved, so e.g. "bmw" in the OCR text will NOT match an
    expected "BMW" — used for a stricter, case-sensitive QA pass.
    """
    src = text or ""
    if not match_case:
        src = src.lower()
    return re.findall(r"[A-Za-z0-9]+", src)


@dataclass
class WordDiff:
    missing: List[str]
    extra: List[str]


def diff_words(expected: str, found: str, match_case: bool = False) -> WordDiff:
    exp_tokens = _tokenize(expected, match_case=match_case)
    found_tokens = set(_tokenize(found, match_case=match_case))
    missing = [t for t in exp_tokens if t not in found_tokens]
    exp_set = set(exp_tokens)
    extra = [t for t in _tokenize(found, match_case=match_case) if t not in exp_set]
    return WordDiff(missing=missing, extra=extra)


def _field_status(expected: str, found: str, config, match_case: bool = False) -> tuple:
    if not expected.strip():
        return WARN, "No expected value provided for this field — skipped."
    wd = diff_words(expected, found, match_case=match_case)
    exp_tokens = _tokenize(expected, match_case=match_case)
    if not exp_tokens:
        return WARN, "Expected value has no comparable words."
    matched_ratio = 1 - (len(wd.missing) / len(exp_tokens))
    if matched_ratio >= config.ocr_token_match_min_ratio and not wd.missing:
        return PASS, "All expected words found in banner OCR text."
    parts = []
    if wd.missing:
        parts.append(f"Missing word(s): {', '.join(wd.missing)}")
    if wd.extra:
        parts.append(f"Unexpected/extra word(s) nearby: {', '.join(wd.extra[:10])}")
    status = FAIL if matched_ratio < config.ocr_token_match_min_ratio else WARN
    return status, "; ".join(parts) if parts else "Partial match."


def _strip_trailing_dealer_name(expected_text: str, dealer_name: str) -> str:
    """
    Removes a trailing occurrence of `dealer_name` from `expected_text`,
    if present. Used so that if the caller's "expected Subheadline" (or
    "expected Headline") string was built by combining multiple OCR'd
    lines together — and one of those lines was actually the Dealer Name
    line, not real Subheadline copy — the Dealer Name words don't end up
    as part of what Subheadline is expected to contain. Dealer Name is
    QA'd separately in its own row, so it should never also need to
    appear in the Subheadline's expected text for that row to pass.
    Case-insensitive, whitespace-tolerant; only strips a match at the very
    end of the string (the dealer name always comes last / smallest-font,
    directly below Subheadline), so it won't accidentally remove dealer
    words that happen to appear earlier inside real subheadline copy.
    """
    text = expected_text or ""
    name = (dealer_name or "").strip()
    if not text.strip() or not name:
        return text
    pattern = re.escape(name).replace(r"\ ", r"\s+")
    # Match the dealer name at the end of the string, allowing trailing
    # punctuation/whitespace after it (e.g. "...ADDITIVES. Bavaria Motors").
    stripped = re.sub(rf"\s*{pattern}\s*[.,]?\s*$", "", text, flags=re.IGNORECASE)
    return stripped.strip()


def run_banner_text_qa(
    expected_headline: str,
    expected_subheadline: str,
    expected_dealer_name: str,
    ocr_text: str,
    config=DEFAULT_CONFIG,
    clustered_lines: Optional[object] = None,  # ocr_engine.ClusteredLines, kept optional for back-compat
    match_case: bool = True,  # Case-sensitive comparison is always on ("BMW" != "bmw")
) -> ModuleResult:
    result = ModuleResult(module_name="Banner Text QA")

    any_expected = any(v.strip() for v in (expected_headline, expected_subheadline, expected_dealer_name))
    if not any_expected:
        result.notes.append("No headline/subheadline/dealer-name expected values provided — banner text QA skipped.")
        return result

    # Filter: the Dealer Name shouldn't be expected as part of the
    # Subheadline (or Headline) row — it's QA'd on its own row below.
    if expected_dealer_name.strip():
        expected_subheadline = _strip_trailing_dealer_name(expected_subheadline, expected_dealer_name)
        expected_headline = _strip_trailing_dealer_name(expected_headline, expected_dealer_name)

    if clustered_lines is not None:
        headline_lines = list(clustered_lines.headline_lines)
        subheadline_lines = list(clustered_lines.subheadline_lines)
        other_lines = list(clustered_lines.other_lines)

        # Content-aware Dealer Name line search: look across ALL bands'
        # raw lines (not just whichever band geometry happened to place
        # it in) for the one line whose words actually match the
        # expected dealer name. This is the authoritative source for
        # `dealer_found` whenever it succeeds — far more reliable than a
        # positional "last line of Subheadline" guess, since it only
        # ever matches a line that genuinely contains the dealer name's
        # words, in either direction (see find_dealer_line() docstring
        # in ocr_engine.py for the full rationale).
        dealer_match_line = None
        if expected_dealer_name.strip():
            all_band_lines = (
                (getattr(clustered_lines, "headline_lines", None) or [])
                + (getattr(clustered_lines, "subheadline_lines", None) or [])
                + (getattr(clustered_lines, "other_lines", None) or [])
            )
            # A caller that already ran extract_clustered_text() WITH
            # expected_dealer_name will have this pre-populated — reuse
            # it directly rather than re-searching. Otherwise (e.g. an
            # older clustering built without the dealer name known yet)
            # search now, across every line we can see.
            pre_matched = getattr(clustered_lines, "dealer_line", None)
            dealer_match_line = pre_matched or _ocr_engine.find_dealer_line(
                all_band_lines, expected_dealer_name
            )

        if dealer_match_line is not None:
            # Remove the matched line from whichever band it's still
            # sitting in (by identity, so a repeated line of the same
            # text elsewhere on the banner isn't also stripped out) so
            # it never also pollutes Headline/Subheadline's own text.
            headline_lines = [l for l in headline_lines if l is not dealer_match_line]
            subheadline_lines = [l for l in subheadline_lines if l is not dealer_match_line]
            other_lines = [l for l in other_lines if l is not dealer_match_line]
            dealer_found = dealer_match_line.text
        else:
            # No confident content match — fall back to whatever
            # geometric band(s) the OCR engine assigned as "smaller than
            # Subheadline", same as the original behaviour. If there
            # isn't one, `dealer_found` stays empty here and is picked
            # up by the single-band whole-blob fallback further below.
            dealer_found = " ".join(l.text for l in other_lines)

        headline_found = " ".join(l.text for l in headline_lines)
        subheadline_found = " ".join(l.text for l in subheadline_lines)

        # If OCR only detected a single font band (e.g. banner really only
        # has one line of text), fall back to the whole blob for whichever
        # expected field didn't get its own band, rather than reporting a
        # false "Missing word(s)" for every word.
        if expected_headline.strip() and not headline_found.strip():
            headline_found = ocr_text
        if expected_subheadline.strip() and not subheadline_found.strip():
            subheadline_found = ocr_text
        if expected_dealer_name.strip() and not dealer_found.strip():
            dealer_found = ocr_text

        if dealer_match_line is not None:
            dealer_match_note = "the Dealer Name line was identified by matching its words against the expected dealer name (content-aware match, independent of font-size band)"
        else:
            dealer_match_note = f"{len(clustered_lines.other_lines)} dealer-name-band line(s) used (font-size band only — no confident content match found)"
        note = (
            f"Headline/Subheadline matched by OCR font-size band "
            f"(engine detected {len(clustered_lines.headline_lines)} headline-band line(s), "
            f"{len(clustered_lines.subheadline_lines)} subheadline-band line(s)); "
            f"{dealer_match_note}."
        )
        result.notes.append(note)
    else:
        # Back-compat path: no clustered data supplied, compare all three
        # against the full blob as before.
        headline_found = ocr_text
        subheadline_found = ocr_text
        dealer_found = ocr_text

    fields = [
        ("Headline", expected_headline, headline_found),
        ("Subheadline", expected_subheadline, subheadline_found),
        ("Dealer Name", expected_dealer_name, dealer_found),
    ]

    if match_case:
        result.notes.append("Case-sensitive matching enabled — casing differences (e.g. \"bmw\" vs \"BMW\") count as a mismatch.")

    for label, expected, found_text in fields:
        status, detail = _field_status(expected, found_text, config, match_case=match_case)
        result.add("Banner Text", label, status, detail=detail, expected=expected, found=found_text[:300])

    return result

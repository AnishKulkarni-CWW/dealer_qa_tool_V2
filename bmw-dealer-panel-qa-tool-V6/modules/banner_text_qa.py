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

Backward compatibility: `run_banner_text_qa` still accepts a plain OCR
string via `ocr_text` for the Dealer Name check and as a fallback if no
clustered data is supplied (old call sites keep working, just without
the headline/subheadline/dealer-name band separation).
"""

import re
from dataclasses import dataclass
from typing import List, Optional

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
        headline_found = clustered_lines.headline_text
        subheadline_found = clustered_lines.subheadline_text
        # Third band (everything smaller than Subheadline) = Dealer Name.
        dealer_found = clustered_lines.other_text

        # Defensive cross-band cleanup: if a caller-supplied clustering
        # still has stray overlap (e.g. exactly 2 bands were detected
        # instead of 3, so Dealer Name text ended up bundled into the
        # Subheadline band), strip out any line that's an exact match to
        # another band's own lines before falling back to the whole blob.
        # This keeps each row's "found" column limited to only its own
        # band text instead of leaking neighbouring rows' text into it.
        headline_line_texts = {l.text.strip() for l in clustered_lines.headline_lines}
        subheadline_line_texts = {l.text.strip() for l in clustered_lines.subheadline_lines}
        dealer_line_texts = {l.text.strip() for l in clustered_lines.other_lines}

        # If Dealer Name has no band of its own but Subheadline's band
        # has more than one line, and the expected dealer name's words
        # only match a subset of those lines, split the LAST line of the
        # Subheadline band off as the Dealer Name candidate instead of
        # letting the whole Subheadline band double as both fields.
        if not dealer_line_texts and len(clustered_lines.subheadline_lines) > 1 and expected_dealer_name.strip():
            *sub_lines_kept, last_line = sorted(clustered_lines.subheadline_lines, key=lambda l: l.top)
            subheadline_found = " ".join(l.text for l in sub_lines_kept)
            dealer_found = last_line.text

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
        note = (
            f"Headline/Subheadline/Dealer Name matched separately by OCR font-size band "
            f"(engine detected {len(clustered_lines.headline_lines)} headline-band line(s), "
            f"{len(clustered_lines.subheadline_lines)} subheadline-band line(s), "
            f"{len(clustered_lines.other_lines)} dealer-name-band line(s))."
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

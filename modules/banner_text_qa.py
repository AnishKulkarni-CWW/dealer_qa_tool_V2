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

--------------------------------------------------------------------------
Content-first field matching (font-size banding demoted to a fallback)
--------------------------------------------------------------------------
Font-size banding still could not separate two lines OCR'd at the same
size. Real, measured case: a banner reading

    ENGINEERED TO DELIVER OPTIMAL      (23px)
    PERFORMANCE EVERY DAY.             (23px)
    BMW FUEL ADDITIVES.                (17px)
    Infinity Cars                      (22px)   <- dealer name

puts the dealer name 4% away from the headline lines — well inside the
jitter tolerance that has to exist to absorb OCR measurement noise — so
geometry merges the dealer name into the Headline band. The expected
Headline OCR'd from the Master then reads "ENGINEERED TO DELIVER OPTIMAL
PERFORMANCE EVERY DAY. Infinity Cars", and every dealer's email is failed
for missing words it was never supposed to contain.

So this module now assigns lines to fields by CONTENT first (see
`ocr_engine.assign_lines_by_content`), using the font-size bands only as a
per-field fallback when content assignment finds nothing, and the flat
whole-banner blob as a final fallback after that. Content assignment is
deliberately conservative — a line must have most of its own words in a
field's expected text to be assigned to it — so genuinely wrong banner
copy is never absorbed into a field to make it pass; it stays unmatched
and is reported in the notes.

--------------------------------------------------------------------------
`known_dealer_names` — the Master may carry a DIFFERENT dealer
--------------------------------------------------------------------------
The expected Headline/Subheadline are OCR'd from the Master creative, and
one Master is routinely reused across every dealer version of a campaign
(only the dealer line changes). So the Master's own dealer name — another
dealer entirely — is what leaks into the expected copy above. Stripping
only THIS email's dealer name cannot remove it.

Callers can now pass `known_dealer_names` (every dealer in the Excel
sheet); a trailing name belonging to ANY of them is stripped from the
expected Headline/Subheadline before comparison. Only ever at the end of
the string, and only a name that is genuinely on that list, so real
banner copy is never touched.
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
    """
    Word-level difference between the expected copy and what was OCR'd.

    Matching is tolerant of OCR word-splitting and word-merging (see
    `ocr_engine.spacing_tolerant_match`) and of nothing else. The expected
    Headline is OCR'd from the Master creative while the found text is
    OCR'd from the dealer's email — two renderings of the same artwork —
    and Tesseract does not always break tightly-tracked display type at the
    same place in both. A real case: the Master read the i7 badge line as
    the single token "THEI7" and the email read it as "THE" + "i7", so a
    pixel-identical banner was reported as `Missing word(s): THEI7`.

    Only exact character-for-character reconciliation across CONSECUTIVE
    tokens is accepted, so a genuinely wrong or absent word is still
    reported as missing exactly as before.
    """
    exp_tokens = _tokenize(expected, match_case=match_case)
    found_tokens = _tokenize(found, match_case=match_case)
    matched_exp, matched_found = _ocr_engine.spacing_tolerant_match(exp_tokens, found_tokens)
    missing = [t for i, t in enumerate(exp_tokens) if i not in matched_exp]
    # `extra` keeps its original, deliberately lenient set-membership rule
    # (a word that appears anywhere in the expected copy is never "extra"),
    # with anything the reconciliation consumed removed as well.
    exp_set = set(exp_tokens)
    extra = [
        t for j, t in enumerate(found_tokens)
        if j not in matched_found and t not in exp_set
    ]
    return WordDiff(missing=missing, extra=extra)


def _squash(text: str, match_case: bool = False) -> str:
    """Letters and digits only, all spacing removed."""
    t = text if match_case else text.lower()
    return re.sub(r"[^0-9A-Za-z]", "", t)


def _field_status(expected: str, found: str, config, match_case: bool = False,
                  space_insensitive: bool = False) -> tuple:
    if not expected.strip():
        return WARN, "No expected value provided for this field — skipped."
    wd = diff_words(expected, found, match_case=match_case)

    # `space_insensitive` is OFF by default, so the comparison is exactly
    # as strict as it has always been. It is switched on by app.py for one
    # specific case only: when the RapidOCR fallback engine is in use.
    # That engine merges words on tightly-tracked display type - it reads
    # "Bavaria Motors" as "BavariaMotors" - which would otherwise report
    # every word of a perfectly correct banner as missing. Tesseract and
    # PaddleOCR space words correctly, so they never take this path and a
    # genuine spacing defect in the artwork is still caught by them.
    if space_insensitive and wd.missing:
        squashed_found = _squash(found, match_case=match_case)
        if squashed_found:
            wd = WordDiff(
                missing=[w for w in wd.missing
                         if _squash(w, match_case=match_case) not in squashed_found],
                extra=wd.extra,
            )
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



def _dealer_field_status(expected: str, matched_line_text: str, banner_ocr_text: str,
                         config, match_case: bool = False,
                         space_insensitive: bool = False) -> tuple:
    """
    Status for the Dealer Name row.

    Kept separate from `_field_status` because the "field not present at
    all" case means something completely different for Dealer Name than it
    does for Headline or Subheadline.

    What used to happen: when no dealer-name line could be found on the
    banner, the generic fallback chain compared the expected dealer name
    against the WHOLE banner text blob. On a BMW template whose dealer
    block lives in the email body — which is most of them — that produced,
    on every single adapt:

        Fail | Missing word(s): Bird, Automotive; Unexpected/extra word(s)
             | nearby: ALL, IN, NO, MORE, EXCUSES, DRIVE, YOUR, MATCH, ...
        Expected: Bird Automotive
        Found:    ALL-IN, NO MORE EXCUSES. DRIVE YOUR MATCH WITH SMART ...

    which is noise: it lists the headline as "extra dealer-name words",
    duplicates the dedicated "Dealer exists in Banner" check, and buries
    any real dealer-name defect underneath. Three honest outcomes instead:

      - a dealer-name line was located  -> ordinary word-level comparison
      - no line, but the name IS in the banner text somewhere -> WARN
      - the name is nowhere on the banner -> one clear message, and the
        `found` column is left empty rather than filled with the headline
        (WARN by default; see config.banner_dealer_name_missing_is_fail)
    """
    if not expected.strip():
        return WARN, "No expected value provided for this field — skipped."

    if matched_line_text.strip():
        return _field_status(expected, matched_line_text, config,
                             match_case=match_case, space_insensitive=space_insensitive)

    if banner_ocr_text.strip():
        wd = diff_words(expected, banner_ocr_text, match_case=match_case)
        if not wd.missing:
            return WARN, (
                f"'{expected.strip()}' appears in the banner text but not as its own "
                "dealer-name line — check that it is set as a separate line on the artwork."
            )

    detail = (
        f"No dealer-name line was found on this banner. On many BMW templates the dealer "
        f"block sits in the email body rather than on the banner artwork — the separate "
        f"'Dealer exists in Banner' check covers that case."
    )
    status = FAIL if getattr(config, "banner_dealer_name_missing_is_fail", False) else WARN
    return status, detail


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
    # A brand prefix immediately before the name is stripped too, since
    # banners routinely render "BMW Bird Automotive" for a dealer the Excel
    # sheet calls "Bird Automotive".
    stripped = re.sub(rf"\s*(?:BMW\s+)?{pattern}\s*[.,]?\s*$", "", text, flags=re.IGNORECASE)
    return stripped.strip()


def _strip_any_dealer_name(expected_text: str, dealer_names) -> str:
    """
    Strips a trailing dealer name belonging to ANY known dealer, not just
    the one this email is for.

    This exists because the expected Headline / Subheadline are OCR'd from
    the MASTER creative, and the master frequently carries a DIFFERENT
    dealer than the email under test — a master built for "Bavaria Motors"
    is routinely used to QA an "Infinity Cars" mailer. Without this, the
    master's own dealer line gets swept into the expected Subheadline
    ("BMW FUEL ADDITIVES. Bavaria Motors") and the email under test is
    then failed for not containing another dealer's name, which it could
    never contain and should never contain.

    Only ever strips at the very END of the string and only a name that is
    genuinely on the caller-supplied known-dealer list, so real copy is
    never touched. Longest names are tried first so "Krishna Automobiles"
    is not half-stripped by "Krishna Automotive".
    """
    text = expected_text or ""
    if not text.strip() or not dealer_names:
        return text
    for name in sorted({str(n or "").strip() for n in dealer_names if str(n or "").strip()},
                       key=len, reverse=True):
        stripped = _strip_trailing_dealer_name(text, name)
        if stripped != text:
            return stripped
    return text


def run_banner_text_qa(
    expected_headline: str,
    expected_subheadline: str,
    expected_dealer_name: str,
    ocr_text: str,
    config=DEFAULT_CONFIG,
    clustered_lines: Optional[object] = None,  # ocr_engine.ClusteredLines, kept optional for back-compat
    match_case: bool = True,  # Case-sensitive comparison is always on ("BMW" != "bmw")
    space_insensitive: bool = False,  # only set when the RapidOCR fallback engine is active
    known_dealer_names: Optional[List[str]] = None,  # every dealer in the Excel sheet, if available
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

    # ...and neither should ANOTHER dealer's name, which is what leaks in
    # when the Master creative was built for a different dealer than the
    # email under test (see _strip_any_dealer_name). Runs second so the
    # email's own dealer name is always stripped first.
    if known_dealer_names:
        _sub_before, _head_before = expected_subheadline, expected_headline
        expected_subheadline = _strip_any_dealer_name(expected_subheadline, known_dealer_names)
        expected_headline = _strip_any_dealer_name(expected_headline, known_dealer_names)
        if expected_subheadline != _sub_before or expected_headline != _head_before:
            result.notes.append(
                "A different dealer's name was found trailing the expected Headline/Subheadline "
                "(the Master creative carries another dealer than this email) and was removed "
                "before comparison — Dealer Name is checked on its own row instead."
            )

    headline_found = ""
    subheadline_found = ""
    dealer_found = ""
    match_method_note = ""

    if clustered_lines is not None:
        headline_lines = list(getattr(clustered_lines, "headline_lines", None) or [])
        subheadline_lines = list(getattr(clustered_lines, "subheadline_lines", None) or [])
        other_lines = list(getattr(clustered_lines, "other_lines", None) or [])
        pre_matched_dealer = getattr(clustered_lines, "dealer_line", None)

        all_band_lines = list(headline_lines) + list(subheadline_lines) + list(other_lines)
        if pre_matched_dealer is not None and pre_matched_dealer not in all_band_lines:
            all_band_lines.append(pre_matched_dealer)
        all_band_lines.sort(key=lambda l: getattr(l, "top", 0))

        # -----------------------------------------------------------------
        # PRIMARY: content-aware assignment.
        #
        # Each OCR'd line is attributed to Headline / Subheadline / Dealer
        # Name by what it actually says. This replaces font-size banding as
        # the primary mechanism because banding demonstrably cannot separate
        # lines of the same measured size — a dealer name set at 22px under
        # a 23px headline line is inside any workable jitter tolerance, so
        # geometry put the dealer name in the Headline band and failed a
        # banner that was completely correct. See
        # ocr_engine.assign_lines_by_content() for the full rationale.
        #
        # It is not allowed to weaken the QA: a line only matches a field
        # when most of the line's own words belong to that field's expected
        # text, so genuinely wrong copy stays unmatched and is reported.
        # -----------------------------------------------------------------
        assignment = _ocr_engine.assign_lines_by_content(
            all_band_lines,
            expected_headline=expected_headline,
            expected_subheadline=expected_subheadline,
            expected_dealer_name=expected_dealer_name,
        )

        headline_found = assignment.headline_text
        subheadline_found = assignment.subheadline_text
        dealer_found = assignment.dealer_text

        # -----------------------------------------------------------------
        # FALLBACK 1: the original font-size bands, used per-field and only
        # where content assignment found nothing. This is what keeps a
        # genuinely wrong banner reporting a real Fail with the real text
        # that IS on it, rather than an empty "found" column.
        # -----------------------------------------------------------------
        used_band_fallback = []
        if expected_headline.strip() and not headline_found.strip():
            headline_found = " ".join(l.text for l in headline_lines
                                      if l is not assignment.dealer_line)
            if headline_found.strip():
                used_band_fallback.append("Headline")
        if expected_subheadline.strip() and not subheadline_found.strip():
            subheadline_found = " ".join(l.text for l in subheadline_lines
                                         if l is not assignment.dealer_line)
            if subheadline_found.strip():
                used_band_fallback.append("Subheadline")
        if expected_dealer_name.strip() and not dealer_found.strip():
            # Only a line that genuinely LOOKS like the dealer name may be
            # used here. `other_lines` is "whatever fell into the smallest
            # font band", which on a banner with no dealer name at all is
            # just the subheadline or a legal strapline — accepting it made
            # the Dealer Name row report the headline as a wrong dealer
            # name. `find_dealer_line` is content-based, so it returns
            # nothing when there is nothing, which is the correct answer.
            if pre_matched_dealer is not None:
                dealer_found = pre_matched_dealer.text
            else:
                rescan = _ocr_engine.find_dealer_line(other_lines, expected_dealer_name)
                dealer_found = rescan.text if rescan is not None else ""
            if dealer_found.strip():
                used_band_fallback.append("Dealer Name")

        # -----------------------------------------------------------------
        # FALLBACK 2 (unchanged): whole-blob comparison for any field that
        # still has nothing, e.g. a banner with a single font size only.
        # -----------------------------------------------------------------
        used_blob_fallback = []
        if expected_headline.strip() and not headline_found.strip():
            headline_found = ocr_text
            used_blob_fallback.append("Headline")
        if expected_subheadline.strip() and not subheadline_found.strip():
            subheadline_found = ocr_text
            used_blob_fallback.append("Subheadline")
        # NOTE: Dealer Name deliberately has NO whole-blob fallback. Falling
        # back to the entire banner text guaranteed a Fail with a nonsense
        # "extra words" list on every template whose dealer block lives in
        # the email body. `_dealer_field_status` handles the not-found case
        # explicitly and honestly instead.

        note_parts = [
            f"Banner lines matched to fields by content "
            f"({len(assignment.headline_lines)} headline, "
            f"{len(assignment.subheadline_lines)} subheadline, "
            f"{1 if assignment.dealer_line is not None else 0} dealer-name line(s))"
        ]
        if used_band_fallback:
            note_parts.append(
                "fell back to OCR font-size band for: " + ", ".join(used_band_fallback)
            )
        if used_blob_fallback:
            note_parts.append(
                "fell back to whole-banner OCR text for: " + ", ".join(used_blob_fallback)
            )
        if assignment.unmatched_lines:
            unmatched_preview = "; ".join(l.text for l in assignment.unmatched_lines[:5])
            note_parts.append(
                f"{len(assignment.unmatched_lines)} banner line(s) matched no expected "
                f"field and were not attributed to one: {unmatched_preview}"
            )
        match_method_note = ". ".join(note_parts) + "."
        result.notes.append(match_method_note)
    else:
        # Back-compat path: no clustered data supplied, compare all three
        # against the full blob as before.
        headline_found = ocr_text
        subheadline_found = ocr_text
        dealer_found = ocr_text

    # A master that supplied nothing at all is worth saying out loud. Left
    # unexplained, both text rows just read "No expected value provided for
    # this field — skipped", which looks like the user forgot to fill
    # something in when in fact the Master banner crop or its OCR failed.
    if (clustered_lines is not None
            and not expected_headline.strip()
            and not expected_subheadline.strip()):
        result.notes.append(
            "No expected Headline or Subheadline was available from the Master, so those "
            "rows were skipped rather than checked. Confirm the Master banner was cropped "
            "correctly (the crop stops at the 'Dear' salutation) and that its text is "
            "legible — the banner text on this email was read fine."
        )

    fields = [
        ("Headline", expected_headline, headline_found),
        ("Subheadline", expected_subheadline, subheadline_found),
        ("Dealer Name", expected_dealer_name, dealer_found),
    ]

    if match_case:
        result.notes.append("Case-sensitive matching enabled — casing differences (e.g. \"bmw\" vs \"BMW\") count as a mismatch.")

    for label, expected, found_text in fields:
        if label == "Dealer Name":
            status, detail = _dealer_field_status(
                expected, found_text, ocr_text, config,
                match_case=match_case, space_insensitive=space_insensitive,
            )
        else:
            status, detail = _field_status(expected, found_text, config, match_case=match_case,
                                           space_insensitive=space_insensitive)
        result.add("Banner Text", label, status, detail=detail, expected=expected, found=found_text[:300])

    return result

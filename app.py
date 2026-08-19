import re
import html as html_escape_module
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from typing import List, Dict, Tuple, Optional

import pandas as pd
import streamlit as st
from bs4 import BeautifulSoup, Comment, Tag

# ---------------------------------------------------------------------
# Extended-feature modules (all optional; app works unchanged without them)
# ---------------------------------------------------------------------
from modules import excel_loader as ext_excel
from modules import dealer_select as ext_dealer
from modules import manual_mode as ext_manual
from modules import priority as ext_priority
from modules import master_image as ext_master_image
from modules import master_pdf as ext_master_pdf
from modules import master_html_zip as ext_master_html_zip
from modules import banner_detect as ext_banner_detect
from modules import banner_compare as ext_banner_compare
from modules import ocr_engine as ext_ocr
from modules import banner_text_qa as ext_banner_text_qa
from modules import body_qa as ext_body_qa
from modules import results_ui as ext_results_ui
from modules import excel_report as ext_excel_report
from modules import theme as ext_theme
from modules import website_link_qa as ext_website_link_qa

# OCR engine preference is fixed (was previously a sidebar radio choice).
# PaddleOCR is preferred, with automatic silent fallback to Tesseract if
# PaddleOCR isn't installed / its models aren't cached — see ocr_engine.py.
EXT_OCR_PREFER_KEY = "paddleocr"
from modules.results import ModuleResult as ExtModuleResult
from modules.config import DEFAULT_CONFIG as EXT_CFG


st.set_page_config(page_title="Dealer Panel QA", layout="wide")

# Full SaaS/Startup visual theme (colors, type, cards, buttons, tables —
# see modules/theme.py). This ONLY changes appearance; every widget below
# keeps its exact arguments, keys, and return values. The old two-rule
# dataframe-scroll fix is now part of the theme's stDataFrame styling.
ext_theme.inject()


# =========================================================
# Normalization utilities
# =========================================================

def normalize_text(text: str) -> str:
    if text is None:
        return ""
    text = str(text)
    text = text.replace("\xa0", " ")
    text = text.replace("\r", "\n")
    text = re.sub(r"[\t ]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    text = text.strip()
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"\s+", " ", text)
    return text.lower().strip()


def split_lines_keep_order(text: str) -> List[str]:
    lines = []
    for raw in str(text).splitlines():
        line = raw.strip()
        if line:
            lines.append(line)
    return lines


# =========================================================
# Excel: Mailers - NSC  sheet reader
# =========================================================

MAILERS_SHEET_CANDIDATES = ["Mailers - NSC ", "mailers-ncs", "mailers_ncs", "mailers ncs"]


def find_mailers_sheet(xl: pd.ExcelFile) -> Optional[str]:
    for name in xl.sheet_names:
        n = name.strip().lower()
        if n in MAILERS_SHEET_CANDIDATES:
            return name
    for name in xl.sheet_names:
        if "mailer" in name.strip().lower():
            return name
    return None


@dataclass
class DealerRow:
    dealer: str
    region: str
    panel_text: str
    # Lines that must render BOLD per spec: the dealer name (column C's
    # first line) plus every branch/city name (the first line of every
    # column block, including column C's own second line and every extra
    # column). Populated once at Excel-read time in
    # build_dealer_rows_from_df, since the column boundaries needed to
    # identify "first line of each block" are lost once everything is
    # flattened into panel_text. Empty for a DealerRow built any other
    # way (e.g. the Advanced QA manual-entry path), in which case the
    # bold-text check below has nothing to check and is skipped.
    bold_required_lines: List[str] = field(default_factory=list)


def build_dealer_rows_from_df(df: pd.DataFrame, sheet_name: str = "") -> List[DealerRow]:
    """
    Given an already-parsed DataFrame with (at least) 'Dealer', 'Region',
    and a 'Dealer Panel(s)'-named column, builds the full List[DealerRow]
    — including every additional, unlabeled branch/location column
    positioned AFTER the named panels column (see the docstring on
    read_dealer_panels_from_excel, which calls this function, for the
    full reasoning on why those extra columns matter and must be read).

    THIS IS THE SINGLE PLACE this column-reading logic lives. Every
    caller that turns a parsed Excel sheet into List[DealerRow] — whether
    from the default auto-detected sheet or from the sidebar's manual
    "Excel Sheet Selection" dropdown — MUST route through this function
    rather than re-implementing its own column mapping. The extra-column
    fix was previously applied only inside read_dealer_panels_from_excel
    itself; the manual-sheet-selection code path in the sidebar had its
    own separate, never-updated copy of the same column-mapping logic,
    so a user who explicitly picked a sheet from that dropdown (rather
    than leaving it on auto-detect) got the OLD, extra-columns-blind
    behaviour even after the fix shipped — confirmed against a real
    session where the sidebar's "Loaded N dealer row(s) from MANUALLY
    SELECTED sheet" message proved that code path was the one that ran.
    Routing both paths through this one function makes that class of
    bug (two implementations silently drifting apart) structurally
    impossible going forward.
    """
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    col_map = {}
    panels_col_position = None
    for pos, c in enumerate(df.columns):
        cl = c.lower().strip()
        if cl == "dealer":
            col_map["dealer"] = c
        elif cl == "region":
            col_map["region"] = c
        elif "dealer panel" in cl:
            col_map["panels"] = c
            panels_col_position = pos

    missing = [k for k in ("dealer", "panels") if k not in col_map]
    if missing:
        raise ValueError(
            f"Sheet '{sheet_name}' is missing expected column(s): {missing}. "
            f"Found columns: {list(df.columns)}"
        )

    # Every column after the "Dealer Panels" column is an additional
    # branch/location panel block for the same dealer.
    extra_panel_columns = list(df.columns[panels_col_position + 1:])

    rows: List[DealerRow] = []
    for _, r in df.iterrows():
        dealer = str(r.get(col_map.get("dealer", ""), "") or "").strip()
        region = str(r.get(col_map.get("region", ""), "") or "").strip()
        panels = str(r.get(col_map.get("panels", ""), "") or "").strip()
        if panels.lower() == "nan":
            panels = ""

        extra_blocks = []
        for extra_col in extra_panel_columns:
            extra_val = str(r.get(extra_col, "") or "").strip()
            if extra_val and extra_val.lower() != "nan":
                extra_blocks.append(extra_val)

        combined_panel_text = "\n".join([b for b in [panels] + extra_blocks if b])

        # Bold-required lines: dealer name (column C's own first line)
        # plus every branch/city name (first line of EVERY column block —
        # column C's second line, and every extra column's own first
        # line). Computed here, not from combined_panel_text, because the
        # per-column boundaries needed to tell "this is a block's first
        # line" apart from "this is just some other line" only exist
        # before flattening.
        bold_required_lines: List[str] = []
        panels_own_lines = [ln.strip() for ln in panels.splitlines() if ln.strip()]
        if panels_own_lines:
            bold_required_lines.append(panels_own_lines[0])  # dealer name
            if len(panels_own_lines) > 1:
                bold_required_lines.append(panels_own_lines[1])  # column C's own city/area name
        for extra_val in extra_blocks:
            extra_own_lines = [ln.strip() for ln in extra_val.splitlines() if ln.strip()]
            if extra_own_lines:
                bold_required_lines.append(extra_own_lines[0])  # that branch's city/area name

        if combined_panel_text:
            rows.append(DealerRow(
                dealer=dealer, region=region, panel_text=combined_panel_text,
                bold_required_lines=bold_required_lines,
            ))

    return rows


def read_dealer_panels_from_excel(uploaded_file) -> Tuple[List[DealerRow], str]:
    """
    Reads the 'Mailers - NSC ' sheet. Handles a title row above the real
    header row by scanning the first few rows for one containing both
    'Dealer' and 'Region'. Column mapping and the extra unlabeled panel
    columns (a dealer's additional branch/location blocks — see
    build_dealer_rows_from_df's docstring for the full reasoning) are
    handled by build_dealer_rows_from_df, which this function calls.
    """
    xl = pd.ExcelFile(uploaded_file)
    sheet_name = find_mailers_sheet(xl)
    if sheet_name is None:
        raise ValueError(
            f"Could not find a 'Mailers - NSC ' sheet. Sheets found: {', '.join(xl.sheet_names)}"
        )

    raw = xl.parse(sheet_name, header=None, dtype=str)

    header_row_idx = None
    for i in range(min(10, len(raw))):
        row_vals = [str(v).strip().lower() for v in raw.iloc[i].tolist()]
        if "dealer" in row_vals and "region" in row_vals:
            header_row_idx = i
            break

    if header_row_idx is None:
        raise ValueError(
            f"Could not find a header row containing 'Dealer' and 'Region' in sheet '{sheet_name}'."
        )

    df = xl.parse(sheet_name, header=header_row_idx, dtype=str)
    rows = build_dealer_rows_from_df(df, sheet_name=sheet_name)
    return rows, sheet_name


def panel_text_to_lines(panel_text: str) -> List[str]:
    return split_lines_keep_order(panel_text)


# =========================================================
# HTML extraction (visible text)
# =========================================================

def html_to_visible_text(soup: BeautifulSoup) -> str:
    work = BeautifulSoup(str(soup), "html.parser")
    for tag in work(['script', 'style', 'noscript']):
        tag.decompose()
    for c in work.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()
    for br in work.find_all("br"):
        br.replace_with("\n")
    text = work.get_text(separator="\n")
    text = text.replace("\xa0", " ")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def html_to_visible_text_raw(soup: BeautifulSoup) -> str:
    """
    Same extraction as html_to_visible_text() (strip script/style/
    comments, turn <br> into newlines, &nbsp; into a real space) but
    WITHOUT collapsing runs of spaces/tabs down to one. html_to_visible_text
    intentionally collapses whitespace so fuzzy line-matching isn't
    tripped up by incidental formatting — but that collapsing would
    silently erase the exact thing the exact-match spacing check exists
    to find. That check must read this raw variant, not the collapsed
    one. (The double-space check uses html_to_rendered_text() below
    instead — see that function for why.)
    """
    work = BeautifulSoup(str(soup), "html.parser")
    for tag in work(['script', 'style', 'noscript']):
        tag.decompose()
    for c in work.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()
    for br in work.find_all("br"):
        br.replace_with("\n")
    text = work.get_text(separator="\n")
    text = text.replace("\xa0", " ")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def html_to_rendered_text(soup: BeautifulSoup) -> str:
    """
    Simulates what a browser actually SHOWS on screen, whitespace-wise —
    used specifically for the double-space check (run_double_space_qa),
    which must only flag a double space a reader would actually see, not
    HTML source-code formatting.

    Per standard HTML whitespace rules (the default white-space: normal,
    which this app's emails all use — no white-space: pre anywhere), a
    browser collapses ANY run of plain whitespace (spaces, tabs,
    newlines) down to exactly one rendered space, no matter how much
    indentation or how many line breaks are in the source. This is why
    an HTML file can be nicely tab-indented for readability — extra tabs
    between "BMW Bird Automotive" and its closing </td>, or inside a long
    indented paragraph — and still render as normal single-spaced text;
    those tabs are invisible to an actual reader and must be invisible to
    this check too.

    The ONE way to force a browser to render more than one consecutive
    visible space is &nbsp; (it does NOT collapse). So a genuine
    double-space authoring bug looks like "word&nbsp;&nbsp;word" or
    "word &nbsp;word" in the source — &nbsp; adjacent to a plain space or
    another &nbsp;. This function keeps &nbsp; as its own distinct
    character (U+00A0) rather than normalizing it to a plain space, so
    the caller can tell "collapsible source formatting" apart from
    "non-collapsible, actually-rendered extra space" — collapsing only
    runs of plain whitespace, never absorbing or collapsing &nbsp; itself.
    """
    work = BeautifulSoup(str(soup), "html.parser")
    for tag in work(['script', 'style', 'noscript']):
        tag.decompose()
    for c in work.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()
    for br in work.find_all("br"):
        br.replace_with("\n")
    text = work.get_text(separator="\n")

    # Collapse runs of PLAIN whitespace (space/tab/CR/LF) to a single
    # space, but never merge across an &nbsp; (U+00A0) — split on nbsp
    # boundaries first so it's never swallowed into a collapsed run.
    NBSP = "\xa0"
    parts = re.split(f"({NBSP})", text)
    collapsed_parts = []
    for part in parts:
        if part == NBSP:
            collapsed_parts.append(part)
        else:
            collapsed_parts.append(re.sub(r"[ \t\r]+", " ", part))
    text = "".join(collapsed_parts)

    # Newlines are block/line-break boundaries (from <br>, <p>, <td>,
    # etc.) — these ARE meaningful for where one visual line ends and
    # another begins, so, unlike the space run above, they're preserved
    # (only excess blank lines are trimmed) rather than collapsed into
    # the same single-space treatment as horizontal whitespace.
    text = re.sub(r"\n[ \t]*\n[ \t]*(\n[ \t]*)+", "\n\n", text)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    return text.strip()


def extract_body_greeting_slice(full_body_text: str, dealer_name: str) -> str:
    """
    Isolates just the greeting/body-copy portion of the email: from the
    word "Dear" up to (but not including) the sign-off line where the
    dealer name appears WITH "BMW" in front of it (e.g. body text reads
    "...regards, Bird Automotive" while the sign-off/dealer-panel further
    down reads "BMW Bird Automotive" — that "BMW <Dealer>" line marks the
    end of the body-copy section and the start of the dealer panel).

    This exists because the Dealer-in-Body check must only look at the
    actual body copy, not accidentally also match the dealer panel below
    it (which is already separately QA'd against the Excel sheet at the
    top of the report) — so a body missing the dealer's name wouldn't be
    silently marked Pass just because "BMW <Dealer>" appears further down
    in the panel.

    Falls back to the full text if "Dear" or a "BMW <dealer>" sign-off
    marker can't be located, so the check never silently breaks.
    """
    text = full_body_text or ""
    if not text.strip():
        return text

    dear_match = re.search(r"\bDear\b", text, flags=re.IGNORECASE)
    start = dear_match.start() if dear_match else 0

    end = len(text)
    if dealer_name and dealer_name.strip():
        # Look for "BMW <dealer name>" (dealer name possibly with minor
        # whitespace/punctuation differences), case-insensitive, anywhere
        # after the greeting — that marks the dealer-panel sign-off line.
        dealer_pattern = re.escape(dealer_name.strip())
        dealer_pattern = dealer_pattern.replace(r"\ ", r"\s+")
        bmw_dealer_match = re.search(
            rf"\bBMW\s+{dealer_pattern}\b", text[start:], flags=re.IGNORECASE
        )
        if bmw_dealer_match:
            end = start + bmw_dealer_match.start()

    return text[start:end].strip()


def _digit_sequence(text: str) -> str:
    """All digits in `text`, concatenated, in order — used to compare
    phone/landline numbers by their actual digit content regardless of
    spacing/punctuation differences (e.g. '82228 22201' vs '82228-22201')."""
    return re.sub(r"[^0-9]", "", text or "")


def _is_number_bearing_line(text: str) -> bool:
    """True if this line is substantially a number (phone/landline/etc.)
    rather than prose that merely contains a digit somewhere. Requires at
    least 5 digits so short incidental numbers (a year, a floor number)
    don't get pulled into the strict digit-exact path below."""
    digits = _digit_sequence(text)
    return len(digits) >= 5


_DOMAIN_OR_EMAIL_RE = re.compile(
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+",
    re.IGNORECASE,
)


def _extract_domain_or_email(text: str) -> Optional[str]:
    """
    Pulls out the actual domain/URL/email token from a line (e.g.
    "Website: www.BirdAuto.com" -> "www.birdauto.com",
    "Email: sales@BirdAuto.com" -> "sales@birdauto.com"), lowercased so
    two differently-cased renderings of the identical address still
    compare equal. Returns None if the line has no domain-shaped token.
    """
    m = _DOMAIN_OR_EMAIL_RE.search(text or "")
    if not m:
        return None
    domain = m.group(0).lower()
    # If there's an email local-part immediately before the domain
    # (word@domain), include it -- "sales@birdauto.com" must not be
    # treated as equal to a line containing only "birdauto.com".
    before = (text or "")[: m.start()]
    email_local_match = re.search(r"([a-z0-9._%+-]+)@$", before, re.IGNORECASE)
    if email_local_match:
        return f"{email_local_match.group(1).lower()}@{domain}"
    return domain


def _is_url_bearing_line(text: str) -> bool:
    """True if this line's primary content is a domain/URL/email address
    (Website:/Email: dealer-panel rows) rather than prose that merely
    happens to contain a word with a dot in it."""
    return _extract_domain_or_email(text) is not None


# Words that appear in nearly every dealer's panel line and therefore
# carry no discriminating power when scoring a fuzzy text match — see
# find_best_match()'s final fallback below. Deliberately narrow (panel-
# specific scaffold only): general English stopwords are NOT included
# here, since dealer/address text needs its real words (including short
# common ones) to count toward a match.
_PANEL_SCAFFOLD_WORDS = {
    "bmw", "pvt", "ltd", "tel", "website", "email",
    "com", "www", "http", "https", "mailto", "dear",
}


def find_best_match(source_lines: List[str], target: str) -> Optional[Tuple[int, str]]:
    """
    Finds the source_lines entry that best corresponds to `target`
    (an Excel dealer-panel line), used both to report Present/Missing
    and — via raw_line_text_from_html() — to locate the exact HTML text
    for the stricter case/spacing/format checks.

    Three content types get a DELIBERATELY STRICT, exact check instead of
    fuzzy matching, and — critically — these strict checks run BEFORE the
    loose substring/token-overlap fallback, not as a fallback after it:

    1. Number-bearing targets (phone/landline numbers): only an identical
       digit sequence counts as a match. Token-overlap scoring is unsafe
       here — a wrong number differing only in its last few digits still
       shares most tokens with the correct one (e.g. Excel "...22201" vs
       HTML "...22299" share 3 of 4 tokens) and would otherwise pass.

    2. URL/email-bearing targets (Website:/Email: lines): only an
       identical domain/email counts. Scaffold words ("website", "email",
       the ".com" TLD) are common enough that two completely different
       domains can still share 2+ tokens purely on that scaffolding.

    3. General text (dealer names, addresses, panel prose): NOT given a
       dedicated exact-only block, but the final fallback below still
       discounts panel-wide scaffold words ("bmw", "pvt", "ltd", ...) for
       the same reason — those words alone are not evidence of a match
       between two different dealers.

    These strict checks run BEFORE the loose "is one line a substring of
    the other" shortcut specifically because that shortcut can match a
    bare label fragment — e.g. HTML text "Tel.:" is a substring of target
    "Tel.: +91 82228 22201" — and return on that fragment alone, even
    though the target's actual number is a SEPARATE line elsewhere in the
    HTML. This happens routinely for a correctly hyperlinked Tel./Website
    value, since wrapping it in <a> splits it onto its own text node
    during extraction, separate from its label. A label substring is not
    evidence the real number/domain is present anywhere at all, so for
    these two content types the exact check must be authoritative, not a
    fallback that only runs once the (unsafe, for these shapes) loose
    check has already failed to find anything.
    """
    t = normalize_text(target)
    if not t:
        return None

    if _is_number_bearing_line(target):
        target_digits = _digit_sequence(target)
        for i, line in enumerate(source_lines):
            if _digit_sequence(line) == target_digits:
                return i, line
        return None

    if _is_url_bearing_line(target):
        target_domain = _extract_domain_or_email(target)
        for i, line in enumerate(source_lines):
            if _extract_domain_or_email(line) == target_domain:
                return i, line
        return None

    # Loose substring check: HTML line n is (or contains, or is contained
    # by) the target t. Deliberately requires the SHORTER side to cover a
    # meaningful proportion of the LONGER side, not just any substring
    # match — a bare short fragment (e.g. a page's standalone "BMW" logo
    # alt-text/heading elsewhere in the email) is trivially a substring of
    # a longer target like "BMW Bird Automotive", and returning on that
    # alone — before the real, full "BMW Bird Automotive" line elsewhere
    # in the document is ever considered — is exactly the same class of
    # false-match bug already fixed for phone/URL/scaffold-word cases
    # above: a short generic fragment must not be allowed to stand in for
    # much longer, more specific target content. The proportion floor is
    # deliberately lenient (covers genuine truncation/partial-render
    # cases, e.g. HTML "Tel." matching target "Tel. Number") while still
    # rejecting a single short word matching a multi-word target.
    best_substring_match = None
    best_substring_len = 0
    for i, line in enumerate(source_lines):
        n = normalize_text(line)
        if not n:
            continue
        if n == t:
            return i, line
        shorter, longer = (n, t) if len(n) <= len(t) else (t, n)
        if shorter in longer and len(shorter) / len(longer) >= 0.6:
            if len(shorter) > best_substring_len:
                best_substring_len = len(shorter)
                best_substring_match = (i, line)
    if best_substring_match is not None:
        return best_substring_match

    # General fallback for everything else (dealer names, addresses, panel
    # prose): proportional, stopword-discounted token overlap instead of a
    # flat absolute count. A flat "2+ shared tokens" threshold has the
    # SAME failure mode as the phone/URL cases above — dealer-panel text
    # is full of scaffold words that appear on nearly every dealer's line
    # ("bmw", "pvt", "ltd", "tel", "website", "email"), so two lines
    # belonging to COMPLETELY DIFFERENT dealers can still share 2-3 tokens
    # on scaffold words alone (e.g. "BMW Bird Automotive Pvt Ltd" vs
    # "BMW Prestige Motors Pvt Ltd" share {"bmw","pvt","ltd"} = score 3,
    # while sharing NONE of the words that actually identify the dealer).
    # Scoring here discounts those scaffold words and requires the
    # MEANINGFUL (non-scaffold) overlap to cover a majority of the
    # target's own meaningful content, so a match still requires the
    # actual distinguishing words to line up — not just the boilerplate
    # around them. This still tolerates real formatting noise (reordered
    # words, "Pvt Ltd" vs "Private Limited", extra corporate-suffix words)
    # since it's proportional rather than exact.
    target_tokens = set(re.findall(r"[a-z0-9]+", t))
    meaningful_target = target_tokens - _PANEL_SCAFFOLD_WORDS

    best_score = 0
    best = None
    for i, line in enumerate(source_lines):
        n = normalize_text(line)
        line_tokens = set(re.findall(r"[a-z0-9]+", n))
        if not line_tokens:
            continue
        overlap = target_tokens & line_tokens
        meaningful_overlap = overlap - _PANEL_SCAFFOLD_WORDS

        if not meaningful_target:
            # Target itself is entirely scaffold words (rare, e.g. a
            # standalone "Tel." label with no number) -- fall back to the
            # original absolute-count behaviour so this case never
            # becomes impossible to match.
            is_match = len(overlap) >= 2
        elif len(meaningful_target) == 1:
            # Very short distinguishing content -- require that one
            # meaningful token to actually be present.
            is_match = len(meaningful_overlap) >= 1
        else:
            is_match = (
                len(meaningful_overlap) >= 2
                and len(meaningful_overlap) / len(meaningful_target) >= 0.5
            )

        score = len(overlap)  # still used only to pick the BEST among matches, not to decide match/no-match
        if is_match and score > best_score:
            best_score = score
            best = (i, line)

    return best


@dataclass
class CheckResult:
    item: str
    status: str


# =========================================================
# Exact-match (case-sensitive, space-sensitive) dealer panel QA
# =========================================================
#
# compare_source_to_html()/find_best_match() above are deliberately fuzzy
# (lowercased, whitespace-collapsed) so they can still find a dealer
# panel line even if it moved position or has trivial formatting
# differences — that fuzziness is the right behaviour for "is this line
# present at all". It is the WRONG behaviour for verifying the dealer's
# actual name/address/contact text is correct, because it would silently
# treat "Bird automotive" as identical to "Bird Automotive" or swallow an
# extra/missing space inside the line. This second pass runs only after
# a line has already been located by the fuzzy matcher above, and checks
# that exact HTML text against the Excel cell byte-for-byte (case and
# internal spacing both included).

def raw_line_text_from_html(html_raw: str, source_line: str) -> Optional[str]:
    """
    Returns the HTML's own visible-text rendering of the line that
    corresponds to `source_line` (located the same way compare_source_to_html
    finds it), WITHOUT the lowercasing/whitespace-collapsing that
    normalize_text()/html_to_visible_text() apply for fuzzy matching —
    i.e. exactly as the email actually renders it, casing and internal
    spacing preserved. Returns None if no corresponding line could be
    located at all (already reported as "Missing" by the fuzzy content
    check, so this exact check doesn't need to duplicate that).

    Two-step approach (deliberately does NOT assume the collapsed and raw
    text split into the same number of lines at the same indices, which
    would be a fragile assumption): first locate WHICH line matches using
    the existing robust fuzzy matcher on the collapsed text (so spacing/
    casing anomalies don't prevent the line from being found at all);
    then re-locate that same content directly inside the RAW (uncollapsed)
    text via a regex built from the matched line's own words, tolerant of
    any amount of whitespace between them — this recovers the actual
    as-rendered spacing without relying on the two texts staying index-
    aligned.

    Label reconstruction (number/URL-bearing targets only): a correctly
    built dealer panel wraps the phone number / website / email VALUE in
    its own <a> tag, e.g. `Tel.: <a href="tel:...">+91 82228 22201</a>`.
    HTML text extraction treats the label ("Tel.:") and the linked value
    as separate text nodes/lines, even though they render on the same
    visual line in the email. This is correct, required HTML structure —
    not a bug — so when the target has a label prefix (text before the
    first digit or before the domain/email), this function looks at the
    line immediately preceding the matched value line; if THAT line's
    text is a case-insensitive match for the target's own label portion,
    the two are joined back together (using the target's own spacing)
    so callers doing an exact-match/format comparison are comparing
    against what the email actually, correctly renders as one line —
    not an artifact of DOM text-node boundaries.
    """
    soup = BeautifulSoup(html_raw, "html.parser")
    collapsed_lines = split_lines_keep_order(html_to_visible_text(soup))
    match = find_best_match(collapsed_lines, source_line)
    if match is None:
        return None
    match_idx, collapsed_match_line = match

    raw_text = html_to_visible_text_raw(soup)

    def _locate_raw(collapsed_line: str) -> Optional[str]:
        words = collapsed_line.split(" ")
        if not words:
            return collapsed_line
        pattern = r"\s+".join(re.escape(w) for w in words if w)
        m = re.search(pattern, raw_text)
        return m.group(0) if m else None

    raw_value = _locate_raw(collapsed_match_line)
    if raw_value is None:
        raw_value = collapsed_match_line  # fallback: shouldn't happen, see below

    if _is_number_bearing_line(source_line) or _is_url_bearing_line(source_line):
        label_prefix_match = re.match(r"^(.*?)[:\s]*([+\d].*|[a-zA-Z0-9].*)$", source_line.strip())
        target_label = ""
        if _is_number_bearing_line(source_line):
            value_start = re.search(r"[+\d]", source_line)
            target_label = source_line[: value_start.start()].strip() if value_start else ""
        else:
            domain = _extract_domain_or_email(source_line)
            if domain:
                idx = source_line.lower().find(domain.split("@")[-1])
                target_label = source_line[:idx].strip() if idx > 0 else ""

        if target_label and match_idx > 0:
            preceding_collapsed = collapsed_lines[match_idx - 1]
            if normalize_text(preceding_collapsed) == normalize_text(target_label):
                raw_label = _locate_raw(preceding_collapsed)
                if raw_label:
                    return f"{raw_label} {raw_value}"

    return raw_value


def diff_exact_spacing(expected: str, found: str) -> str:
    """
    Human-readable note on where `found`'s internal spacing/casing
    diverges from `expected` — used in the exact-match QA detail column
    so a person can see precisely what to fix rather than just "mismatch".
    Covers three independent kinds of divergence, checked in this order:
      1. Spacing: found has a different number of space-separated words
         than expected (catches BOTH an added space bar that splits one
         word into two, AND a missing space bar that merges two words
         into one — not just multi-space runs).
      2. Multi-space runs: even when word count matches, an extra/missing
         space WITHIN a run (single vs double space between the same two
         words) is called out specifically.
      3. Casing: same words, same spacing, different letter case.
    A line can have more than one of these at once; all applicable notes
    are included. (The current caller only invokes this when the strings
    are already known to differ, but the guard below keeps this function
    correct on its own terms rather than relying on that.)
    """
    if expected.strip() == found.strip():
        return "No difference — strings are identical."

    notes = []
    expected_words = expected.strip().split(" ")
    found_words = found.strip().split(" ")

    if len(expected_words) != len(found_words):
        # Word count differs -- catches a missing space merging two words
        # ("BirdAutomotive") as well as a stray space splitting one word
        # into two ("Auto motive"), even when neither involves a {2,}
        # multi-space run anywhere in the line.
        notes.append(
            "Spacing does not match the Excel reference — the number/position of space bars "
            "between words/characters differs from the source line "
            f"({len(found_words)} word(s) found vs {len(expected_words)} expected)."
        )
    else:
        expected_multi = re.findall(r" {2,}", expected)
        found_multi = re.findall(r" {2,}", found)
        if found_multi != expected_multi:
            notes.append(
                "Spacing does not match the Excel reference — the number of consecutive spaces "
                "at one or more points differs from the source line."
            )

    if expected.strip().casefold() == found.strip().casefold() and expected.strip() != found.strip():
        notes.append(
            "Casing does not match the Excel reference — one or more letters that should be "
            "uppercase are lowercase (or vice-versa)."
        )

    if not notes:
        notes.append("Text differs from the Excel reference.")
    return " ".join(notes)


def classify_expected_phone_format(excel_line: str, config) -> Optional[str]:
    """
    Determines which of the three accepted phone formats applies to this
    line, based on the digit shape of the NUMBER ITSELF as given in the
    Excel cell (Excel is the source of truth for what the number is — the
    format is then a rendering rule on top of that). Returns one of
    "mobile_intl" / "tollfree" / "std_landline", or None if this line
    isn't a phone/landline line at all (no format check applies).
    """
    digits = _digit_sequence(excel_line)
    has_tel_prefix = bool(re.search(r"\bTel\.?:?", excel_line, re.I))

    if not digits or len(digits) < 8:
        return None

    if has_tel_prefix and digits.startswith("91") and len(digits) == 12:
        return "mobile_intl"
    if has_tel_prefix and digits.startswith("1800") and len(digits) == 11:
        return "tollfree"
    if not has_tel_prefix and 8 <= len(digits) <= 13:
        return "std_landline"
    # Tel.: prefix present but digits don't match either +91-mobile or
    # 1800-tollfree length -- still a phone line, just not classifiable
    # against these three formats; flagged separately as Warn rather than
    # silently skipped, so an unexpected number shape isn't invisible.
    if has_tel_prefix:
        return "unclassified"
    return None


def check_phone_number_format(excel_line: str, html_found_line: str, config) -> Optional[dict]:
    """
    Verifies the phone/landline number as it actually appears in the HTML
    matches the one-of-three accepted formats:
        Format 1: "Tel.: +91 82228 22201"
        Format 2: "Tel.: 1800 103 2211"
        Format 3: "040-27676946"
    The expected format is determined from the Excel line's own digit
    shape (see classify_expected_phone_format) — the check then verifies
    the HTML rendering matches THAT specific format's pattern, so a
    number in the wrong format (extra/missing spaces, wrong punctuation,
    missing "Tel.:" prefix, hyphens instead of spaces, etc.) fails even
    when the digits themselves are correct. Returns None if this line
    isn't a phone/landline line (no format check applies to it).
    """
    fmt = classify_expected_phone_format(excel_line, config)
    if fmt is None:
        return None

    found = html_found_line.strip()

    if fmt == "unclassified":
        return {
            "item": f"Phone number format: {excel_line}"[:120],
            "status": "Warn",
            "detail": (
                f"'{found}' has a 'Tel.:' prefix but its digit count doesn't match either the "
                f"+91 mobile format (10 digits) or the 1800 toll-free format (7 digits after 1800) — "
                f"could not verify against the three accepted formats. Verify manually."
            ),
        }

    pattern_map = {
        "mobile_intl": (config.phone_format_mobile_intl, "Tel.: +91 XXXXX XXXXX"),
        "tollfree": (config.phone_format_tollfree, "Tel.: 1800 XXX XXXX"),
        "std_landline": (config.phone_format_std_landline, "XXX-XXXXXXX (STD code-hyphen-number, no spaces)"),
    }
    pattern, example = pattern_map[fmt]

    if re.match(pattern, found):
        return {
            "item": f"Phone number format: {excel_line}"[:120],
            "status": "Pass",
            "detail": f"'{found}' matches the required format ({example}).",
        }

    return {
        "item": f"Phone number format: {excel_line}"[:120],
        "status": "Fail",
        "detail": f"'{found}' does not match the required format — expected pattern like '{example}'.",
    }


def check_tel_href_matches_number(excel_line: str, html_raw: str, config) -> Optional[dict]:
    """
    Cross-checks that a `tel:` link's ACTUAL href digits match the
    Excel-sourced number for this line — catches the case where the
    visible text on the page is correct but the underlying link is wired
    to a different number (a real authoring mistake that a pure visible-
    text comparison can't see, since the href is invisible on the
    rendered page). Only runs for lines classified as phone/landline
    lines; returns None otherwise.
    """
    fmt = classify_expected_phone_format(excel_line, config)
    if fmt is None:
        return None

    expected_digits = _digit_sequence(excel_line)
    if not expected_digits:
        return None

    soup = BeautifulSoup(html_raw, "html.parser")
    tel_links = [a for a in soup.find_all("a") if (a.get("href") or "").lower().startswith("tel:")]

    matching_link = None
    for a in tel_links:
        href_digits = _digit_sequence(a.get("href") or "")
        # A tel: href may or may not include the country code; accept a
        # match either on the full digit string or on the local number
        # (last 10 digits), so a correctly-linked number in either style
        # isn't flagged just because of a country-code convention choice.
        if href_digits == expected_digits or (
            len(expected_digits) >= 10 and href_digits.endswith(expected_digits[-10:]) and len(href_digits) >= 10
        ):
            matching_link = a
            break

    if matching_link is not None:
        return {
            "item": f"Tel. link target: {excel_line}"[:120],
            "status": "Pass",
            "detail": f"A tel: link with matching digits was found (href=\"{matching_link.get('href')}\").",
        }

    if tel_links:
        hrefs = ", ".join(f'"{a.get("href")}"' for a in tel_links[:5])
        return {
            "item": f"Tel. link target: {excel_line}"[:120],
            "status": "Fail",
            "detail": f"No tel: link's digits match the Excel number. Tel. link(s) found in HTML: {hrefs}.",
        }

    return {
        "item": f"Tel. link target: {excel_line}"[:120],
        "status": "Fail",
        "detail": "No tel: link found anywhere in the HTML to check against the Excel number.",
    }


def _exact_match_comparison_target(source_line: str, found: str, config) -> str:
    """
    Returns the portion of `source_line` that should be compared
    byte-for-byte against `found`, for the generic exact-match (casing/
    spacing) row. For an ordinary line this is the whole source_line, as
    before. For a number-bearing or URL/email-bearing line, a correctly
    built HTML normally puts the label ("Tel.:", "Website:") and the
    value in SEPARATE DOM text nodes — this happens precisely because the
    value is (correctly) wrapped in its own <a> tag, and is not a spacing
    bug. In that case `found` legitimately contains only the value, not
    the label, so the fair comparison target is the source_line's own
    value portion (its digit sequence rendered as-is, or its domain/
    email), not the full "Tel.: +91 82228 22201" string. The dedicated
    check_phone_number_format() / check_tel_href_matches_number() checks
    already validate the label+format and link-target correctness
    separately, so this function only needs to isolate the value for the
    plain text-identity comparison.
    """
    if _is_number_bearing_line(source_line):
        # If `found` itself still contains the label (a non-hyperlinked
        # or differently-structured number line, where label+value share
        # one text node), compare the full line as normal.
        if _digit_sequence(found) and re.search(r"[a-zA-Z]", found) and ":" in found:
            return source_line
        # Otherwise `found` is value-only (the normal, correct hyperlinked
        # case) -- compare against just the source line's own value
        # portion, i.e. everything from the first digit onward.
        value_match = re.search(r"[+\d].*$", source_line.strip())
        return value_match.group(0) if value_match else source_line

    if _is_url_bearing_line(source_line):
        found_domain = _extract_domain_or_email(found)
        source_domain = _extract_domain_or_email(source_line)
        # If `found` contains ONLY the domain/email (no label text before
        # it), compare domain-to-domain; otherwise compare the full line.
        found_stripped = found.strip()
        if found_domain and found_stripped.lower() == found_domain:
            return source_domain or source_line

    return source_line


def run_dealer_panel_exact_match_qa(panel_lines: List[str], html_raw: str, config) -> pd.DataFrame:
    """
    For every dealer panel line that the fuzzy Content QA above located in
    the HTML, verifies the HTML's actual rendered text is identical to the
    Excel cell's line — casing and internal spacing both included (see
    _exact_match_comparison_target for how the comparison target is
    chosen for number/URL-bearing lines, where the label and value
    normally live in separate DOM nodes). A line the fuzzy check already
    reported "Missing" is skipped here (nothing exact to compare
    against); a phone/landline line found here is also where the correct
    format check (see check_phone_number_format) and the tel: href
    cross-check (see check_tel_href_matches_number) get applied, since
    all three checks need the same located HTML line/number.
    Returns a DataFrame with columns: item, status, detail — appended as
    additional rows alongside the existing content/style checks, per spec
    ("include these points as well in different rows").
    """
    if not config.dealer_panel_exact_match:
        return pd.DataFrame(columns=["item", "status", "detail"])

    rows = []
    for line in panel_lines:
        if normalize_text(line) in {"|", "-", "—"}:
            continue
        found = raw_line_text_from_html(html_raw, line)
        if found is None:
            continue  # already reported Missing by the fuzzy Content QA table

        compare_target = _exact_match_comparison_target(line, found, config)
        exact_ok = found.strip() == compare_target.strip()
        rows.append({
            "item": f"Exact match: {line}"[:120],
            "status": "Pass" if exact_ok else "Fail",
            "detail": "Casing and spacing match the Excel reference exactly." if exact_ok
                      else diff_exact_spacing(compare_target, found),
        })

        phone_status = check_phone_number_format(line, found, config)
        if phone_status is not None:
            rows.append(phone_status)

        href_status = check_tel_href_matches_number(line, html_raw, config)
        if href_status is not None:
            rows.append(href_status)

    if rows:
        return pd.DataFrame(rows)
    return pd.DataFrame(columns=["item", "status", "detail"])


# =========================================================
# Dealer auto-detection from HTML
# =========================================================

def detect_dealer_from_html(html_raw: str, dealer_rows: List[DealerRow]) -> Optional[DealerRow]:
    """
    Finds which dealer (from the Excel rows) this HTML email belongs to,
    by looking for a 'BMW <Dealer Name>' heading in the HTML and matching
    it against each row's Dealer column / first panel line.
    """
    soup = BeautifulSoup(html_raw, "html.parser")
    visible = html_to_visible_text(soup)
    visible_norm = normalize_text(visible)

    best_row = None
    best_len = 0
    for row in dealer_rows:
        dealer_name = row.dealer.strip()
        if not dealer_name:
            continue
        candidates = {dealer_name, f"BMW {dealer_name}"}
        panel_lines = panel_text_to_lines(row.panel_text)
        if panel_lines:
            candidates.add(panel_lines[0])

        for cand in candidates:
            cn = normalize_text(cand)
            if cn and cn in visible_norm:
                if len(cn) > best_len:
                    best_len = len(cn)
                    best_row = row

    return best_row


# =========================================================
# Style / linking QA — scoped to the dealer panel block plus
# the module immediately above it (not disclaimer/social).
# =========================================================

@dataclass
class StyleIssue:
    rule: str
    severity: str
    detail: str


def get_bg_mode(container: Tag) -> str:
    node = container
    while node is not None and isinstance(node, Tag):
        style = (node.get("style") or "").lower()
        bgcolor = (node.get("bgcolor") or "").lower()
        combined = style + " " + bgcolor
        m = re.search(r"background-color:\s*#?([0-9a-f]{3,6})", combined)
        hexval = None
        if m:
            hexval = m.group(1)
        elif bgcolor:
            hexval = bgcolor.lstrip("#")
        if hexval:
            hexval = hexval.strip()
            if hexval in ("000", "000000"):
                return "black"
            if hexval in ("fff", "ffffff"):
                return "white"
        node = node.parent
    return "unknown"


def locate_dealer_panel_container(soup: BeautifulSoup) -> Optional[Tag]:
    """
    Finds the panel content scoped to the dealer name heading through the
    Website/Email row that follows it -- just the <tr> rows that make up
    the dealer panel itself, not the whole enclosing wrapper table (which
    may also contain unrelated sibling rows like a "FOLLOW US" social
    block or a disclaimer further down).
    """
    candidates = soup.find_all(string=re.compile(r"Tel\.?:|Website:", re.I))
    if not candidates:
        return None

    rows: List[Tag] = []
    seen_ids = set()
    for c in candidates:
        node = c.parent
        while node is not None and node.name != "tr":
            node = node.parent
        if node is not None and id(node) not in seen_ids:
            rows.append(node)
            seen_ids.add(id(node))

    if not rows:
        return None

    parent_table = rows[0]
    while parent_table is not None and parent_table.name != "table":
        parent_table = parent_table.parent
    if parent_table is None:
        return rows[0]

    all_trs = parent_table.find_all("tr", recursive=True)
    top_level_trs = [tr for tr in all_trs if tr.find_parent("table") is parent_table]

    row_indices = [top_level_trs.index(r) for r in rows if r in top_level_trs]
    if not row_indices:
        return rows[0]

    start_idx = min(row_indices)
    end_idx = max(row_indices)
    selected_trs = top_level_trs[start_idx:end_idx + 1]

    wrapper = BeautifulSoup("<table><tbody></tbody></table>", "html.parser")
    tbody = wrapper.tbody
    for tr in selected_trs:
        tbody.append(BeautifulSoup(str(tr), "html.parser"))
    return wrapper.table


def locate_scope_container(soup: BeautifulSoup) -> Optional[Tag]:
    """
    Scope for style QA = the dealer panel rows themselves (dealer-name
    heading through the last Tel./Website/Email row). This already
    excludes footer disclaimers and social-icon blocks that sit in
    sibling rows of the same wrapper table.
    """
    return locate_dealer_panel_container(soup)


def extract_px(value: str) -> Optional[float]:
    m = re.search(r"([\d.]+)\s*px", value)
    if m:
        return float(m.group(1))
    return None


def run_style_qa(html_raw: str) -> List[StyleIssue]:
    issues: List[StyleIssue] = []
    soup = BeautifulSoup(html_raw, "html.parser")

    panel = locate_dealer_panel_container(soup)
    if panel is None:
        issues.append(StyleIssue(
            "Dealer panel block", "Warn",
            "Could not locate a dealer panel block (no 'Tel.:' / 'Website:' text found) to run styling QA."
        ))
        return issues

    scope = locate_scope_container(soup) or panel

    # Background mode must be read from a node still attached to the
    # original document (the cloned `panel`/`scope` wrapper has no
    # ancestors), so find the original in-document Tel./Website row first.
    orig_candidates = soup.find_all(string=re.compile(r"Tel\.?:|Website:", re.I))
    bg_source = orig_candidates[0].parent if orig_candidates else panel
    panel_bg_mode = get_bg_mode(bg_source)
    expected_text_color = "#ffffff" if panel_bg_mode == "black" else "#666666"
    expected_link_color = "#ffffff" if panel_bg_mode == "black" else "#1c69d4"

    issues.append(StyleIssue(
        "Background detected", "Pass" if panel_bg_mode != "unknown" else "Warn",
        f"Dealer panel background detected as: {panel_bg_mode}."
    ))

    # ---- Rule: panel/scope text color matches background mode ----
    color_issue = False
    for td in scope.find_all(["td", "span", "font"]):
        style = (td.get("style") or "").lower()
        color_m = re.search(r"(?<!background-)color:\s*#?([0-9a-f]{3,6})", style)
        if not color_m:
            continue
        if td.find("a"):
            continue  # links checked separately below
        color = "#" + color_m.group(1)
        if color.lower() != expected_text_color:
            snippet = td.get_text(" ", strip=True)[:40]
            issues.append(StyleIssue(
                "Panel text color", "Fail",
                f"Text '{snippet}' has color {color}, expected {expected_text_color} on {panel_bg_mode} background."
            ))
            color_issue = True
    if not color_issue:
        issues.append(StyleIssue("Panel text color", "Pass", f"Panel text color correctly set to {expected_text_color}."))

    # ---- Rule: Tel / Website / Email should be hyperlinked ----
    panel_text_all = panel.get_text(" ", strip=True)
    for label, pattern in [
        ("Tel.", re.compile(r"tel\.?:?", re.I)),
        ("Website", re.compile(r"website:?", re.I)),
        ("Email", re.compile(r"email:?", re.I)),
    ]:
        if pattern.search(panel_text_all):
            label_nodes = panel.find_all(string=pattern)
            linked = False
            for ln in label_nodes:
                row = ln.parent
                hop = 0
                while row is not None and hop < 6:
                    a = row.find("a") if isinstance(row, Tag) else None
                    if a and a.get("href"):
                        href = a.get("href", "")
                        if label == "Tel." and href.lower().startswith("tel:"):
                            linked = True
                        elif label == "Website" and (href.lower().startswith("http") or href.lower().startswith("www")):
                            linked = True
                        elif label == "Email" and href.lower().startswith("mailto:"):
                            linked = True
                    row = row.parent
                    hop += 1
            if linked:
                issues.append(StyleIssue(f"{label} hyperlink", "Pass", f"{label} appears correctly hyperlinked."))
            else:
                issues.append(StyleIssue(f"{label} hyperlink", "Fail", f"{label} was found in the panel but no matching <a href> link (tel:/http/mailto:) was detected."))

    # ---- Rule: Tel/Website/Email link color ----
    for a in panel.find_all("a"):
        href = (a.get("href") or "").lower()
        style = (a.get("style") or "").lower()
        color_m = re.search(r"color:\s*#?([0-9a-f]{3,6})", style)
        color = ("#" + color_m.group(1)) if color_m else None
        if href.startswith(("tel:", "mailto:")) or "http" in href:
            if color and color.lower() != expected_link_color:
                issues.append(StyleIssue(
                    f"Link color ({panel_bg_mode} bg)", "Fail",
                    f"Link '{a.get_text(strip=True)}' has color {color}, expected {expected_link_color}."
                ))

    # ---- Rule: dealer panel font size 14px <= size < 17px ----
    font_size_issue = False
    for td in scope.find_all(["td", "span", "font"]):
        style = (td.get("style") or "")
        if "font-size" not in style.lower():
            continue
        size = extract_px(style)
        if size is None:
            continue
        problems = []
        if size < 14:
            problems.append(f"{size}px is below the 14px minimum")
        if size >= 17:
            problems.append(f"{size}px is at/above the 17px ceiling")
        if problems:
            snippet = td.get_text(" ", strip=True)[:40]
            issues.append(StyleIssue(
                "Dealer panel font size", "Fail",
                f"Text '{snippet}' — " + "; ".join(problems)
            ))
            font_size_issue = True
    if not font_size_issue:
        issues.append(StyleIssue("Dealer panel font size", "Pass", "All detected dealer-panel font sizes are within 14px–16.99px."))

    # ---- Rule: bold text uses bmwtypenextbold, light text uses bmwtypenextlight ----
    bold_font_issue = False
    bold_checked_snippets = []
    for tag in scope.find_all(["strong", "b"]):
        style = (tag.get("style") or "").lower()
        snippet = tag.get_text(strip=True)[:40]
        bold_checked_snippets.append(snippet)
        if "bmwtypenextbold" not in style:
            bold_font_issue = True
            issues.append(StyleIssue(
                f"Bold font-family: '{snippet}'", "Fail",
                f"Bold text '{snippet}' does not declare font-family: bmwtypenextbold."
            ))
    if not bold_font_issue:
        if bold_checked_snippets:
            checked_label = ", ".join(f"'{s}'" for s in bold_checked_snippets[:6])
            if len(bold_checked_snippets) > 6:
                checked_label += f", and {len(bold_checked_snippets) - 6} more"
            issues.append(StyleIssue(
                f"Bold font-family: {checked_label}", "Pass",
                f"All bold (<strong>/<b>) text uses bmwtypenextbold. Checked: {checked_label}."
            ))
        else:
            issues.append(StyleIssue("Bold font-family", "Pass", "No bold (<strong>/<b>) text found in scope to check."))

    light_font_issue = False
    light_checked_snippets = []
    for td in scope.find_all("td"):
        style = (td.get("style") or "").lower()
        if "font-weight: 300" in style or "font-weight:300" in style:
            snippet = td.get_text(strip=True)[:40]
            light_checked_snippets.append(snippet)
            if "bmwtypenextlight" not in style:
                light_font_issue = True
                issues.append(StyleIssue(
                    f"Light font-family: '{snippet}'", "Fail",
                    f"Light-weight text '{snippet}' does not declare font-family: bmwtypenextlight."
                ))
    if not light_font_issue:
        if light_checked_snippets:
            checked_label = ", ".join(f"'{s}'" for s in light_checked_snippets[:6])
            if len(light_checked_snippets) > 6:
                checked_label += f", and {len(light_checked_snippets) - 6} more"
            issues.append(StyleIssue(
                f"Light font-family: {checked_label}", "Pass",
                f"All light-weight (font-weight:300) text uses bmwtypenextlight. Checked: {checked_label}."
            ))
        else:
            issues.append(StyleIssue("Light font-family", "Pass", "No light-weight (font-weight:300) text found in scope to check."))

    # ---- Rule: "Follow Us" footer text should use bmwtypenextregular ----
    # Only some email templates render this footer line with the expected
    # font declared explicitly — when it's missing, this is a WARN, never
    # a Fail (per spec), since not every template is required to set it.
    # Searches the WHOLE document (not `scope`), since "Follow Us" sits in
    # the footer/social-icon block, outside the dealer panel itself.
    follow_us_nodes = soup.find_all(string=re.compile(r"follow\s+us", re.I))
    if follow_us_nodes:
        follow_us_font_issue = False
        for node in follow_us_nodes:
            style_node = node.parent
            hop = 0
            found_style = ""
            while style_node is not None and isinstance(style_node, Tag) and hop < 6:
                s = (style_node.get("style") or "")
                if s:
                    found_style = s.lower()
                    break
                style_node = style_node.parent
                hop += 1
            if EXT_CFG.follow_us_expected_font not in found_style:
                follow_us_font_issue = True
        if follow_us_font_issue:
            issues.append(StyleIssue(
                "Follow Us font", "Warn",
                f"'Follow Us' text found but does not declare font-family: {EXT_CFG.follow_us_expected_font}. "
                f"This is only a warning — not every template is required to set this."
            ))
        else:
            issues.append(StyleIssue("Follow Us font", "Pass", f"'Follow Us' text correctly uses {EXT_CFG.follow_us_expected_font}."))
    # If "Follow Us" text isn't present at all in this email, no row is
    # added — the check simply doesn't apply to this template.

    # ---- Rule: buttons should have border-radius ----
    # A real CTA button (e.g. "Book a test drive") is an <a> that wraps a
    # nested <table> forming the button shape. Plain links sitting inside a
    # colored <td> — phone numbers, website URLs, social icons — do NOT
    # wrap a table and must be excluded, otherwise every colored link in
    # the email gets mistakenly flagged as a "button".
    button_found = False
    radius_re = re.compile(r"border-radius\s*:\s*(\d+(?:\.\d+)?)\s*px", re.IGNORECASE)
    bg_color_re = re.compile(r"background-color:\s*#?([0-9a-f]{3,6})", re.IGNORECASE)
    expected_cta_bg = EXT_CFG.cta_button_expected_bg.lstrip("#").lower()
    for a in soup.find_all("a"):
        href = a.get("href") or ""

        # Must wrap a nested <table> — this is what makes it a CTA button
        # rather than a plain text/icon link.
        inner_table = a.find("table")
        if inner_table is None:
            continue

        ancestor_tds = a.find_parents("td")
        if not ancestor_tds:
            continue

        cta_td = None
        for td in ancestor_tds:
            bgcolor = (td.get("bgcolor") or "").strip()
            style = (td.get("style") or "").lower()
            if bgcolor or "background-color" in style:
                cta_td = td
                break

        if cta_td is None:
            continue

        button_found = True
        style = (cta_td.get("style") or "").lower()
        a_style = (a.get("style") or "").lower()
        inner_td_style = " ".join((td.get("style") or "").lower() for td in inner_table.find_all("td"))

        combined_style = style + " " + a_style + " " + inner_td_style
        match = radius_re.search(combined_style)
        has_radius = match is not None
        radius_ok = has_radius and float(match.group(1)) >= 3

        label = a.get_text(strip=True)[:30] or href
        if radius_ok:
            issues.append(StyleIssue("Button border-radius", "Pass", f"Button '{label}' has rounded corners ({match.group(1)}px)."))
        elif has_radius:
            issues.append(StyleIssue("Button border-radius", "Fail", f"Button '{label}' has border-radius of {match.group(1)}px — should be at least 3px."))
        else:
            issues.append(StyleIssue("Button border-radius", "Warn", f"Button '{label}' has no border-radius set — should have rounded corners (min 3px)."))

        # ---- Rule: CTA button background color must match config.cta_button_expected_bg ----
        cta_bgcolor_attr = (cta_td.get("bgcolor") or "").strip().lstrip("#").lower()
        style_bg_match = bg_color_re.search(style)
        actual_bg = (style_bg_match.group(1).lower() if style_bg_match else None) or cta_bgcolor_attr or None
        if actual_bg is None:
            issues.append(StyleIssue(
                "CTA button background color", "Fail",
                f"Button '{label}' has no background color set — expected {EXT_CFG.cta_button_expected_bg.upper()}."
            ))
        elif actual_bg == expected_cta_bg:
            issues.append(StyleIssue(
                "CTA button background color", "Pass",
                f"Button '{label}' background color correctly set to {EXT_CFG.cta_button_expected_bg.upper()}."
            ))
        else:
            issues.append(StyleIssue(
                "CTA button background color", "Fail",
                f"Button '{label}' has background color #{actual_bg.upper()} — expected {EXT_CFG.cta_button_expected_bg.upper()}."
            ))
    if not button_found:
        issues.append(StyleIssue("Button border-radius", "Warn", "No CTA-style button (linked, colored <td> wrapping a nested button table) detected in scope to check."))
        issues.append(StyleIssue("CTA button background color", "Warn", "No CTA-style button detected in scope to check background color."))

    return issues


# =========================================================
# Image size QA
# =========================================================

def run_double_space_qa(html_raw: str, config) -> List[StyleIssue]:
    """
    Flags a run of 2+ consecutive RENDERED space characters anywhere in
    the email — i.e. what a reader would actually see as a double space
    on the page, not HTML source-code formatting. Reads
    html_to_rendered_text() (see that function's docstring for the full
    reasoning), which simulates real browser whitespace-collapsing: any
    run of plain whitespace (spaces/tabs/newlines used for HTML source
    indentation) collapses to one rendered space exactly like a browser
    does, so a developer's tab-indented markup never trips this check.
    Only &nbsp; forces a genuinely non-collapsing rendered space, so a
    real double-space bug is &nbsp; sitting next to another &nbsp; or a
    plain space — that combination IS still detected. Scans the WHOLE
    email, not just the dealer panel scope, since this can happen in any
    section.
    """
    issues: List[StyleIssue] = []
    soup = BeautifulSoup(html_raw, "html.parser")
    rendered = html_to_rendered_text(soup)

    min_run = config.double_space_min_run
    # Match a run of 2+ characters that are EACH a rendered space -- a
    # plain space or an nbsp, in any combination -- since both display as
    # visible whitespace and a reader can't tell them apart on the page.
    pattern = re.compile(r"[ \xa0]{" + str(min_run) + r",}")

    found_runs = []
    for line in rendered.splitlines():
        for m in pattern.finditer(line):
            snippet_start = max(0, m.start() - 20)
            snippet_end = min(len(line), m.end() + 20)
            context = line[snippet_start:snippet_end].strip()
            found_runs.append((len(m.group()), context))

    if found_runs:
        for run_len, context in found_runs[:15]:
            issues.append(StyleIssue(
                "Double space", "Fail",
                f"Found a {run_len}-space run — double space bars should not be present. Context: '...{context}...'",
            ))
        if len(found_runs) > 15:
            issues.append(StyleIssue(
                "Double space", "Fail",
                f"...and {len(found_runs) - 15} more double-space occurrence(s) not shown.",
            ))
    else:
        issues.append(StyleIssue("Double space", "Pass", "No double space bars found anywhere in the email's rendered text."))

    return issues


def _looks_like_domain_or_email_token(word: str) -> bool:
    """
    True if `word` (a single whitespace-delimited token) is, AS A WHOLE,
    shaped like a domain, URL, or email address — used to exclude these
    from the punctuation-spacing check below, since a domain/URL/email
    legitimately has dots with no surrounding space (e.g.
    "www.bmw-birdautomotive.in", "info@bmw-krishnaautomotive.in").

    This is NOT the same test as _extract_domain_or_email() used
    elsewhere in this file (that one finds a domain-shaped SPAN inside a
    larger string, for phone/website line matching) — this one tests
    whether the ENTIRE token is domain-shaped, which is the safer test
    here: a run-on sentence like "sentence.Next" is superficially
    word.Word-shaped too, so the two things this function checks for are
    what make the difference:
      - A capital letter immediately after a dot is treated as a
        sentence boundary, not a domain — real domains don't do this
        (a genuine run-on like "sentence.Next" is excluded from being
        treated as a domain by this rule alone).
      - The final dot-separated segment must be letters-only and at
        least 2 characters (a TLD shape: "in", "com" — NOT a number,
        which is what correctly distinguishes a domain from something
        like "Rs.500").
    """
    w = re.sub(r"^https?://", "", word)
    w = w.split("/")[0]
    if not w:
        return False
    if re.search(r"\.[A-Z]", w):
        return False
    parts = w.rstrip(".").split(".")
    if len(parts) < 2:
        return False
    last = parts[-1]
    if not (last.isalpha() and len(last) >= 2):
        return False
    host = w.split("@")[-1]
    host_parts = host.rstrip(".").split(".")
    return all(re.match(r"^[a-zA-Z0-9-]+$", seg) for seg in host_parts)


def _looks_like_numeric_identifier_token(word: str) -> bool:
    """
    True if `word`, once trailing punctuation is stripped, is made up
    ENTIRELY of digits, dots, slashes, and hyphens — a plot/survey/unit
    number like "3.25/1" or "27/-16". A genuine "missing space after
    punctuation" authoring bug always involves an actual WORD (letters)
    running into the punctuation; a bare numeric code with an internal
    dot is a different, legitimate thing (validated against the real
    dealer sheet: "D.No. 3.25/1, Sy No.27/-16Pa4" — the survey number
    "3.25/1" must NOT be flagged, while "No.27" in the same address
    correctly IS flagged, since "No" is a real word/abbreviation running
    into "27" with no space).
    """
    core = word.rstrip(".,;:")
    return bool(core) and bool(re.match(r"^[0-9./-]+$", core))


def run_punctuation_spacing_qa(html_raw: str, config) -> List[StyleIssue]:
    """
    Flags a comma or period immediately followed by a letter or digit —
    i.e. the next word/sentence running straight into the punctuation
    with no space, the normal English-usage rule being that a space
    always follows a comma or full stop before the next word starts.
    Reads html_to_rendered_text() (see run_double_space_qa above for why
    rendered text, not raw HTML source, is required — the same reasoning
    applies here: HTML source formatting must never be mistaken for a
    real spacing issue). Deliberately excludes:
      - Domains, URLs, and email addresses (see
        _looks_like_domain_or_email_token) — these legitimately have
        dots with no surrounding space.
      - Purely numeric identifiers like plot/survey numbers (see
        _looks_like_numeric_identifier_token).
      - Initials-style abbreviations ("A.C.", "M.G.") — a capital
        letter immediately before AND after the period is treated as
        initials, not a run-on sentence.
    Validated against the real 23-dealer panel dataset with zero false
    positives, while still correctly catching genuine spacing gaps like
    "Plot No.50" (should be "Plot No. 50") and "Gate no.3" (should be
    "Gate no. 3").
    """
    issues: List[StyleIssue] = []
    soup = BeautifulSoup(html_raw, "html.parser")
    rendered = html_to_rendered_text(soup)

    punct_pattern = re.compile(r"[.,](?=[A-Za-z0-9])")
    found: List[str] = []

    for line in rendered.splitlines():
        for word_match in re.finditer(r"\S+", line):
            word = word_match.group()
            if _looks_like_domain_or_email_token(word) or _looks_like_numeric_identifier_token(word):
                continue
            for m in punct_pattern.finditer(word):
                before_char = word[m.start() - 1] if m.start() > 0 else ""
                after_char = word[m.end()] if m.end() < len(word) else ""
                if before_char.isalpha() and before_char.isupper() and after_char.isalpha() and after_char.isupper():
                    continue  # initials, e.g. "A.C."
                found.append(word)

    # De-duplicate while preserving first-seen order, so the same typo
    # repeated verbatim elsewhere in the email doesn't spam the table.
    seen = set()
    unique_found = []
    for w in found:
        if w not in seen:
            seen.add(w)
            unique_found.append(w)

    if unique_found:
        for word in unique_found[:15]:
            issues.append(StyleIssue(
                f"Punctuation spacing: '{word}'", "Fail",
                f"'{word}' — a comma or full stop should be followed by a space before the next word.",
            ))
        if len(unique_found) > 15:
            issues.append(StyleIssue(
                "Punctuation spacing", "Fail",
                f"...and {len(unique_found) - 15} more occurrence(s) not shown.",
            ))
    else:
        issues.append(StyleIssue("Punctuation spacing", "Pass", "Every comma and full stop found is correctly followed by a space."))

    return issues


_BOLD_WEIGHT_RE = re.compile(r"font-weight\s*:\s*(bold|[7-9]00)\b", re.IGNORECASE)


def is_text_bold(node, max_ancestor_hops: int = 6) -> bool:
    """
    True if a BeautifulSoup text/tag node renders bold — via a <strong>
    or <b> ancestor tag, OR an inline font-weight: bold (or a numeric
    weight of 700 or higher) on the node's OWN element or any ancestor,
    up to `max_ancestor_hops` levels up. Both mechanisms are real and
    both appear in actual dealer-panel HTML: "Tel.:"/"Website:" labels
    are wrapped in a <b style="font-weight: bold;">...</b> tag, while a
    dealer name line can be bold purely because its containing <td>'s
    own inline style sets font-weight: bold, with NO <strong>/<b> tag
    anywhere around the text at all — checking only for the tag, or only
    for the node's own style, would miss one of these two real cases.
    The hop limit keeps this from walking all the way up to <body> and
    picking up unrelated styling from far outside the actual line being
    checked.
    """
    current = node if hasattr(node, "get") else getattr(node, "parent", None)
    hops = 0
    while current is not None and hasattr(current, "name") and hops < max_ancestor_hops:
        if getattr(current, "name", None) in ("strong", "b"):
            return True
        style = (current.get("style") or "") if hasattr(current, "get") else ""
        if _BOLD_WEIGHT_RE.search(style):
            return True
        current = current.parent
        hops += 1
    return False


def check_bold_required_lines(html_raw: str, dealer_row: "DealerRow", config) -> List[StyleIssue]:
    """
    Verifies that the dealer name, every branch/city name (from
    dealer_row.bold_required_lines — see DealerRow's docstring for how
    these are identified), and any "Tel.:"/"Website:" label all render
    bold. Uses find_best_match on the collapsed visible-text lines to
    locate each required line's own text node (same location strategy
    used throughout this file), then is_text_bold() to check it.
    """
    issues: List[StyleIssue] = []

    soup = BeautifulSoup(html_raw, "html.parser")
    work = BeautifulSoup(str(soup), "html.parser")
    for tag in work(["script", "style", "noscript"]):
        tag.decompose()
    for c in work.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()
    for br in work.find_all("br"):
        br.replace_with("\n")

    checked_any = False

    if dealer_row.bold_required_lines:
        collapsed_lines_with_nodes: List[Tuple[str, object]] = []
        for text_node in work.find_all(string=True):
            raw_piece = str(text_node)
            for piece in raw_piece.split("\n"):
                cleaned = re.sub(r"[ \t]+", " ", piece.replace("\xa0", " ")).strip()
                if cleaned:
                    collapsed_lines_with_nodes.append((cleaned, text_node))

        def _find_node_for_line(target_line: str):
            collapsed_only = [c for c, _ in collapsed_lines_with_nodes]
            match = find_best_match(collapsed_only, target_line)
            if match is None:
                return None
            idx = match[0]
            return collapsed_lines_with_nodes[idx][1]

        for line in dealer_row.bold_required_lines:
            node = _find_node_for_line(line)
            if node is None:
                continue  # not found at all — already reported Missing by Content QA
            checked_any = True
            if is_text_bold(node):
                issues.append(StyleIssue(f"Bold text: '{line}'", "Pass", f"'{line}' correctly renders bold."))
            else:
                issues.append(StyleIssue(f"Bold text: '{line}'", "Fail", f"'{line}' should be bold (dealer name / city / branch name) but is not."))

    # Tel./Website labels: not a fixed line from bold_required_lines
    # (the number/domain varies per dealer), so found by label text
    # instead — any line beginning with "Tel." or "Website" must be bold.
    for label in ("Tel.", "Website"):
        label_nodes = work.find_all(string=re.compile(rf"^\s*{re.escape(label)}\s*:?", re.IGNORECASE))
        for text_node in label_nodes:
            stripped = str(text_node).strip()
            if not stripped:
                continue
            checked_any = True
            display = stripped[:30]
            if is_text_bold(text_node):
                issues.append(StyleIssue(f"Bold text: '{display}'", "Pass", f"'{display}' correctly renders bold."))
            else:
                issues.append(StyleIssue(f"Bold text: '{display}'", "Fail", f"'{display}' — the '{label}' label should be bold but is not."))

    if not checked_any:
        issues.append(StyleIssue("Bold text", "Warn", "No dealer name, city/branch name, or Tel./Website label could be located to check for bold styling."))

    return issues


def run_image_size_qa(html_raw: str, images_source) -> List[StyleIssue]:
    """
    images_source can be:
      - None (no check possible)
      - a zip file-like object (uploaded separately alongside a pasted/uploaded HTML)
      - a dict {filename_lower: size_bytes} built from an uploaded model folder/zip
    """
    issues: List[StyleIssue] = []
    soup = BeautifulSoup(html_raw, "html.parser")
    img_srcs = [img.get("src", "") for img in soup.find_all("img") if img.get("src")]

    if not img_srcs:
        issues.append(StyleIssue("Image size", "Warn", "No <img> tags found in the HTML."))
        return issues

    if images_source is None:
        issues.append(StyleIssue(
            "Image size", "Warn",
            f"Found {len(img_srcs)} image reference(s) in the HTML, but no images were provided — "
            "upload an images .zip (or the full model folder) to check the 300KB limit."
        ))
        return issues

    name_to_size: Dict[str, int] = {}

    if isinstance(images_source, dict):
        name_to_size = images_source
    else:
        try:
            zf = zipfile.ZipFile(images_source)
        except Exception as e:
            issues.append(StyleIssue("Image size", "Warn", f"Could not read the uploaded images zip: {e}"))
            return issues
        for zi in zf.infolist():
            base = zi.filename.split("/")[-1].lower()
            if base:
                name_to_size[base] = zi.file_size

    for src in img_srcs:
        base = src.split("/")[-1].lower()
        size_bytes = name_to_size.get(base)
        if size_bytes is None:
            issues.append(StyleIssue("Image size", "Warn", f"Image '{src}' referenced in HTML but not found in the uploaded images."))
            continue
        size_kb = size_bytes / 1024
        if size_kb > 300:
            issues.append(StyleIssue("Image size", "Fail", f"Image '{src}' is {size_kb:.0f}KB — exceeds the 300KB limit."))
        else:
            issues.append(StyleIssue("Image size", "Pass", f"Image '{src}' is {size_kb:.0f}KB — within the 300KB limit."))

    return issues


# =========================================================
# Content comparison
# =========================================================

def compare_source_to_html(source_lines: List[str], html_raw: str) -> pd.DataFrame:
    soup = BeautifulSoup(html_raw, "html.parser")
    html_visible = html_to_visible_text(soup)
    html_lines = split_lines_keep_order(html_visible)

    source_items = [line for line in source_lines if normalize_text(line) not in {"|", "-", "—"}]

    results: List[CheckResult] = []
    for item in source_items:
        match = find_best_match(html_lines, item)
        status = "Present" if match else "Missing"
        results.append(CheckResult(item=item, status=status))

    if results:
        return pd.DataFrame([r.__dict__ for r in results])
    return pd.DataFrame(columns=["item", "status"])


# =========================================================
# Model-folder (zip) helpers
# =========================================================

def extract_model_zip(uploaded_zip) -> Tuple[Optional[str], Dict[str, int]]:
    """
    Given a zip of a model's email folder (containing an index.html /
    *.html file and an images/ subfolder), returns (html_text, image_sizes).
    """
    zf = zipfile.ZipFile(uploaded_zip)
    html_text = None
    image_sizes: Dict[str, int] = {}

    html_candidates = [zi for zi in zf.infolist() if zi.filename.lower().endswith((".html", ".htm")) and not zi.is_dir()]
    html_candidates.sort(key=lambda zi: (0 if zi.filename.lower().endswith("index.html") else 1, len(zi.filename)))

    if html_candidates:
        with zf.open(html_candidates[0]) as f:
            html_text = f.read().decode("utf-8", errors="ignore")

    for zi in zf.infolist():
        if zi.is_dir():
            continue
        if zi.filename.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")):
            base = zi.filename.split("/")[-1].lower()
            image_sizes[base] = zi.file_size

    return html_text, image_sizes


# =========================================================
# UI
# =========================================================
# Single flowing page (no tabs) — every input section stacks top to
# bottom in one straightforward order: hero, Excel upload, email input
# type, HTML/model uploads, Advanced QA toggle, Run QA button, and
# THEN (below the button) Dealer Name Validation + the Master-mode
# blocks side by side in two columns so that part of the page doesn't
# add extra vertical scroll. Every widget below keeps its EXACT key,
# EXACT type, and EXACT position relative to its sibling widgets —
# this is purely a reordering/flattening of where things render;
# nothing about what any widget returns or how downstream code reads
# it has changed. Each variable is still assigned exactly once, before
# anything that reads it, in the same relative order data becomes
# available (Excel must be uploaded before dealer_rows can exist,
# input_mode must be chosen before email_jobs can be built, etc.).
# ---------------------------------------------------------------

ext_theme.render_hero(
    title="Dealer Panel QA Tool",
    subtitle="Compares the 'Mailers - NSC ' sheet (Dealer / Region / Dealer Panels) against dealer-panel HTML email code, and QAs styling rules.",
    badge="BMW · MINI",
)

# ---- 1. Excel upload + sheet selection ----
with ext_theme.section("content", "Excel & Mode"):
    st.subheader("Inputs")
    excel_upload = st.file_uploader("Upload dealer panel Excel (.xlsx / .xls)", type=["xlsx", "xls"])
    st.caption("Reads the 'Mailers - NSC ' sheet — columns: Dealer, Region, Dealer Panels (plus any additional branch/location columns after it).")

    ext_selected_sheet = None
    ext_workbook = None
    if excel_upload is not None:
        st.divider()
        st.subheader("Excel Sheet Selection (optional)")
        try:
            ext_workbook = ext_excel.open_workbook(excel_upload)
            ext_selected_sheet = st.selectbox(
                "Select Excel Sheet",
                options=["(auto-detect - default behaviour)"] + ext_workbook.sheet_names,
                index=0,
                help="Leave on auto-detect to keep existing behaviour. Pick a sheet to load ONLY that sheet.",
            )
            if ext_selected_sheet == "(auto-detect - default behaviour)":
                ext_selected_sheet = None
        except Exception as e:
            st.warning(f"Could not list sheets for manual selection: {e}")

dealer_rows: List[DealerRow] = []
sheet_used = ""
if excel_upload is not None:
    if ext_selected_sheet:
        try:
            df = ext_excel.load_selected_sheet_with_header(
                ext_workbook, ext_selected_sheet, required_columns_lower=["dealer", "region"]
            )
            dealer_rows = build_dealer_rows_from_df(df, sheet_name=ext_selected_sheet)
            sheet_used = ext_selected_sheet
            st.success(f"Loaded {len(dealer_rows)} dealer row(s) from manually selected sheet '{sheet_used}'.")
        except Exception as e:
            st.error(str(e))
    else:
        try:
            dealer_rows, sheet_used = read_dealer_panels_from_excel(excel_upload)
            st.success(f"Loaded {len(dealer_rows)} dealer row(s) from sheet '{sheet_used}'.")
        except Exception as e:
            st.error(str(e))

# ---- 2. Email input type + HTML / model-folder upload — its own
#         section card, separate from the Excel card above, matching
#         the screenshot reference where these render as visually
#         distinct blocks. ----
with ext_theme.section("email", "Email Input"):
    input_mode = st.radio(
        "Email input type",
        ["HTML file(s)", "Model folder(s) (.zip)"],
        index=0,
    )

    # Each entry: {"name": label, "html": str, "images": None|zipfile-like|dict}
    email_jobs: List[Dict] = []

    if input_mode == "HTML file(s)":
        upload_col1, upload_col2 = st.columns(2)
        with upload_col1:
            html_files = st.file_uploader("Upload HTML / HTM file(s)", type=["html", "htm", "txt"], accept_multiple_files=True)
        with upload_col2:
            images_zip = st.file_uploader("Optional: images .zip (for the 300KB image-size check)", type=["zip"])
        if html_files:
            for hf in html_files:
                html_text = hf.getvalue().decode("utf-8", errors="ignore")
                email_jobs.append({"name": hf.name, "html": html_text, "images": images_zip})
    else:
        model_zips = st.file_uploader("Upload model folder(s) as .zip", type=["zip"], accept_multiple_files=True)
        if model_zips:
            for mz in model_zips:
                try:
                    html_text, image_sizes = extract_model_zip(mz)
                except Exception as e:
                    st.error(f"Could not read '{mz.name}': {e}")
                    continue
                if not html_text:
                    st.error(f"No HTML file found inside '{mz.name}'.")
                    continue
                email_jobs.append({"name": mz.name, "html": html_text, "images": image_sizes})

# ---- 3. Advanced QA toggle ----
ext_run_advanced_qa = st.checkbox(
    "Enable Advanced QA tabs for this run", value=False, key="ext_run_advanced_qa",
    help="Turn on to compute Banner / Visual / OCR / Advanced Body QA tabs below the existing report. Existing QA always runs regardless of this toggle.",
)

def render_qa_table(df: "pd.DataFrame", status_col: str, table_key: str, pass_label: str = "Passed") -> None:
    """
    Thin delegate to the single shared table-rendering implementation in
    modules/results_ui.py (see that module's docstring for why the
    implementation itself lives there and not here) — Fail/Warn always
    visible in a full-width, non-truncating table; Pass rows collapsed
    into a closed expander; an Expand button opens the complete table in
    a popup with its own close button.
    """
    ext_results_ui.render_qa_table(df, status_col=status_col, table_key=table_key, pass_label=pass_label)


# ---- 4. Run QA button ----
run_clicked = st.button("Run QA", type="primary", use_container_width=True)

# ---- 5. Below the button: Dealer Name Validation + Master modes,
#         the latter laid out in two columns so this part of the page
#         doesn't add much extra vertical scroll. Dealer Selection
#         (the dealer dropdown) sits alongside Dealer Name Validation
#         since both are dealer-specific and previously lived together
#         in the same tab. ----
with ext_theme.section("exact", "Dealer Name Validation"):
    st.subheader("Dealer Selection & Validation")

    ext_selected_dealer_row = None
    if dealer_rows:
        ext_dealer_options = ["(none - use automatic HTML detection)"] + ext_dealer.build_dealer_options(dealer_rows)
        ext_dealer_choice = st.selectbox("Dealer", options=ext_dealer_options, key="ext_dealer_dropdown_live")
        if ext_dealer_choice != "(none - use automatic HTML detection)":
            ext_selected_dealer_row = ext_dealer.resolve_selected_dealer(dealer_rows, ext_dealer_choice)
            if ext_selected_dealer_row:
                st.success(f"Master dealer set to: {ext_selected_dealer_row.dealer} ({ext_selected_dealer_row.region})")
    else:
        st.info("Upload a dealer panel Excel file above first — the dealer dropdown will appear here once it's loaded.")

    st.divider()
    st.caption("Opt-in checks — off by default. The tool behaves exactly as before if left unticked.")
    ext_check_dealer_in_banner = st.checkbox("Dealer exists in Banner", value=False, key="ext_dealer_in_banner")
    ext_check_dealer_in_body = st.checkbox("Dealer exists in Body", value=False, key="ext_dealer_in_body")

ext_master_col_a, ext_master_col_b = st.columns(2)

with ext_master_col_a:
    with ext_theme.section("advanced", "Manual Text Mode"):
        st.subheader("Manual Text Mode")
        st.caption("None of these are required. The tool behaves exactly as before if left empty.")
        ext_manual_headline = st.text_input("Headline", value="", key="ext_manual_headline")
        ext_manual_subheadline = st.text_input("Subheadline", value="", key="ext_manual_subheadline")
        ext_manual_dealer_name = st.text_input("Dealer Name", value="", key="ext_manual_dealer_name")
        ext_manual_body_text = st.text_area("Body Text", value="", key="ext_manual_body_text", height=100)
        ext_manual_master = ext_manual.ManualMasterText(
            headline=ext_manual_headline,
            subheadline=ext_manual_subheadline,
            dealer_name=ext_manual_dealer_name,
            body_text=ext_manual_body_text,
        )
        if ext_manual_master.is_active():
            _ext_manual_fields_used = [
                label for label, is_manual in (
                    ("Headline", ext_manual_master.headline_is_manual()),
                    ("Subheadline", ext_manual_master.subheadline_is_manual()),
                    ("Dealer Name", ext_manual_master.dealer_name_is_manual()),
                    ("Body Text", ext_manual_master.body_text_is_manual()),
                ) if is_manual
            ]
            st.info(
                f"Manual Text Mode is ACTIVE for: {', '.join(_ext_manual_fields_used)}. "
                f"Those field(s) always use the typed value. Any field left blank here still "
                f"falls through to Master JPG / Master PDF / Master HTML ZIP / Dealer Dropdown, "
                f"whichever is active — master-asset uploads below are NOT disabled."
            )

    with ext_theme.section("master-b", "Manual Body Comparison"):
        st.subheader("Manual Body Comparison")
        st.caption("As Is / To Be — compared against the live HTML body.")
        ext_body_as_is = st.text_area("As Is", value="", key="ext_body_as_is", height=80)
        ext_body_to_be = st.text_area("To Be", value="", key="ext_body_to_be", height=80)

with ext_master_col_b:
    with ext_theme.section("advanced", "Master Image (JPG)"):
        st.subheader("Master Image (JPG)")
        ext_master_jpg_upload = st.file_uploader(
            "Upload Master JPG", type=["jpg", "jpeg", "png"], key="ext_master_jpg",
        )

    with ext_theme.section("master-b", "Master PDF"):
        st.subheader("Master PDF")
        ext_master_pdf_upload = st.file_uploader(
            "Upload Master PDF", type=["pdf"], key="ext_master_pdf",
        )
        ext_master_pdf_page = st.number_input(
            "PDF Page Number (optional)", min_value=0, value=0, step=1, key="ext_master_pdf_page",
            help="Leave at 0 to auto-detect the page containing the master creative.",
        )

    with ext_theme.section("master-c", "Master HTML (ZIP)"):
        st.subheader("Master HTML (ZIP)")
        ext_master_html_zip_upload = st.file_uploader(
            "Upload Master HTML ZIP", type=["zip"], key="ext_master_html_zip",
        )

if run_clicked:
    st.session_state["ext_has_run"] = True
run = st.session_state.get("ext_has_run", False)

if run:
    if not dealer_rows:
        st.error("Please upload the dealer panel Excel file first.")
        st.stop()
    if not email_jobs:
        st.error("Please upload at least one HTML file or model folder.")
        st.stop()

    ext_theme_results_group_opened = True
    ext_theme_results_group = ext_theme.group("Results")
    ext_theme_results_group.__enter__()

    ext_report_jobs: List[ext_excel_report.JobReportData] = []

    for job_idx, job in enumerate(email_jobs):
        st.divider()

        with ext_theme.section("neutral", job["name"]):
            st.header(job["name"])

            auto_detected_dealer_row = detect_dealer_from_html(job["html"], dealer_rows)

            # Dealer Selection dropdown now applies to the WHOLE tool, not just
            # Advanced QA. When a dealer is explicitly selected, that selection
            # is authoritative for this run: it becomes the dealer whose Excel
            # row (name/region/panel text) everything below is compared
            # against — Content QA, Styling QA, exact-match, phone format, all
            # of it. If the email's HTML actually belongs to a different
            # dealer (or no dealer could be auto-detected from the HTML at
            # all), comparing against the SELECTED dealer's Excel data will
            # correctly and naturally fail every Excel-comparable point, since
            # that dealer's real name/address/phone number won't be found in
            # an email built for someone else. When nothing is selected from
            # the dropdown, behaviour is fully unchanged: the auto-detected
            # dealer (from the email's own "BMW <Dealer>" heading) is used, as
            # before.
            dealer_mismatch = False
            if ext_selected_dealer_row is not None:
                dealer_row = ext_selected_dealer_row
                if (auto_detected_dealer_row is None
                        or normalize_text(auto_detected_dealer_row.dealer) != normalize_text(dealer_row.dealer)):
                    dealer_mismatch = True
            else:
                dealer_row = auto_detected_dealer_row

            if dealer_row is None:
                st.error("Could not automatically match this email to a dealer from the Excel sheet.")
                continue

            if dealer_mismatch:
                auto_label = f"<strong>{auto_detected_dealer_row.dealer}</strong>" if auto_detected_dealer_row else "<em>(could not be auto-detected)</em>"
                st.markdown(
                    f"<div style='color:#c00000;font-weight:bold;padding:10px;border:2px solid #c00000;"
                    f"border-radius:4px;background-color:#fff0f0;"
                    f"box-sizing:border-box;width:100%;max-width:100%;overflow-wrap:break-word;'>"
                    f"⚠ SELECTED DEALER MISMATCH — This email's HTML actually belongs to {auto_label}, "
                    f"but you selected <strong>{dealer_row.dealer}</strong> ({dealer_row.region}) from the "
                    f"Dealer Selection dropdown. Every Excel-comparable check below is being run against "
                    f"the SELECTED dealer's data, so mismatched content is expected and correct."
                    f"</div>",
                    unsafe_allow_html=True,
                )
            else:
                dropdown_note = " (via Dealer Selection dropdown)" if ext_selected_dealer_row is not None else ""
                st.caption(f"Matched dealer: **{dealer_row.dealer}** ({dealer_row.region}){dropdown_note}")

        panel_lines = panel_text_to_lines(dealer_row.panel_text)
        results_df = compare_source_to_html(panel_lines, job["html"])

        # Feature 16 — Dealer Website Link QA: verifies the CTA button's
        # href AND the Dealer Panel's own "Website: ..." line both belong
        # to the SELECTED (dropdown) or AUTO-DETECTED dealer's own domain
        # (derived from the dealer name itself, since no dedicated
        # "Website" column exists in the Excel sheet), and that the two
        # agree with each other. `dealer_row` here is already the
        # correctly-resolved dealer for this run (dropdown selection wins,
        # otherwise falls back to HTML auto-detection — see the dealer
        # resolution logic above). Rows are appended to the SAME
        # results_df (same item/status schema as the existing Content QA
        # table) immediately after it's built, so they render directly
        # below the existing "Website: ..." Content QA row in the same
        # table, in the same Pass/Fail styling.
        website_link_result = ext_website_link_qa.run_website_link_qa(
            dealer_name=dealer_row.dealer,
            panel_text=dealer_row.panel_text,
            html_raw=job["html"],
            dealer_mismatch=dealer_mismatch,
        )
        if website_link_result.rows:
            website_link_df = pd.DataFrame(website_link_result.rows)
            # compare_source_to_html() only ever produces item/status
            # columns (no "detail"). Concatenating website_link_df (which
            # DOES have a "detail" column) directly would union the
            # columns and backfill every ORIGINAL content row's "detail"
            # with NaN -- which then renders as the literal text "nan" in
            # every existing Present/Missing row's Detail cell. Give the
            # original rows a real empty "detail" first so the union
            # produces "" instead of NaN for them.
            if "detail" not in results_df.columns:
                results_df["detail"] = ""
            results_df = pd.concat([results_df, website_link_df], ignore_index=True)
            results_df["detail"] = results_df["detail"].fillna("")
        elif "detail" not in results_df.columns:
            results_df["detail"] = ""

        # When the dropdown-SELECTED dealer doesn't match the dealer this
        # email's HTML actually belongs to (dealer_mismatch, computed
        # above), every "Missing" row AND every website-link-QA "Fail"
        # row in Content QA is collapsed onto the SAME single shared
        # explanation. "Missing" additionally becomes "Fail" — the
        # content isn't merely absent, it's actively wrong for the
        # selected dealer, which is a stronger, more accurate signal for
        # a reviewer scanning Pass/Fail/Warn at a glance. Repeating a
        # near-identical per-row detail for every one of the dozens of
        # mismatched lines added no information beyond what the mismatch
        # banner above the table already explains, so all of them share
        # one message instead.
        if dealer_mismatch:
            missing_mask = results_df["status"] == "Missing"
            results_df.loc[missing_mask, "status"] = "Fail"
            combined_mismatch_detail = (
                f"Dealer mismatch — this email's HTML belongs to "
                f"{auto_detected_dealer_row.dealer if auto_detected_dealer_row else 'a different dealer'}, "
                f"not the selected dealer ({dealer_row.dealer}). See the mismatch warning above."
            )
            fail_mask = results_df["status"] == "Fail"
            results_df.loc[fail_mask, "detail"] = combined_mismatch_detail

        total = len(results_df)
        # "Present" covers both the original fuzzy-match status value AND
        # the website-link QA rows' "Pass" status (added just above) — both
        # mean "this item is correct" and should count the same way in the
        # Total/Present/Missing metrics. Likewise "Missing" now also covers
        # website-link QA "Fail" rows. "Warn" rows (e.g. no CTA button
        # found at all) are deliberately excluded from both counts, same
        # as they always were for any other Warn-status row.
        present = int(results_df["status"].isin(["Present", "Pass"]).sum()) if total else 0
        missing = int(results_df["status"].isin(["Missing", "Fail"]).sum()) if total else 0

        with ext_theme.section("content", "Content QA"):
            st.subheader("Content QA")
            m1, m2, m3 = st.columns(3)
            m1.metric("Total items", total)
            m2.metric("Present", present)
            m3.metric("Missing", missing)
            render_qa_table(results_df, status_col="status", table_key=f"content_{job_idx}", pass_label="Present")

        exact_match_df = run_dealer_panel_exact_match_qa(panel_lines, job["html"], EXT_CFG)
        if len(exact_match_df):
            with ext_theme.section("exact", "Exact Match QA"):
                st.subheader("Dealer Panel Exact Match QA")
                st.caption("Case-sensitive, space-sensitive comparison against the Excel reference, plus phone/landline number format and link-target checks.")
                render_qa_table(exact_match_df, status_col="status", table_key=f"exact_{job_idx}", pass_label="Passed")

        with ext_theme.section("style", "Styling QA"):
            st.subheader("Styling QA")
            style_issues = run_style_qa(job["html"])
            double_space_issues = run_double_space_qa(job["html"], EXT_CFG)
            punctuation_issues = run_punctuation_spacing_qa(job["html"], EXT_CFG)
            bold_issues = check_bold_required_lines(job["html"], dealer_row, EXT_CFG)
            image_issues = run_image_size_qa(job["html"], job["images"])
            all_issues = style_issues + double_space_issues + punctuation_issues + bold_issues + image_issues

            style_df = pd.DataFrame([i.__dict__ for i in all_issues]) if all_issues else pd.DataFrame(columns=["rule", "severity", "detail"])
            fails = int((style_df["severity"] == "Fail").sum()) if len(style_df) else 0
            warns = int((style_df["severity"] == "Warn").sum()) if len(style_df) else 0
            passes = int((style_df["severity"] == "Pass").sum()) if len(style_df) else 0

            s1, s2, s3 = st.columns(3)
            s1.metric("Passed", passes)
            s2.metric("Warnings", warns)
            s3.metric("Failed", fails)

            render_qa_table(style_df, status_col="severity", table_key=f"style_{job_idx}", pass_label="Passed")

        exact_match_fails = int((exact_match_df["status"] == "Fail").sum()) if len(exact_match_df) else 0
        if dealer_mismatch:
            st.error("SELECTED DEALER MISMATCH — see the warning above. Content/exact-match failures below are expected because this email is being checked against a different dealer's data than the one baked into its HTML.")
        elif missing > 0 or fails > 0 or exact_match_fails > 0:
            st.warning("Some content is missing and/or styling rules failed — see tables above.")
        else:
            st.success("All content found and all styling checks passed (or only warnings where data wasn't available).")

        # Fold the exact-match / phone-format / tel-href-target checks
        # into the SAME DataFrame shape (rule/severity/detail) used for
        # the Excel export, so the Consolidated Excel QA Report captures
        # these new checks too — not just the on-screen view above, which
        # already rendered exact_match_df on its own with its own
        # item/status/detail columns.
        if len(exact_match_df):
            exact_match_for_report = exact_match_df.rename(
                columns={"item": "rule", "status": "severity"}
            )[["rule", "severity", "detail"]]
            style_df_for_report = pd.concat([style_df, exact_match_for_report], ignore_index=True)
        else:
            style_df_for_report = style_df

        ext_job_report = ext_excel_report.JobReportData(
            job_name=job["name"],
            dealer=dealer_row.dealer,
            region=dealer_row.region,
            content_df=results_df,
            style_df=style_df_for_report,
        )
        ext_report_jobs.append(ext_job_report)

        if ext_run_advanced_qa:
            with ext_theme.section("advanced", "Advanced QA"):
                st.subheader("Advanced QA")

                # Manual Text is now per-field (see manual_mode.py) rather than
                # an all-or-nothing switch, so it no longer forces the other
                # sources' *_active flags to False as a block. resolve_active_source
                # still picks ONE visual/HTML master source (for whichever
                # fields Manual Text left blank) using the same priority order
                # as before; Manual Text's own filled-in fields always win
                # regardless of which visual source (if any) is "active".
                ext_sources = ext_priority.MasterSources(
                    manual_text_active=ext_manual_master.is_active(),
                    master_jpg_active=ext_master_jpg_upload is not None,
                    master_pdf_active=ext_master_pdf_upload is not None,
                    master_html_zip_active=ext_master_html_zip_upload is not None,
                    dealer_dropdown_active=ext_selected_dealer_row is not None,
                    excel_active=bool(dealer_rows),
                )
                active_source = ext_priority.resolve_active_source(ext_sources)
                # NOTE (was previously shown on-screen via st.caption; moved to a
                # code comment per request): ext_priority.explain_priority(ext_sources)
                # returns a human-readable string like "Active Master source:
                # Manual Text (highest priority available)." — still computed
                # below for any future debugging/logging use, just not rendered.
                _ext_priority_explanation = ext_priority.explain_priority(ext_sources)

                # Dealer Name fallback fix: when no Dealer Dropdown selection
                # and no Manual Dealer Name is typed, the effective dealer name
                # must come from a Master JPG/PDF/HTML ZIP (below, once that
                # master's OCR/HTML text is available) — NEVER from `dealer_row`,
                # which is only the auto-detected-from-this-email's-own-HTML
                # match used for the separate base Dealer Panel QA feature.
                # Falling back to `dealer_row` here was a tautology: it validates
                # the email's claimed dealer name against that same email's HTML,
                # so a genuinely wrong dealer name baked into the HTML would
                # always "Pass" since it's being checked against itself.
                if ext_selected_dealer_row is not None:
                    _dropdown_dealer_name = ext_selected_dealer_row.dealer
                else:
                    _dropdown_dealer_name = ""

                # Build the Master Banner from whichever visual/HTML source is
                # active. This now runs whenever a visual/HTML master was
                # uploaded — regardless of what active_source says — because
                # active_source only reflects ONE top-priority source (e.g.
                # "manual_text" if any Manual field is filled), but Manual Text
                # is per-field: a Master JPG/PDF/HTML ZIP may still be needed to
                # supply Dealer Name (or Headline/Subheadline) for whichever
                # fields Manual Text left blank. Priority among the visual/HTML
                # uploads themselves still follows Master JPG > Master PDF >
                # Master HTML ZIP, same order as priority.py.
                ext_master_banner_img = None
                ext_master_banner_note = ""
                ext_master_html_text = None  # only populated when Master HTML ZIP supplied the banner
                try:
                    if ext_master_jpg_upload is not None:
                        img = ext_master_image.load_image_from_upload(ext_master_jpg_upload)
                        crop_out = ext_master_image.crop_banner_top_to_dear(img, EXT_CFG)
                        ext_master_banner_img = crop_out.banner_image
                        ext_master_banner_note = crop_out.note
                    elif ext_master_pdf_upload is not None:
                        page_num = ext_master_pdf_page if ext_master_pdf_page and ext_master_pdf_page > 0 else None
                        crop_out = ext_master_pdf.get_master_banner_from_pdf(ext_master_pdf_upload, page_num, EXT_CFG)
                        ext_master_banner_img = crop_out.banner_image
                        ext_master_banner_note = crop_out.note
                    elif ext_master_html_zip_upload is not None:
                        mh = ext_master_html_zip.load_master_from_html_zip(ext_master_html_zip_upload, EXT_CFG)
                        ext_master_banner_img = mh.banner_result.image
                        ext_master_banner_note = mh.note
                        ext_master_html_text = mh.html_text
                except Exception as e:
                    ext_master_banner_note = f"Could not build Master Banner: {e}"

                # -----------------------------------------------------------
                # Expected Headline / Subheadline / Dealer Name / Body Text are
                # now resolved PER-FIELD (see manual_mode.py):
                #   - Any field the user typed into Manual Text always wins for
                #     that field, regardless of what a visual master provides.
                #   - Any field left blank in Manual Text falls through to the
                #     active visual/HTML master source's own OCR/HTML-derived
                #     value for that same field, if available.
                #   - Dealer Dropdown supplies the dealer name fallback (never
                #     the auto-detected `dealer_row` — see note above).
                #   - If nothing provides a field, it stays "" and that field's
                #     QA row is skipped (WARN "No expected value provided"),
                #     same as before.
                # -----------------------------------------------------------
                master_derived_headline = ""
                master_derived_subheadline = ""
                master_derived_dealer_name = ""
                master_derived_body_text = ""
                ext_master_banner_clustered_lines = None
                ext_master_ocr_warning = ""

                if ext_master_banner_img is not None:
                    try:
                        ext_master_banner_clustered_lines, _master_lines_res = ext_ocr.extract_clustered_text(
                            ext_master_banner_img, prefer=EXT_OCR_PREFER_KEY
                        )
                        master_derived_headline = ext_master_banner_clustered_lines.headline_text
                        master_derived_subheadline = ext_master_banner_clustered_lines.subheadline_text
                        # The dealer name is typically the smallest/third font
                        # band under Headline/Subheadline (see banner_text_qa.py's
                        # own band-splitting notes) — use it as the master-derived
                        # dealer name when nothing more explicit (dropdown/manual)
                        # is available, so a Master JPG/PDF alone can still supply
                        # a dealer name for validation.
                        master_derived_dealer_name = ext_master_banner_clustered_lines.other_text
                        if _master_lines_res.warning:
                            ext_master_ocr_warning = _master_lines_res.warning
                    except Exception as e:
                        ext_master_banner_clustered_lines = None
                        ext_master_ocr_warning = f"Could not OCR the Master Banner for Headline/Subheadline/Dealer Name: {e}"

                if ext_master_html_text:
                    master_derived_body_text = html_to_visible_text(BeautifulSoup(ext_master_html_text, "html.parser"))

                expected_headline = ext_manual_master.resolve_headline(master_derived_headline)
                expected_subheadline = ext_manual_master.resolve_subheadline(master_derived_subheadline)
                expected_body_text = ext_manual_master.resolve_body_text(master_derived_body_text)

                # Dealer name resolution order (per latest spec):
                #   1. Dealer Dropdown selection — if the person explicitly
                #      picked a dealer, that ALWAYS wins, even over Manual
                #      Dealer Name — the dropdown is the authoritative choice
                #      once made. Manual Text / Master JPG/PDF/HTML in that
                #      case are only used for Headline/Subheadline/Body Text.
                #   2. Manual Dealer Name (if typed, and no dropdown selection).
                #   3. Master JPG / Master PDF / Master HTML ZIP — OCR'd
                #      dealer-name band from whichever was uploaded (never the
                #      auto-detected `dealer_row` — see note above).
                #   4. "" — no dealer name available, check is skipped.
                if _dropdown_dealer_name:
                    effective_dealer_name = _dropdown_dealer_name
                elif ext_manual_master.dealer_name_is_manual():
                    effective_dealer_name = ext_manual_master.dealer_name.strip()
                elif master_derived_dealer_name.strip():
                    effective_dealer_name = master_derived_dealer_name.strip()
                else:
                    effective_dealer_name = ""

                if ext_master_ocr_warning:
                    st.caption(f"Master Banner OCR note: {ext_master_ocr_warning}")

                # Manual Body Comparison (As Is / To Be) always overrides the
                # master-derived body text if the user typed a "To Be" value —
                # that section is an explicit manual override, unchanged.
                if ext_body_to_be.strip():
                    expected_body_text = ext_body_to_be

                if ext_master_banner_note:
                    st.caption(ext_master_banner_note)

                ext_input_zip_for_banner = job.get("images")
                ext_input_banner_result = None
                try:
                    if isinstance(ext_input_zip_for_banner, dict):
                        ext_input_banner_result = None
                        st.caption("Banner pixel extraction needs an images .zip (a model-folder size map isn't enough) — upload one alongside your HTML file(s) to enable Banner QA.")
                    elif ext_input_zip_for_banner is not None:
                        ext_input_banner_result = ext_banner_detect.extract_banner_image(job["html"], ext_input_zip_for_banner, EXT_CFG)
                except Exception as e:
                    st.caption(f"Could not extract input banner: {e}")

                ext_input_banner_img = ext_input_banner_result.image if ext_input_banner_result else None

                ext_input_banner_ocr_text = ""
                ext_input_banner_clustered_lines = None
                if ext_input_banner_img is not None:
                    ocr_res = ext_ocr.extract_text(ext_input_banner_img, prefer=EXT_OCR_PREFER_KEY)
                    ext_input_banner_ocr_text = ocr_res.text
                    if ocr_res.warning:
                        st.caption(f"OCR note: {ocr_res.warning}")
                    # Also run structured line extraction so Headline / Subheadline
                    # can be matched against their own font-size band instead of
                    # the whole banner text blob (fixes headline+subheadline
                    # being treated as one combined string).
                    try:
                        ext_input_banner_clustered_lines, _lines_res = ext_ocr.extract_clustered_text(
                            ext_input_banner_img, prefer=EXT_OCR_PREFER_KEY
                        )
                    except Exception:
                        ext_input_banner_clustered_lines = None

                ext_html_body_text = html_to_visible_text(BeautifulSoup(job["html"], "html.parser"))
                # Dealer-in-Body must only look at the greeting/body-copy
                # portion (Dear ... up to the "BMW <Dealer>" sign-off line),
                # NOT the dealer panel further down — that's already QA'd
                # separately against the Excel sheet in the main report above.
                ext_html_body_greeting_slice = extract_body_greeting_slice(ext_html_body_text, effective_dealer_name)

                ext_tab_names = ["Body QA", "Banner QA", "Summary"]
                ext_tabs = st.tabs(ext_tab_names)
                ext_all_module_results: List[ExtModuleResult] = []

                with ext_tabs[0]:
                    body_dealer_result = ext_body_qa.run_body_dealer_qa(
                        ext_check_dealer_in_body, effective_dealer_name, ext_html_body_greeting_slice
                    )
                    ext_results_ui.render_module_result(body_dealer_result, table_key=f"adv_body_dealer_{job_idx}")
                    st.divider()
                    manual_body_result = ext_body_qa.run_manual_body_comparison(
                        ext_body_as_is if ext_body_as_is.strip() else expected_body_text,
                        ext_body_to_be if ext_body_to_be.strip() else expected_body_text,
                        ext_html_body_greeting_slice,
                    )
                    ext_results_ui.render_module_result(manual_body_result, table_key=f"adv_manual_body_{job_idx}")
                    ext_all_module_results.extend([body_dealer_result, manual_body_result])

                with ext_tabs[1]:
                    if ext_input_banner_img is None:
                        st.info("No input banner image available — upload an images .zip alongside your HTML file(s) (or use a model-folder .zip as the email input) to enable this tab.")
                    else:
                        # expected_headline / expected_subheadline were already
                        # resolved above from whichever Master source is active
                        # (Manual Text, or OCR'd from Master JPG/PDF/HTML-ZIP
                        # banner) — not Manual Text Mode only.
                        banner_text_result = ext_banner_text_qa.run_banner_text_qa(
                            expected_headline, expected_subheadline, effective_dealer_name,
                            ext_input_banner_ocr_text, EXT_CFG,
                            clustered_lines=ext_input_banner_clustered_lines,
                        )
                        ext_results_ui.render_module_result(banner_text_result, table_key=f"adv_banner_text_{job_idx}")
                        ext_all_module_results.append(banner_text_result)

                        st.divider()
                        dealer_banner_result = ext_dealer.run_dealer_name_validation(
                            dealer_name=effective_dealer_name,
                            check_in_banner=ext_check_dealer_in_banner,
                            check_in_body=False,
                            banner_ocr_text=ext_input_banner_ocr_text,
                            body_text=None,
                        )
                        ext_results_ui.render_module_result(dealer_banner_result, table_key=f"adv_dealer_banner_{job_idx}")
                        ext_all_module_results.append(dealer_banner_result)

                with ext_tabs[2]:
                    ext_results_ui.render_summary(ext_all_module_results, table_key=f"adv_summary_{job_idx}")

                ext_job_report.advanced_module_results = ext_all_module_results
                if effective_dealer_name:
                    ext_job_report.dealer = effective_dealer_name

if run and "ext_report_jobs" in dir() and ext_report_jobs:
    st.divider()
    with ext_theme.section("report", "Excel Report"):
        st.subheader("Consolidated Excel QA Report")
        st.caption(
            "One professionally formatted workbook covering every email/model run above — "
            "Overview sheet plus per-email Content, Style, and (if enabled) Advanced QA sheets."
        )
        ext_workbook_bytes = ext_excel_report.build_qa_workbook(ext_report_jobs)
        st.download_button(
            "📊 Download Full QA Report (Excel)",
            data=ext_workbook_bytes,
            file_name="dealer_panel_qa_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="ext_download_full_excel_report",
        )

if run and "ext_theme_results_group_opened" in dir():
    ext_theme_results_group.__exit__(None, None, None)
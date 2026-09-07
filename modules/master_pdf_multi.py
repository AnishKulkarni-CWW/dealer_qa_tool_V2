"""
Feature 6 (multi) — Multi-Emailer Master PDF.

A single "Sales Push Bulletin" style deck contains the master EMAILER
creative for MANY models at once, e.g.:

    p2   2GC              <- model divider slide (model name only, no image)
    p3   PRINT ADS: HALF PAGE
    p4   PRINT ADS: FULL PAGE
    p5   EMAILER:         <- the master emailer creative for 2GC
    p6   WHATSAPP POST & STORY
    ...
    p11  3LWB             <- next model divider
    ...
    p14  EMAILER:         <- the master emailer creative for 3LWB

So when several adapt .zip files are QA'd in one run, a SINGLE master PDF
is enough: each adapt only has to be routed to the EMAILER page belonging
to its own model. That is what this module does — no per-adapt master PDF
upload is needed (unlike Master JPG / Master HTML ZIP, which genuinely
are one file per adapt).

Two independent jobs live here:

1. `index_emailer_pages()` — walk the deck once and build an index of
   {model label -> EMAILER page}. Model dividers are detected structurally
   (a page carrying almost no text, no embedded image, and a label that
   contains a digit — every real BMW model label does: 2GC, 3LWB, 5LWB,
   iX1 LWB, X1, X3, X5, X7, THE 7, THE i7 — while non-model dividers like
   "THANK YOU" do not). EMAILER pages are detected by the literal word
   "EMAILER" that the deck prints beside every one of them. Everything
   else in the deck (print ads, WhatsApp, GDN, Discovery, Social Media
   banners/posts) is ignored, exactly as required.

2. `match_model()` / `resolve_job_to_entry()` — map an adapt (its .zip /
   .html filename, and if that's inconclusive, its own HTML copy) onto one
   of those indexed models. Matching is done with word-boundary-anchored
   model patterns rather than plain substring tests, because plain
   substrings get this wrong in exactly the cases that matter here:
   "iX1" contains "X1" and "i7" contains "7", so a substring match would
   happily route an X1 adapt to the iX1 master. A `\\b` before the "x" in
   "x1" cannot match inside "ix1" (both are word characters, so there is
   no boundary between them), which makes the distinction automatic and
   exact rather than a fragile ordering hack.

Nothing here rasterizes a page or runs OCR — page selection is pure text
+ structure, which keeps it fast even on a 78-page deck. Rendering the
chosen page's creative is delegated to the existing, already-validated
`master_pdf.select_pdf_page()` / `get_master_banner_from_pdf()` so both
the single-master and multi-master paths share one code path.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# --------------------------------------------------------------------------
# Model vocabulary
# --------------------------------------------------------------------------
# (code, display, [regex alternatives]) — ordered most-specific-first purely
# for readability; correctness does NOT depend on the order because every
# pattern is \b-anchored (see the module docstring). Each entry ends with a
# deliberately loose "bare number" alternative so a terse filename like
# "3.zip" or "7.zip" still resolves, while "x3" / "x7" cannot accidentally
# match it (there is no word boundary between the letter and the digit).
_MODEL_PATTERNS: List[Tuple[str, str, List[str]]] = [
    ("ix1", "iX1 / iX1 LWB", [r"\bi\s*x\s*1\b", r"\bix1lwb\b"]),
    ("ix3", "iX3",           [r"\bi\s*x\s*3\b"]),
    ("i4",  "i4",            [r"\bi\s*4\b"]),
    ("i5",  "i5",            [r"\bi\s*5\b"]),
    ("i7",  "i7 / THE i7",   [r"\bi\s*7\b", r"\b745\b", r"\bxdrive60\b"]),
    ("x1",  "X1",            [r"\bx\s*1\b", r"\bsdrive18i\b"]),
    ("x3",  "X3",            [r"\bx\s*3\b", r"\bxdrive20\b"]),
    ("x5",  "X5",            [r"\bx\s*5\b", r"\bxdrive40i\b"]),
    ("x7",  "X7",            [r"\bx\s*7\b"]),
    ("2gc", "2 Gran Coupé",  [r"\b2\s*gc\b", r"2\s*series\s*gran\s*coup",
                              r"\bgran\s*coup", r"\b218\b", r"\b2\b"]),
    ("3lwb", "3 Series LWB", [r"\b3\s*lwb\b", r"3\s*series\s*lwb",
                              r"3\s*series\s*long\s*wheel", r"\b330li\b", r"\b3\b"]),
    ("5lwb", "5 Series LWB", [r"\b5\s*lwb\b", r"5\s*series\s*lwb",
                              r"5\s*series\s*long\s*wheel", r"\b530li\b", r"\b5\b"]),
    ("7",   "THE 7",         [r"\bthe\s*7\b", r"\b740\s*li\b", r"\b740i\b",
                              r"7\s*series", r"\b7\b"]),
]

# Compiled once at import.
_COMPILED: List[Tuple[str, str, List[re.Pattern]]] = [
    (code, display, [re.compile(p, re.IGNORECASE) for p in pats])
    for code, display, pats in _MODEL_PATTERNS
]

# Specificity = index in _MODEL_PATTERNS is NOT used; instead a match's
# score is the length of the literal text it matched, so "ix1" (3 chars)
# beats a hypothetical looser 1-char "\b3\b" hit in the same string.
_MODEL_DISPLAY: Dict[str, str] = {code: disp for code, disp, _ in _MODEL_PATTERNS}

# Words that never form part of a model identity, stripped before matching
# so noisy filenames ("BMW_iX1_Bird_Delhi_FINAL_v2.zip") still resolve.
_NOISE_WORDS = {
    "bmw", "mini", "the", "series", "emailer", "emailers", "mailer", "mailers",
    "email", "edm", "master", "adapt", "adapts", "final", "approved", "new",
    "copy", "v1", "v2", "v3", "zip", "html", "htm", "index", "dealer",
    "panel", "push", "sales", "bulletin", "creative", "draft", "rev",
}

# Divider slides that carry a short label but are NOT a model.
_NON_MODEL_LABELS = (
    "thank you", "thanks", "thankyou", "the end", "end", "agenda", "index",
    "contents", "content", "overview", "disclaimer", "confidential",
    "appendix", "annexure", "title", "cover",
)

_EMAILER_TOKEN = re.compile(r"\bE\s*-?\s*MAILER\b", re.IGNORECASE)


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------

@dataclass
class EmailerEntry:
    """One master EMAILER creative found inside a multi-model deck."""
    model_label: str          # exactly as printed on the divider slide, e.g. "iX1 LWB"
    model_code: str           # normalized code, e.g. "ix1" ("" if unrecognised)
    page_number: int          # 1-based page number of the EMAILER page
    divider_page: Optional[int] = None   # 1-based page of the model divider

    @property
    def display(self) -> str:
        return f"{self.model_label} — page {self.page_number}"


@dataclass
class EmailerIndex:
    entries: List[EmailerEntry] = field(default_factory=list)
    page_count: int = 0
    note: str = ""

    def is_multi(self) -> bool:
        return len(self.entries) > 1

    def by_code(self) -> Dict[str, EmailerEntry]:
        out: Dict[str, EmailerEntry] = {}
        for e in self.entries:
            if e.model_code and e.model_code not in out:
                out[e.model_code] = e
        return out

    def options(self) -> List[str]:
        return [e.display for e in self.entries]

    def from_option(self, option_label: str) -> Optional[EmailerEntry]:
        for e in self.entries:
            if e.display == option_label:
                return e
        return None


# --------------------------------------------------------------------------
# Normalisation + matching
# --------------------------------------------------------------------------

def _clean_for_match(text: str) -> str:
    """Lowercase, drop punctuation to spaces, and remove noise words so that
    word-boundary patterns can do their job on a predictable string."""
    if not text:
        return ""
    t = str(text).lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    words = [w for w in t.split() if w not in _NOISE_WORDS]
    return " ".join(words)


def match_model(text: str) -> Tuple[str, int]:
    """
    Returns (model_code, score) for the strongest model signal in `text`.
    score is the character length of the matched literal (0 = no match),
    so a specific "ix1" hit always outranks a loose bare-number hit found
    in the same string.
    """
    cleaned = _clean_for_match(text)
    if not cleaned:
        return "", 0

    best_code = ""
    best_score = 0
    for code, _display, patterns in _COMPILED:
        for pat in patterns:
            m = pat.search(cleaned)
            if not m:
                continue
            score = len(re.sub(r"\s+", "", m.group(0)))
            if score > best_score:
                best_score = score
                best_code = code
    return best_code, best_score


def model_display(code: str) -> str:
    return _MODEL_DISPLAY.get(code, code.upper() if code else "")


def _model_hint_from_html(html_text: str) -> Tuple[str, int]:
    """
    Secondary signal used only when the adapt's filename is inconclusive.
    Every one of these emails carries a T&C line naming the exact variant,
    e.g. "...is specific to the BMW iX1 eDrive20L M Sport." — that phrase
    is a far more reliable model fingerprint than the whole document, so
    it is searched first and the full text is only a last resort.
    """
    if not html_text:
        return "", 0

    focused = []
    for m in re.finditer(r"specific to the(.{0,80})", html_text, re.IGNORECASE):
        focused.append(m.group(1))
    for m in re.finditer(r"\bBMW\s+([A-Za-z0-9 ]{0,40})", html_text):
        focused.append(m.group(1))

    for chunk in focused:
        code, score = match_model(chunk)
        if code:
            return code, score
    return "", 0


def resolve_job_to_entry(
    job_name: str,
    html_text: str,
    index: EmailerIndex,
) -> Tuple[Optional[EmailerEntry], str]:
    """
    Routes one adapt to its EMAILER page inside the deck.

    Order of evidence (first conclusive win stops the search):
      1. The adapt's own filename ("iX1.zip" -> ix1).
      2. The adapt's HTML, focused on the "specific to the BMW ..." T&C
         phrase that names the exact variant.
    Returns (entry_or_None, human_readable_reason).
    """
    by_code = index.by_code()
    if not by_code:
        return None, "The master PDF has no recognisable model sections to match against."

    stem = os.path.splitext(os.path.basename(job_name or ""))[0]
    code, score = match_model(stem)
    if code and code in by_code:
        return by_code[code], f"Matched on the file name '{job_name}' → {model_display(code)}."

    code2, _score2 = _model_hint_from_html(html_text or "")
    if code2 and code2 in by_code:
        return by_code[code2], (
            f"File name '{job_name}' was inconclusive — matched on the model named "
            f"inside the email's own terms &amp; conditions → {model_display(code2)}."
        )

    if code and code not in by_code:
        return None, (
            f"'{job_name}' looks like the {model_display(code)}, but the master PDF "
            f"has no EMAILER page for that model."
        )
    return None, f"Could not work out which model '{job_name}' is — pick its master page manually."


# --------------------------------------------------------------------------
# Deck indexing
# --------------------------------------------------------------------------

def _page_lines(page) -> List[str]:
    try:
        raw = page.get_text() or ""
    except Exception:
        raw = ""
    return [ln.strip() for ln in raw.splitlines() if ln.strip()]


def _looks_like_model_divider(lines: List[str], image_count: int) -> bool:
    """
    A model divider slide is: no embedded image, one short line of text,
    and a label containing a digit. Every real BMW model label in these
    decks contains a digit (2GC, 3LWB, 5LWB, iX1 LWB, X1, X3, X5, X7,
    THE 7, THE i7), while the decorative dividers that must NOT be treated
    as models ("THANK YOU", "CONFIDENTIAL") contain none — so this single
    condition separates them cleanly without a hardcoded model list.
    """
    if image_count > 0:
        return False
    if not lines or len(lines) > 2:
        return False
    label = " ".join(lines).strip()
    if len(label) > 24:
        return False
    low = label.lower()
    if any(bad in low for bad in _NON_MODEL_LABELS):
        return False
    return any(ch.isdigit() for ch in label)


def index_emailer_pages(pdf_source) -> EmailerIndex:
    """
    Walk the deck once and return every EMAILER page with the model it
    belongs to. `pdf_source` may be raw bytes or an uploaded file object.
    Never raises for content reasons — an empty index with a `note` is
    returned instead so the UI can explain the situation.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return EmailerIndex(note=(
            "Multi-emailer detection needs the 'pymupdf' package. "
            "Run: pip install pymupdf"
        ))

    if hasattr(pdf_source, "getvalue"):
        data = pdf_source.getvalue()
    elif hasattr(pdf_source, "read"):
        data = pdf_source.read()
    else:
        data = pdf_source

    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as e:
        return EmailerIndex(note=f"Could not open the master PDF: {e}")

    entries: List[EmailerEntry] = []
    current_label = ""
    current_divider = None
    unnamed_seq = 0

    try:
        for i in range(doc.page_count):
            page = doc[i]
            lines = _page_lines(page)
            try:
                image_count = len(page.get_images(full=True))
            except Exception:
                image_count = 0

            if _looks_like_model_divider(lines, image_count):
                current_label = " ".join(lines).strip()
                current_divider = i + 1
                continue

            page_text = " ".join(lines)
            if _EMAILER_TOKEN.search(page_text):
                if current_label:
                    label = current_label
                else:
                    unnamed_seq += 1
                    label = f"Emailer {unnamed_seq}"
                code, _score = match_model(label)
                entries.append(EmailerEntry(
                    model_label=label,
                    model_code=code,
                    page_number=i + 1,
                    divider_page=current_divider,
                ))
        page_count = doc.page_count
    finally:
        doc.close()

    if not entries:
        return EmailerIndex(
            entries=[], page_count=page_count,
            note=(
                "No page labelled 'EMAILER' was found in this PDF, so it is being "
                "treated as an ordinary single-master PDF."
            ),
        )

    # De-duplicate: keep only the FIRST emailer page per model label, so a
    # deck that repeats a model (e.g. a revised slide appended later) does
    # not create two competing entries for the same adapt.
    seen_labels = set()
    unique: List[EmailerEntry] = []
    for e in entries:
        key = e.model_label.strip().lower()
        if key in seen_labels:
            continue
        seen_labels.add(key)
        unique.append(e)

    recognised = sum(1 for e in unique if e.model_code)
    note = (
        f"Found {len(unique)} master emailer page(s) across {page_count} page(s) — "
        f"{recognised} matched to a known model."
    )
    return EmailerIndex(entries=unique, page_count=page_count, note=note)


def build_auto_map(
    jobs: List[dict],
    index: EmailerIndex,
) -> Dict[str, Tuple[Optional[EmailerEntry], str]]:
    """
    jobs: the app's email_jobs list ({"name", "html", ...}).
    Returns {job_name: (entry_or_None, reason)} for display + defaults.
    """
    out: Dict[str, Tuple[Optional[EmailerEntry], str]] = {}
    for job in jobs:
        name = job.get("name", "")
        entry, reason = resolve_job_to_entry(name, job.get("html", ""), index)
        out[name] = (entry, reason)
    return out

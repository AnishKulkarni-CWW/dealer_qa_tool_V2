"""
Feature 10 — OCR Text Extraction.

Uses PaddleOCR if it is installed and its models are available (PaddleOCR
downloads its recognition/detection models ONCE on first use, into a local
cache folder — no admin rights are required for `pip install paddleocr`,
since pip installs into the user's own Python environment; after that
first model download, PaddleOCR runs fully offline).

If PaddleOCR is not installed, or its models are not cached and cannot be
fetched (e.g. no network available on this machine), we automatically and
silently fall back to Tesseract (pytesseract), which is already offline,
lightweight, and available. This guarantees the app keeps working
regardless of what's installed on a given Windows/macOS machine.

Only ever OCRs the banner image that is handed to it — never the full
email — per spec (item 10 & 8).

--------------------------------------------------------------------------
Headline vs Subheadline splitting
--------------------------------------------------------------------------
Banners commonly stack a large-font Headline directly above a smaller-font
Subheadline (see e.g. "DOMINATE EVERYDAY. YOUR WAY." / "DRIVE YOUR MATCH.").
A flat joined text string has no notion of which words belonged to which
line, so a single blob comparison can't reliably tell headline text apart
from subheadline text.

To fix this, `extract_lines()` returns each OCR detection as a `TextLine`
that keeps its text AND its pixel height (bounding-box height) and vertical
position. `cluster_lines_by_size()` then groups those lines into "large"
(headline-sized) and "small" (subheadline-sized) clusters using relative
font height — the tallest line-height band on the banner is treated as the
Headline band, and the next-tallest distinct band as the Subheadline band.
Everything else (dealer name, disclaimers, CTAs, logos-as-text, etc.) is
left as "other" and is still available via the full joined text.

`extract_text()` is kept as-is (flat joined string) for backward
compatibility with callers that only need the whole banner text (e.g. the
OCR QA tab, dealer-in-banner substring check) — nothing about its
behaviour changed.
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image


@dataclass
class OCRResult:
    text: str
    engine_used: str  # "paddleocr" or "tesseract" or "none"
    warning: Optional[str] = None


@dataclass
class TextLine:
    text: str
    height: float          # bounding-box pixel height of this line of text
    top: float              # y-coordinate of the top of the box (0 = top of banner)
    center_y: float          # y-coordinate of the vertical center of the box


@dataclass
class LinesResult:
    lines: List[TextLine] = field(default_factory=list)
    engine_used: str = "none"
    warning: Optional[str] = None

    @property
    def text(self) -> str:
        return "\n".join(l.text for l in self.lines)


@dataclass
class ClusteredLines:
    headline_lines: List[TextLine] = field(default_factory=list)
    subheadline_lines: List[TextLine] = field(default_factory=list)
    other_lines: List[TextLine] = field(default_factory=list)

    @property
    def headline_text(self) -> str:
        return " ".join(l.text for l in self.headline_lines)

    @property
    def subheadline_text(self) -> str:
        return " ".join(l.text for l in self.subheadline_lines)

    @property
    def other_text(self) -> str:
        return " ".join(l.text for l in self.other_lines)

    @property
    def all_text(self) -> str:
        # preserves top-to-bottom reading order across all bands
        all_lines = sorted(
            self.headline_lines + self.subheadline_lines + self.other_lines,
            key=lambda l: l.top,
        )
        return "\n".join(l.text for l in all_lines)


def _try_load_paddleocr():
    """
    Attempts to construct a PaddleOCR reader. Returns None if the package
    isn't installed, or if model initialisation fails for any reason
    (e.g. no cached models and no network to fetch them) — the caller
    falls back to Tesseract in that case.
    """
    try:
        from paddleocr import PaddleOCR  # type: ignore
    except ImportError:
        return None
    try:
        # use_angle_cls off keeps this fast/low-RAM for the mostly-horizontal
        # marketing banner text we deal with here.
        reader = PaddleOCR(use_angle_cls=False, lang="en", show_log=False)
        return reader
    except Exception:
        return None


@lru_cache(maxsize=1)
def _get_paddle_reader():
    return _try_load_paddleocr()


def _box_height_and_center(box) -> Tuple[float, float, float]:
    """
    box: list of 4 [x, y] points (PaddleOCR polygon format), in any order.
    Returns (height, top_y, center_y).
    """
    ys = [pt[1] for pt in box]
    top = min(ys)
    bottom = max(ys)
    height = max(bottom - top, 1.0)
    center_y = (top + bottom) / 2.0
    return height, top, center_y


def _lines_with_paddle(reader, image: Image.Image) -> List[TextLine]:
    arr = np.array(image.convert("RGB"))
    result = reader.ocr(arr, cls=False)
    lines: List[TextLine] = []
    if result:
        for page in result:
            if not page:
                continue
            for det in page:
                # det = [box, (text, confidence)]
                try:
                    box = det[0]
                    text = det[1][0]
                    if not text or not text.strip():
                        continue
                    # Drop pure punctuation/symbol noise (e.g. a stray ")"
                    # picked up from a logo edge) — see Tesseract path for
                    # the same rationale.
                    if not re.search(r"[A-Za-z0-9]", text):
                        continue
                    height, top, center_y = _box_height_and_center(box)
                    lines.append(TextLine(text=text.strip(), height=height, top=top, center_y=center_y))
                except Exception:
                    continue
    # top-to-bottom reading order
    lines.sort(key=lambda l: l.top)
    return lines


def _ocr_with_paddle(reader, image: Image.Image) -> str:
    return "\n".join(l.text for l in _lines_with_paddle(reader, image))


def _configure_tesseract_path_if_needed(pytesseract_module) -> None:
    """
    On Windows, the `tesseract` binary is frequently not on PATH even after
    installing it, which makes pytesseract raise
    "tesseract is not installed or it's not in your PATH". This checks a
    couple of the standard install locations and points pytesseract at the
    binary directly if found, so the app works without the user having to
    edit their PATH manually. No-op on macOS/Linux, and no-op if the
    binary is already discoverable.
    """
    import shutil
    import sys

    if shutil.which("tesseract"):
        return  # already on PATH, nothing to do

    if sys.platform.startswith("win"):
        import os
        candidates = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Tesseract-OCR\tesseract.exe"),
        ]
        for path in candidates:
            if os.path.isfile(path):
                pytesseract_module.pytesseract.tesseract_cmd = path
                return


def _lines_with_tesseract(image: Image.Image) -> List[TextLine]:
    import pytesseract
    _configure_tesseract_path_if_needed(pytesseract)

    rgb = image.convert("RGB")
    data = pytesseract.image_to_data(rgb, output_type=pytesseract.Output.DICT)

    # Group word-level boxes into lines using tesseract's own
    # block/par/line numbering, then merge word text + take the max word
    # height in that line as the line's font height (more robust than
    # averaging, since a single tall character can otherwise get diluted).
    line_groups = {}
    n = len(data.get("text", []))
    for i in range(n):
        word = (data["text"][i] or "").strip()
        if not word:
            continue
        conf = data.get("conf", ["-1"] * n)[i]
        try:
            if float(conf) < 0:
                continue
        except (ValueError, TypeError):
            pass
        # Skip isolated punctuation/symbol-only tokens (e.g. a stray ")"
        # picked up from a logo edge or icon) so they don't get glued
        # onto the front/back of real headline/subheadline text.
        if not re.search(r"[A-Za-z0-9]", word):
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        top = data["top"][i]
        height = data["height"][i]
        line_groups.setdefault(key, {"words": [], "top": top, "bottom": top + height})
        g = line_groups[key]
        g["words"].append(word)
        g["top"] = min(g["top"], top)
        g["bottom"] = max(g["bottom"], top + height)

    lines: List[TextLine] = []
    for g in line_groups.values():
        text = " ".join(g["words"]).strip()
        if not text:
            continue
        # Drop lines that are pure punctuation/symbol noise (e.g. a stray
        # ")" or "|" picked up from a logo edge or icon) — they carry no
        # real word content and would otherwise get glued onto the front
        # of whatever real headline text follows, corrupting the match.
        if not re.search(r"[A-Za-z0-9]", text):
            continue
        top = float(g["top"])
        bottom = float(g["bottom"])
        height = max(bottom - top, 1.0)
        center_y = (top + bottom) / 2.0
        lines.append(TextLine(text=text, height=height, top=top, center_y=center_y))

    lines.sort(key=lambda l: l.top)
    return lines


def _ocr_with_tesseract(image: Image.Image) -> str:
    import pytesseract
    _configure_tesseract_path_if_needed(pytesseract)
    return pytesseract.image_to_string(image.convert("RGB"))


def extract_text(image: Image.Image, prefer: str = "paddleocr") -> OCRResult:
    """
    Main entry point (unchanged behaviour). `image` must already be the
    cropped banner region — callers should never pass a full-email
    screenshot here. Returns a flat joined string, top-to-bottom.
    """
    if prefer == "paddleocr":
        reader = _get_paddle_reader()
        if reader is not None:
            try:
                text = _ocr_with_paddle(reader, image)
                return OCRResult(text=text, engine_used="paddleocr")
            except Exception as e:
                # fall through to tesseract
                fallback_warning = f"PaddleOCR failed at runtime ({e}); used Tesseract instead."
            else:
                fallback_warning = None
        else:
            fallback_warning = "PaddleOCR not installed/available; used Tesseract instead."
    else:
        fallback_warning = None

    try:
        text = _ocr_with_tesseract(image)
        return OCRResult(text=text, engine_used="tesseract", warning=fallback_warning)
    except Exception as e:
        return OCRResult(text="", engine_used="none", warning=f"OCR unavailable: {e}")


def extract_lines(image: Image.Image, prefer: str = "paddleocr") -> LinesResult:
    """
    Structured entry point: returns each OCR'd line with its font height
    and vertical position, so callers can distinguish Headline (large
    font) from Subheadline (smaller font) from other banner text. Same
    PaddleOCR-preferred / Tesseract-fallback behaviour as extract_text().
    """
    if prefer == "paddleocr":
        reader = _get_paddle_reader()
        if reader is not None:
            try:
                lines = _lines_with_paddle(reader, image)
                return LinesResult(lines=lines, engine_used="paddleocr")
            except Exception as e:
                fallback_warning = f"PaddleOCR failed at runtime ({e}); used Tesseract instead."
            else:
                fallback_warning = None
        else:
            fallback_warning = "PaddleOCR not installed/available; used Tesseract instead."
    else:
        fallback_warning = None

    try:
        lines = _lines_with_tesseract(image)
        return LinesResult(lines=lines, engine_used="tesseract", warning=fallback_warning)
    except Exception as e:
        return LinesResult(lines=[], engine_used="none", warning=f"OCR unavailable: {e}")


def cluster_lines_by_size(lines_result: LinesResult, jitter_tolerance_ratio: float = 0.08) -> ClusteredLines:
    """
    Groups OCR'd lines into Headline (largest font band), Subheadline
    (next distinct, smaller font band), and Dealer Name / Other (any
    remaining, smaller bands) — purely from relative line height, no
    dependency on absolute pixel size, so it works whether the banner was
    cropped/scaled to any resolution.

    A fixed percentage threshold for "is this a new band?" doesn't work
    across different banners — some banners have a huge Headline vs
    Subheadline size difference and a small Subheadline vs Dealer Name
    difference, others are closer to uniform across all three, or even
    collapse Headline+Subheadline into nearly the same size on a
    different banner design. A single cutoff percentage is always wrong
    for some real banner somewhere.

    Instead, this uses a "biggest relative gap" cut-point approach that
    adapts to whatever size differences actually exist on THIS banner:
      1. Merge lines whose heights are within `jitter_tolerance_ratio`
         (default 8%) of each other into the same "distinct size" group
         first — this absorbs pure OCR measurement noise between two
         lines that are visually the same font size (e.g. a wrapped
         2-line Headline), without conflating genuinely different sizes.
      2. Take the resulting distinct size groups, sorted largest to
         smallest, and compute the proportional gap between each
         consecutive pair.
      3. Cut at the two BIGGEST gaps (if there are 3+ distinct size
         groups) to form up to 3 bands: Headline / Subheadline / Dealer
         Name. If there are only 2 distinct sizes, one gap is cut,
         forming Headline / Subheadline (Dealer Name band stays empty).
         If there's only 1 distinct size, everything is Headline.
      This way the split always lands on the biggest actual size jump on
      THIS banner, rather than requiring that jump to exceed some fixed
      percentage that may not match every banner's proportions.

    Band 1 = Headline, Band 2 = Subheadline, Band 3 (if present) =
    Dealer Name / Other.
    """
    clustered = ClusteredLines()
    if not lines_result.lines:
        return clustered

    # Step 1: merge near-identical heights into "distinct size" groups.
    by_height_desc = sorted(lines_result.lines, key=lambda l: l.height, reverse=True)
    size_groups: List[List[TextLine]] = []
    group_anchor_height = None
    for line in by_height_desc:
        if group_anchor_height is None:
            size_groups.append([line])
            group_anchor_height = line.height
        else:
            drop = (group_anchor_height - line.height) / group_anchor_height if group_anchor_height > 0 else 0
            if drop > jitter_tolerance_ratio:
                size_groups.append([line])
                group_anchor_height = line.height
            else:
                size_groups[-1].append(line)
                group_anchor_height = max(group_anchor_height, line.height)

    # Each size group's representative height = its tallest member (most
    # reliable single measurement, since OCR under-measures more often
    # than it over-measures on partial/descender-heavy text).
    group_heights = [max(l.height for l in g) for g in size_groups]

    if len(size_groups) == 1:
        clustered.headline_lines = sorted(size_groups[0], key=lambda l: l.top)
        return clustered

    # Step 2: proportional gap between each consecutive pair of distinct
    # size groups (gap relative to the taller of the pair).
    gaps = []
    for i in range(len(group_heights) - 1):
        taller, shorter = group_heights[i], group_heights[i + 1]
        gap = (taller - shorter) / taller if taller > 0 else 0
        gaps.append(gap)

    # Step 3: cut at the biggest gap(s) — up to 2 cuts (3 bands). Cuts are
    # chosen by gap size, largest first, then applied in position order.
    num_cuts = min(2, len(gaps))
    cut_positions = sorted(
        sorted(range(len(gaps)), key=lambda i: gaps[i], reverse=True)[:num_cuts]
    )

    bands: List[List[TextLine]] = []
    band_start = 0
    for cut_idx in cut_positions:
        band_groups = size_groups[band_start:cut_idx + 1]
        bands.append([l for g in band_groups for l in g])
        band_start = cut_idx + 1
    bands.append([l for g in size_groups[band_start:] for l in g])

    if len(bands) >= 1:
        clustered.headline_lines = sorted(bands[0], key=lambda l: l.top)
    if len(bands) >= 2:
        clustered.subheadline_lines = sorted(bands[1], key=lambda l: l.top)
    if len(bands) >= 3:
        remaining = [l for band in bands[2:] for l in band]
        clustered.other_lines = sorted(remaining, key=lambda l: l.top)

    return clustered


def extract_clustered_text(image: Image.Image, prefer: str = "paddleocr",
                            jitter_tolerance_ratio: float = 0.08) -> Tuple[ClusteredLines, LinesResult]:
    """
    Convenience wrapper: OCRs the banner and returns both the size-based
    line clusters and the raw LinesResult (for the flat "found" text /
    warnings callers may still want to display).
    """
    lines_result = extract_lines(image, prefer=prefer)
    clustered = cluster_lines_by_size(lines_result, jitter_tolerance_ratio=jitter_tolerance_ratio)
    return clustered, lines_result

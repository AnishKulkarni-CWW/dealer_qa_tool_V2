"""
Feature 6 — Master PDF Module.

IMPORTANT CONTEXT (validated against real sample PDFs — see notes below):
Master PDFs in this workflow are usually multi-page CAMPAIGN DECKS (16:9
slides: title page, EDM, WhatsApp Post, WhatsApp/Social Story, Social Post
with multiple frames, crossword/puzzle creative, print ads, etc.) — NOT a
single flattened screenshot of one email. Each slide typically has ONE
real embedded "master creative" image (the actual EDM/WhatsApp design)
plus a text column describing it (HL/SHL/Body Copy). Several slides in
the same deck have almost no usable text at all (Story slides, Crossword
slides) because their copy is baked into the image itself, not present as
selectable PDF text.

This means the old approach — OCR-scanning raw rasterized PDF PAGES for
the word "dear" — fails for most of these decks:
  - Many valid creative pages have no "Dear ..." salutation on them at all
    (WhatsApp Story, Social Post frames, Crossword, Print ads, title/thank
    you slides).
  - When a page number IS supplied, the previous code rendered the WHOLE
    page (text column + image) rather than isolating the actual embedded
    master image — so OCR/crop logic was operating on the wrong region
    entirely (mixing in the slide's body-copy text column).

VALIDATED FIX: every genuine master EDM/creative image in this workflow
carries a distinctive footer baked into the image itself: a dealer
address block, "Tel:"/"Website:" contact lines, and a "FOLLOW US" line
above social icons. This footer is NOT present on Story/Social-frame/
Crossword/title/thank-you slides. Cropping a candidate image down to its
bottom ~25% and OCR'ing JUST that strip reliably detects "follow us"
(confirmed on real sample PDFs) even when whole-page OCR at the same DPI
misses it (the footer text is small relative to the full 16:9 slide).

Selection strategy:
  1. For each page, find every embedded raster image and its on-page
     bounding box (via PyMuPDF/fitz — no page rasterization needed for
     this step, so it's fast even on large decks).
  2. Per plan: always take the SINGLE LARGEST image on the page as the
     candidate (multi-frame Social Post slides, Story slides with 2
     images, etc. are resolved this way — no image-picking UI).
  3. Render that image's bounding box at high DPI (so small footer text
     stays legible), crop its bottom ~25% as a footer strip, and OCR just
     that strip for "follow us" (+ "tel:"/"website:" as secondary
     signals). This is the plan's requested detection condition.
  4. The page with the strongest-scoring candidate image wins. If NO page
     has any candidate image at all, fall back to page 1's full render
     (never hard-fail) and say so clearly.
  5. Only the winning candidate IMAGE (not the full slide/page) is passed
     into the existing crop-to-"Dear" logic — this fixes the second half
     of the bug (crop/OCR was running on the wrong region when a page
     number was manually selected too).

If a page number is explicitly supplied, footer-signal scoring is
skipped, but the SAME "extract the largest embedded image on that page"
step still runs — so manual page selection also gets the correct image,
not the whole slide.
"""

import io
from dataclasses import dataclass
from typing import List, Optional

from PIL import Image

from .config import DEFAULT_CONFIG
from .master_image import crop_banner_top_to_dear, CropOutcome


@dataclass
class PdfPageChoice:
    page_index: int  # 0-based
    page_image: Image.Image
    auto_selected: bool
    note: str


# Signals baked into the real master-creative footer image (validated via
# OCR against real sample decks). "follow us" is the strongest/most
# reliable signal; others are supporting evidence only.
_FOOTER_SIGNALS = (
    ("follow us", 5),
    ("tel:", 2),
    ("tel.", 2),
    ("website:", 2),
)


def _largest_image_rect(page):
    """Returns (xref, rect) for the single largest embedded raster image
    on the page, or (None, None) if the page has no images."""
    biggest_xref = None
    biggest_rect = None
    biggest_area = 0.0
    for img_info in page.get_images(full=True):
        xref = img_info[0]
        for rect in page.get_image_rects(xref):
            area = rect.width * rect.height
            if area > biggest_area:
                biggest_area = area
                biggest_xref = xref
                biggest_rect = rect
    return biggest_xref, biggest_rect


def _render_rect(page, rect, dpi: int) -> Image.Image:
    import fitz
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, clip=rect)
    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")


def _render_full_page(page, dpi: int) -> Image.Image:
    import fitz
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")


def _ocr_footer_score(candidate_image: Image.Image) -> float:
    """Crops the bottom ~25% of the candidate image (where the dealer
    address / Tel: / Website: / FOLLOW US footer sits on real master
    creatives) and OCRs just that strip. Whole-image or whole-page OCR at
    normal DPI is NOT reliable for this — the footer text is small
    relative to the full slide/creative, so isolating the strip first is
    required (validated against real sample PDFs)."""
    try:
        import pytesseract
    except ImportError:
        return 0.0

    w, h = candidate_image.size
    if h < 20:
        return 0.0
    footer = candidate_image.crop((0, int(h * 0.75), w, h))
    try:
        text = pytesseract.image_to_string(footer, config="--psm 6").lower()
    except Exception:
        return 0.0

    score = 0.0
    for signal, pts in _FOOTER_SIGNALS:
        if signal in text:
            score += pts
    return score


def auto_select_pdf_page(
    pdf_bytes: bytes,
    dpi: int = 200,
) -> PdfPageChoice:
    """Scans every page of the deck, extracts each page's single largest
    embedded image, and OCR-scores that image's footer strip for the
    dealer-panel "FOLLOW US" / "Tel:" / "Website:" signature that only
    the real master-creative image carries. Returns the best-scoring
    page's largest image (not the full slide)."""
    try:
        import fitz  # PyMuPDF
    except ImportError as e:
        raise RuntimeError(
            "Could not auto-detect the master page: the 'pymupdf' package is "
            "not installed. Run: pip install pymupdf"
        ) from e

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        raise RuntimeError(f"Could not open PDF: {e}")

    if doc.page_count == 0:
        doc.close()
        raise ValueError("The PDF appears to have no pages.")

    best_idx = -1
    best_score = -1.0
    best_image = None

    for i in range(doc.page_count):
        page = doc[i]
        xref, rect = _largest_image_rect(page)
        if xref is None:
            continue
        candidate = _render_rect(page, rect, dpi)
        score = _ocr_footer_score(candidate)
        if score > best_score:
            best_score = score
            best_idx = i
            best_image = candidate

    if best_idx == -1 or best_score <= 0:
        # No page had any candidate image with a recognizable footer
        # signal (or no images at all) — never hard-fail, fall back to
        # page 1's full render and say so clearly.
        page = doc[0]
        image = _render_full_page(page, dpi)
        note = (
            f"Could not detect a master creative footer ('FOLLOW US' / "
            f"'Tel:' / 'Website:') on any of {doc.page_count} page(s) — "
            f"defaulted to a full render of page 1. Verify this is correct, "
            f"or specify the page number manually."
        )
        doc.close()
        return PdfPageChoice(page_index=0, page_image=image, auto_selected=True, note=note)

    note = (
        f"Auto-detected the master creative on page {best_idx + 1} of "
        f"{doc.page_count} (matched dealer-panel footer signal — "
        f"'FOLLOW US' / 'Tel:' / 'Website:' — on that page's largest "
        f"embedded image)."
    )
    doc.close()
    return PdfPageChoice(page_index=best_idx, page_image=best_image, auto_selected=True, note=note)


def select_pdf_page(
    uploaded_pdf,
    page_number_1_based: Optional[int],
    dpi: int = 200,
) -> PdfPageChoice:
    """Selects a page from the uploaded PDF.

    If page_number_1_based is given, auto-detection is skipped, BUT the
    same "extract this page's single largest embedded image" step still
    runs — so manually selecting a page still crops/OCRs the actual
    creative image, not the whole slide (this was the second half of the
    reported bug: manual page selection was reading the slide's body-copy
    text column instead of the email image).

    If the selected page has no embedded image at all (e.g. a pure-text
    or title slide), falls back to rendering the full page so the flow
    never hard-fails.
    """
    data = uploaded_pdf.getvalue() if hasattr(uploaded_pdf, "getvalue") else uploaded_pdf.read()

    if not page_number_1_based:
        return auto_select_pdf_page(data, dpi=dpi)

    try:
        import fitz
    except ImportError as e:
        raise RuntimeError(
            "Could not open the PDF: the 'pymupdf' package is not "
            "installed. Run: pip install pymupdf"
        ) from e
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as e:
        raise RuntimeError(f"Could not open PDF: {e}")

    if doc.page_count == 0:
        doc.close()
        raise ValueError("The PDF appears to have no pages.")

    idx = page_number_1_based - 1
    if idx < 0 or idx >= doc.page_count:
        page_count = doc.page_count
        doc.close()
        raise ValueError(
            f"Page {page_number_1_based} is out of range — this PDF has {page_count} page(s)."
        )

    page = doc[idx]
    xref, rect = _largest_image_rect(page)
    page_count = doc.page_count
    if xref is not None:
        image = _render_rect(page, rect, dpi)
        note = (
            f"Using explicitly specified page {page_number_1_based} of "
            f"{page_count} — extracted that page's largest embedded image "
            f"as the master creative (not the full slide)."
        )
    else:
        image = _render_full_page(page, dpi)
        note = (
            f"Using explicitly specified page {page_number_1_based} of "
            f"{page_count} — this page has no embedded image, so the full "
            f"page was rendered instead."
        )
    doc.close()
    return PdfPageChoice(page_index=idx, page_image=image, auto_selected=False, note=note)


def get_master_banner_from_pdf(
    uploaded_pdf,
    page_number_1_based: Optional[int] = None,
    config=DEFAULT_CONFIG,
) -> CropOutcome:
    """Unchanged external contract: still returns a CropOutcome, still
    crops the selected page's master image to the "Dear" banner region —
    identical to how Master JPG works, just fed the correctly-extracted
    creative image instead of the whole slide/page."""
    choice = select_pdf_page(uploaded_pdf, page_number_1_based)
    crop_outcome = crop_banner_top_to_dear(choice.page_image, config)
    crop_outcome.note = choice.note + " " + crop_outcome.note
    return crop_outcome

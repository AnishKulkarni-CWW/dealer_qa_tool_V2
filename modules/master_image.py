"""
Feature 5 — Master Image Module.

Upload a Master JPG (full email screenshot). We auto-crop from the TOP
of the image down to the line containing the word "Dear" (the salutation
that starts the body copy) using OCR word-level bounding boxes. Everything
above that line is treated as the Master Banner.
"""

from dataclasses import dataclass
from io import BytesIO
from typing import Optional

from PIL import Image

from .config import DEFAULT_CONFIG


@dataclass
class CropOutcome:
    banner_image: Image.Image
    anchor_found: bool
    anchor_y: Optional[int]
    note: str


def load_image_from_upload(uploaded_file) -> Image.Image:
    data = uploaded_file.getvalue() if hasattr(uploaded_file, "getvalue") else uploaded_file.read()
    return Image.open(BytesIO(data)).convert("RGB")


def _find_anchor_y_paddle(image: Image.Image, anchor_word: str) -> Optional[int]:
    from .ocr_engine import _get_paddle_reader
    import numpy as np

    reader = _get_paddle_reader()
    if reader is None:
        return None
    arr = np.array(image.convert("RGB"))
    result = reader.ocr(arr, cls=False)
    if not result:
        return None
    for page in result:
        if not page:
            continue
        for det in page:
            try:
                box, (text, conf) = det
                if anchor_word in text.strip().lower():
                    ys = [pt[1] for pt in box]
                    return int(min(ys))
            except Exception:
                continue
    return None


# Tesseract page-segmentation modes tried, in order, when hunting for the
# salutation anchor. The default (PSM 3, full auto) is not enough on real
# master creatives: on the "THE 7" emailer page of a live BMW bulletin it
# returned only four words for the entire 851x1472 image and missed a
# "Dear Patron," that is perfectly legible — while PSM 6 ("assume a single
# uniform block of text") found it at confidence 97. A big photograph above
# the copy is all it takes to throw the automatic segmenter off.
_ANCHOR_PSM_CONFIGS = ("", "--psm 6", "--psm 11")

# If no configuration finds the anchor at native size, try once more on an
# enlarged copy — small body copy is the other reason the word goes missing.
_ANCHOR_UPSCALE = 2


def _anchor_hit(word: str, anchor_word: str) -> bool:
    """
    True when `word` is the salutation anchor, allowing for one OCR slip.

    Exact substring first (the original rule, unchanged). Failing that, a
    single-character edit is tolerated on words of the same length, because
    a missed "Dear" costs the whole banner: the crop silently falls back to
    a fixed fraction of the image height, which on a real BMW emailer cut
    the banner text off entirely and left Headline and Subheadline with no
    expected value at all. One edit is tight enough that ordinary body copy
    never trips it.
    """
    w = (word or "").strip().lower()
    a = (anchor_word or "").strip().lower()
    if not w or not a:
        return False
    if a in w:
        return True
    if len(a) < 4 or len(w) != len(a):
        return False
    return sum(1 for x, y in zip(w, a) if x != y) <= 1


def _scan_data_for_anchor(data: dict, anchor_word: str, scale: int) -> Optional[int]:
    n = len(data.get("text", []))
    for i in range(n):
        if _anchor_hit(data["text"][i], anchor_word):
            return int(float(data["top"][i]) / scale)
    return None


def _find_anchor_y_tesseract(image: Image.Image, anchor_word: str) -> Optional[int]:
    """
    Locates the salutation line, trying several Tesseract page-segmentation
    modes and then an upscaled pass before giving up. A single default-mode
    call is not reliable enough — see `_ANCHOR_PSM_CONFIGS`.
    """
    import pytesseract
    from .ocr_engine import _configure_tesseract_path_if_needed

    _configure_tesseract_path_if_needed(pytesseract)
    rgb = image.convert("RGB")

    for cfg in _ANCHOR_PSM_CONFIGS:
        try:
            data = pytesseract.image_to_data(
                rgb, output_type=pytesseract.Output.DICT, config=cfg
            )
        except Exception:
            continue
        y = _scan_data_for_anchor(data, anchor_word, 1)
        if y is not None:
            return y

    try:
        big = rgb.resize(
            (rgb.width * _ANCHOR_UPSCALE, rgb.height * _ANCHOR_UPSCALE), Image.LANCZOS
        )
    except Exception:
        return None
    for cfg in _ANCHOR_PSM_CONFIGS:
        try:
            data = pytesseract.image_to_data(
                big, output_type=pytesseract.Output.DICT, config=cfg
            )
        except Exception:
            continue
        y = _scan_data_for_anchor(data, anchor_word, _ANCHOR_UPSCALE)
        if y is not None:
            return y
    return None


def find_anchor_y(image: Image.Image, anchor_word: str) -> Optional[int]:
    """Try PaddleOCR first, fall back to Tesseract — same policy as ocr_engine."""
    y = _find_anchor_y_paddle(image, anchor_word)
    if y is not None:
        return y
    try:
        return _find_anchor_y_tesseract(image, anchor_word)
    except Exception:
        return None


def _strip_has_text(image: Image.Image, top: int, bottom: int) -> bool:
    """True if OCR finds any real word in the horizontal strip [top, bottom)."""
    if bottom <= top:
        return False
    try:
        import pytesseract
        from .ocr_engine import _configure_tesseract_path_if_needed

        _configure_tesseract_path_if_needed(pytesseract)
        strip = image.convert("RGB").crop((0, top, image.width, bottom))
        if strip.height < 4:
            return False
        text = pytesseract.image_to_string(strip, config="--psm 6")
    except Exception:
        return False
    return any(ch.isalnum() for ch in text)


def _fallback_crop_height(image: Image.Image, config) -> int:
    """
    Height to use when the salutation anchor could not be found.

    Starts at the configured fallback fraction, but will not hand back a
    banner region with no text in it at all. A blind fixed fraction was
    cutting the banner copy off a real BMW "THE 7" master creative: the
    banner text sits at 35% of the image height, the fallback cropped at
    exactly 35%, and the resulting "banner" contained nothing but a
    photograph. Headline and Subheadline then came back empty and the QA
    report said "No expected value provided for this field" for a master
    that was perfectly readable.

    So the strip below the initial cut is examined in small steps and the
    crop is extended only until text appears — which lands on the banner
    copy, well above the body, and stops immediately.
    """
    start = int(image.height * config.crop_anchor_fallback_ratio)
    limit = int(image.height * getattr(config, "crop_anchor_fallback_max_ratio", 0.60))
    step_ratio = getattr(config, "crop_anchor_fallback_step_ratio", 0.05)
    step = max(int(image.height * step_ratio), 1)

    if _strip_has_text(image, 0, start):
        return start
    y = start
    while y < limit:
        nxt = min(y + step, limit)
        if _strip_has_text(image, y, nxt):
            # Text starts inside this strip — take the whole strip so the
            # line is never cut in half, then stop.
            return nxt
        y = nxt
    return start


def crop_banner_top_to_dear(image: Image.Image, config=DEFAULT_CONFIG) -> CropOutcome:
    """
    Crops `image` from y=0 down to just above the row where the anchor
    word (default "dear") is first found. If not found, falls back to a
    configurable fraction of the image height (never crashes).
    """
    anchor_y = find_anchor_y(image, config.crop_anchor_word)

    if anchor_y is not None and anchor_y > 10:
        crop = image.crop((0, 0, image.width, anchor_y))
        return CropOutcome(
            banner_image=crop,
            anchor_found=True,
            anchor_y=anchor_y,
            note=f"Cropped banner from top to detected '{config.crop_anchor_word}' at y={anchor_y}px.",
        )

    fallback_y = _fallback_crop_height(image, config)
    crop = image.crop((0, 0, image.width, fallback_y))
    pct = int(round(100.0 * fallback_y / max(image.height, 1)))
    return CropOutcome(
        banner_image=crop,
        anchor_found=False,
        anchor_y=None,
        note=(
            f"Could not locate the word '{config.crop_anchor_word}' via OCR — "
            f"fell back to cropping the top {pct}% of the image ({fallback_y}px) "
            f"as the banner region, extended as needed until banner text was "
            f"actually inside the crop."
        ),
    )

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


def _find_anchor_y_tesseract(image: Image.Image, anchor_word: str) -> Optional[int]:
    import pytesseract
    from .ocr_engine import _configure_tesseract_path_if_needed

    _configure_tesseract_path_if_needed(pytesseract)
    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    n = len(data.get("text", []))
    for i in range(n):
        word = (data["text"][i] or "").strip().lower()
        if anchor_word in word:
            return int(data["top"][i])
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

    fallback_y = int(image.height * config.crop_anchor_fallback_ratio)
    crop = image.crop((0, 0, image.width, fallback_y))
    return CropOutcome(
        banner_image=crop,
        anchor_found=False,
        anchor_y=None,
        note=(
            f"Could not locate the word '{config.crop_anchor_word}' via OCR — "
            f"fell back to cropping the top {int(config.crop_anchor_fallback_ratio * 100)}% "
            f"of the image ({fallback_y}px) as the banner region."
        ),
    )

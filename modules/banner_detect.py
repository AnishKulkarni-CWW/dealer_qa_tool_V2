"""
Feature 8 — Banner Detection Module (generic, reused by feature 7).

Given raw HTML text and a zip file containing its referenced images,
locates the first "banner" image (the large hero image at the top of the
email — never a logo/icon), extracts it from the zip, and returns it as a
PIL Image ready for OCR / visual comparison.

Never OCRs the full email — only ever returns a single banner image.
"""

import posixpath
import zipfile
from dataclasses import dataclass
from io import BytesIO
from typing import Dict, List, Optional

from bs4 import BeautifulSoup
from PIL import Image

from .config import DEFAULT_CONFIG


@dataclass
class BannerCandidate:
    src: str
    width: Optional[int]
    height: Optional[int]


@dataclass
class BannerDetectionResult:
    image: Optional[Image.Image]
    src: Optional[str]
    note: str


def _parse_dimension(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        return int(str(value).strip().replace("px", ""))
    except Exception:
        return None


def list_img_candidates(html_raw: str) -> List[BannerCandidate]:
    soup = BeautifulSoup(html_raw, "html.parser")
    candidates = []
    for img in soup.find_all("img"):
        src = img.get("src")
        if not src:
            continue
        w = _parse_dimension(img.get("width"))
        h = _parse_dimension(img.get("height"))
        candidates.append(BannerCandidate(src=src, width=w, height=h))
    return candidates


def pick_banner_candidate(
    candidates: List[BannerCandidate],
    config=DEFAULT_CONFIG,
) -> Optional[BannerCandidate]:
    """
    Picks the first image whose declared width/height meet the configured
    banner minimums (skips small logos/icons/social buttons). If no image
    declares dimensions large enough, falls back to the very first <img>
    in the document (typical banner-first email layout).
    """
    for c in candidates[: config.banner_max_candidates * 4]:
        if c.width and c.height and c.width >= config.banner_min_width_px and c.height >= config.banner_min_height_px:
            return c
    return candidates[0] if candidates else None


def _find_in_zip(zf: zipfile.ZipFile, src: str) -> Optional[bytes]:
    """
    Matches an <img src="..."> path against entries inside the zip,
    trying exact path, then basename-only matching (common when the HTML
    references e.g. "images/banner.jpg" and the zip has a different
    top-level folder name).
    """
    normalized = src.lstrip("./")
    names = zf.namelist()

    for name in names:
        if name.endswith(normalized):
            return zf.read(name)

    basename = posixpath.basename(src)
    for name in names:
        if posixpath.basename(name).lower() == basename.lower():
            return zf.read(name)

    return None


def extract_banner_image(
    html_raw: str,
    zip_source,
    config=DEFAULT_CONFIG,
) -> BannerDetectionResult:
    """
    zip_source: an uploaded .zip file-like object containing the images
    referenced by html_raw.
    """
    candidates = list_img_candidates(html_raw)
    if not candidates:
        return BannerDetectionResult(image=None, src=None, note="No <img> tags found in HTML.")

    chosen = pick_banner_candidate(candidates, config)
    if chosen is None:
        return BannerDetectionResult(image=None, src=None, note="No suitable banner image candidate found.")

    if zip_source is None:
        return BannerDetectionResult(
            image=None, src=chosen.src,
            note=f"Banner image reference found ('{chosen.src}') but no images .zip was provided to extract it from.",
        )

    try:
        zf = zipfile.ZipFile(zip_source)
    except Exception as e:
        return BannerDetectionResult(image=None, src=chosen.src, note=f"Could not read images zip: {e}")

    raw_bytes = _find_in_zip(zf, chosen.src)
    if raw_bytes is None:
        return BannerDetectionResult(
            image=None, src=chosen.src,
            note=f"Banner image '{chosen.src}' referenced in HTML but not found inside the zip.",
        )

    try:
        img = Image.open(BytesIO(raw_bytes)).convert("RGB")
    except Exception as e:
        return BannerDetectionResult(image=None, src=chosen.src, note=f"Could not decode banner image: {e}")

    return BannerDetectionResult(image=img, src=chosen.src, note=f"Banner extracted from '{chosen.src}'.")

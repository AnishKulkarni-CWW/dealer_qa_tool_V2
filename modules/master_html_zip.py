"""
Feature 7 — Master HTML ZIP Module.

Upload a zip containing a Master HTML file (and its images). We locate
the HTML inside the zip, find its banner <img src="...">, extract that
image from the same zip, and treat it as the Master Banner — ready to be
compared against the Input HTML's banner via banner_detect + banner_compare.
"""

import zipfile
from dataclasses import dataclass
from typing import Optional

from .banner_detect import extract_banner_image, BannerDetectionResult
from .config import DEFAULT_CONFIG


@dataclass
class MasterHtmlZipResult:
    html_text: Optional[str]
    banner_result: BannerDetectionResult
    html_filename: Optional[str]
    note: str


def _find_html_in_zip(zf: zipfile.ZipFile) -> Optional[str]:
    html_candidates = [
        n for n in zf.namelist()
        if n.lower().endswith((".html", ".htm")) and not n.endswith("/")
    ]
    if not html_candidates:
        return None
    # Prefer index.html, then shortest path (top-level files over nested).
    html_candidates.sort(key=lambda n: (0 if n.lower().endswith("index.html") else 1, len(n)))
    return html_candidates[0]


def load_master_from_html_zip(uploaded_zip, config=DEFAULT_CONFIG) -> MasterHtmlZipResult:
    try:
        zf = zipfile.ZipFile(uploaded_zip)
    except Exception as e:
        return MasterHtmlZipResult(
            html_text=None,
            banner_result=BannerDetectionResult(image=None, src=None, note=""),
            html_filename=None,
            note=f"Could not open the Master HTML zip: {e}",
        )

    html_name = _find_html_in_zip(zf)
    if html_name is None:
        return MasterHtmlZipResult(
            html_text=None,
            banner_result=BannerDetectionResult(image=None, src=None, note=""),
            html_filename=None,
            note="No .html/.htm file found inside the Master HTML zip.",
        )

    html_text = zf.read(html_name).decode("utf-8", errors="ignore")

    # Re-open the zip fresh for extract_banner_image (it does its own ZipFile() call).
    uploaded_zip_bytes = uploaded_zip.getvalue() if hasattr(uploaded_zip, "getvalue") else None
    from io import BytesIO
    zip_for_banner = BytesIO(uploaded_zip_bytes) if uploaded_zip_bytes is not None else uploaded_zip

    banner_result = extract_banner_image(html_text, zip_for_banner, config)

    return MasterHtmlZipResult(
        html_text=html_text,
        banner_result=banner_result,
        html_filename=html_name,
        note=f"Master HTML found at '{html_name}'. {banner_result.note}",
    )

"""
Feature 9 — Banner Visual Comparison.

Pipeline: Resize -> Align (ORB homography) -> SSIM -> ORB match quality
-> Difference mask -> Red bounding boxes on mismatched regions.

Produces Master / Input / Difference / Overlay images plus a Pass/Fail/Warn
verdict, using only OpenCV + NumPy + Pillow + scikit-image's SSIM
(all offline, all lightweight).
"""

from dataclasses import dataclass
from io import BytesIO
from typing import List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity as ssim

from .config import DEFAULT_CONFIG
from .results import ModuleResult, PASS, FAIL, WARN


@dataclass
class VisualCompareOutcome:
    ssim_score: float
    orb_good_matches: int
    aligned_ok: bool
    master_img: Image.Image
    input_img: Image.Image
    diff_img: Image.Image
    overlay_img: Image.Image
    mismatch_boxes: List[Tuple[int, int, int, int]]
    verdict: str
    detail: str


def _pil_to_cv(img: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)


def _cv_to_pil(arr: np.ndarray) -> Image.Image:
    return Image.fromarray(cv2.cvtColor(arr, cv2.COLOR_BGR2RGB))


def _resize_to_width(img: np.ndarray, target_width: int) -> np.ndarray:
    h, w = img.shape[:2]
    if w == 0:
        return img
    scale = target_width / w
    new_size = (target_width, max(1, int(h * scale)))
    return cv2.resize(img, new_size, interpolation=cv2.INTER_AREA)


def _align_with_orb(master: np.ndarray, other: np.ndarray, config) -> Tuple[np.ndarray, bool, int]:
    """
    Aligns `other` onto `master` using ORB feature matching + homography.
    Returns (aligned_other, aligned_ok, good_match_count). If alignment
    fails (too few matches / degenerate homography) returns the original
    (unaligned) `other` resized to match master's shape, with aligned_ok=False.
    """
    gray_master = cv2.cvtColor(master, cv2.COLOR_BGR2GRAY)
    gray_other = cv2.cvtColor(other, cv2.COLOR_BGR2GRAY)

    orb = cv2.ORB_create(nfeatures=2000)
    kp1, des1 = orb.detectAndCompute(gray_master, None)
    kp2, des2 = orb.detectAndCompute(gray_other, None)

    if des1 is None or des2 is None or len(kp1) < 4 or len(kp2) < 4:
        resized = cv2.resize(other, (master.shape[1], master.shape[0]))
        return resized, False, 0

    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    matches = bf.knnMatch(des1, des2, k=2)

    good = []
    for pair in matches:
        if len(pair) != 2:
            continue
        m, n = pair
        if m.distance < config.orb_ratio_test * n.distance:
            good.append(m)

    if len(good) < config.orb_min_good_matches:
        resized = cv2.resize(other, (master.shape[1], master.shape[0]))
        return resized, False, len(good)

    src_pts = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst_pts = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)

    H, mask = cv2.findHomography(dst_pts, src_pts, cv2.RANSAC, 5.0)
    if H is None:
        resized = cv2.resize(other, (master.shape[1], master.shape[0]))
        return resized, False, len(good)

    aligned = cv2.warpPerspective(other, H, (master.shape[1], master.shape[0]))
    return aligned, True, len(good)


def _diff_and_boxes(master: np.ndarray, aligned_other: np.ndarray, config) -> Tuple[np.ndarray, np.ndarray, List[Tuple[int, int, int, int]]]:
    gray_master = cv2.cvtColor(master, cv2.COLOR_BGR2GRAY)
    gray_other = cv2.cvtColor(aligned_other, cv2.COLOR_BGR2GRAY)

    score, diff = ssim(gray_master, gray_other, full=True)
    diff = (diff * 255).astype("uint8")
    diff_inv = 255 - diff

    thresh = cv2.threshold(diff_inv, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < config.diff_min_contour_area:
            continue
        x, y, w, h = cv2.boundingRect(c)
        boxes.append((x, y, w, h))

    return diff_inv, thresh, boxes


def compare_banners(
    master_image: Image.Image,
    input_image: Image.Image,
    config=DEFAULT_CONFIG,
) -> VisualCompareOutcome:
    master_cv = _pil_to_cv(master_image)
    input_cv = _pil_to_cv(input_image)

    master_cv = _resize_to_width(master_cv, config.resize_target_width)
    input_cv = _resize_to_width(input_cv, config.resize_target_width)

    aligned_input, aligned_ok, good_matches = _align_with_orb(master_cv, input_cv, config)

    # SSIM requires identical dimensions — align step already guarantees this.
    diff_vis, thresh, boxes = _diff_and_boxes(master_cv, aligned_input, config)
    score = ssim(
        cv2.cvtColor(master_cv, cv2.COLOR_BGR2GRAY),
        cv2.cvtColor(aligned_input, cv2.COLOR_BGR2GRAY),
    )

    overlay = aligned_input.copy()
    for (x, y, w, h) in boxes:
        cv2.rectangle(overlay, (x, y), (x + w, y + h), (0, 0, 255), 2)  # BGR red

    if score >= config.ssim_pass_threshold:
        verdict = PASS
    elif score >= config.ssim_warn_threshold:
        verdict = WARN
    else:
        verdict = FAIL

    detail_parts = [f"SSIM similarity: {score:.3f}", f"ORB good matches: {good_matches}"]
    if not aligned_ok:
        detail_parts.append("Alignment fell back to a simple resize (not enough ORB matches for homography) — results may be less precise.")
    if boxes:
        detail_parts.append(f"{len(boxes)} mismatched region(s) highlighted in red.")
    else:
        detail_parts.append("No significant mismatched regions detected.")

    return VisualCompareOutcome(
        ssim_score=float(score),
        orb_good_matches=good_matches,
        aligned_ok=aligned_ok,
        master_img=_cv_to_pil(master_cv),
        input_img=_cv_to_pil(aligned_input),
        diff_img=_cv_to_pil(cv2.cvtColor(diff_vis, cv2.COLOR_GRAY2BGR)),
        overlay_img=_cv_to_pil(overlay),
        mismatch_boxes=boxes,
        verdict=verdict,
        detail="; ".join(detail_parts),
    )


def to_module_result(outcome: VisualCompareOutcome) -> ModuleResult:
    result = ModuleResult(module_name="Banner Visual QA")
    result.add(
        "Visual", "Banner similarity (SSIM)", outcome.verdict,
        detail=outcome.detail,
    )
    for label, img in [
        ("Master Banner", outcome.master_img),
        ("Input Banner (aligned)", outcome.input_img),
        ("Difference Map", outcome.diff_img),
        ("Overlay (mismatches highlighted)", outcome.overlay_img),
    ]:
        buf = BytesIO()
        img.save(buf, format="PNG")
        from .results import ImageArtifact
        result.images.append(ImageArtifact(label=label, png_bytes=buf.getvalue()))
    return result

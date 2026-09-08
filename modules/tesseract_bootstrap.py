"""
tesseract_bootstrap.py — provides a working Tesseract binary on hosts where
`apt-get` is unavailable or broken.

Why this module exists
======================
Streamlit Community Cloud installs system packages by running `apt-get
update` followed by an install of everything in `packages.txt`. As of
September 2026 their build image is Debian **trixie** (13) but still carries
**bullseye** (11) entries in its sources list, and Debian 11's security
Release file has now expired:

    E: Release file for .../bullseye-security/InRelease is expired
       (invalid since 5h 46min 50s)

`apt-get update` treats an expired Release file as a hard error and exits
non-zero, and the Streamlit installer aborts the entire dependency step on
that exit code — so `pip install` never runs either and the app never
starts. Nothing in the repository can influence this: the apt step runs
before `packages.txt` is even parsed, and the expiry timestamp is a fixed
point in the past, so it does not heal on a retry.

The only lever a repository has is to **not ship a `packages.txt` at all**,
which makes Cloud skip the apt step entirely. That gets the app running but
leaves it with no Tesseract, and the RapidOCR fallback in `ocr_engine.py` is
a real downgrade for this app — measured on the four BMW adapts, it reads a
car's number plate as banner copy on X7 and lets the giant "X1" badge
outrank the real headline on X1, because none of the small-type upscale,
core-line-height or debris-alignment work in `_lines_with_tesseract` applies
to that path.

This module closes that gap. It fetches a self-contained Tesseract AppImage
(binary, Leptonica, image codecs and `eng.traineddata` all inside one file),
extracts it without root, and points `pytesseract` at the result. Verified
to give byte-identical Banner QA results to a system Tesseract install.

What this is NOT
================
Not a replacement for `packages.txt` on a host where apt works. If
`tesseract` is already on PATH — every local dev machine, any Docker image,
Hugging Face Spaces, or Community Cloud once they repair their image — this
module does nothing at all and returns immediately.

Cost and safety
===============
* One ~57 MB download, once per container, cached on disk afterwards.
* No root, no FUSE. `--appimage-extract` unpacks the squashfs in userspace.
* Standard library only: no new entry in `requirements.txt`.
* Every failure path is non-fatal. If the download or extraction fails the
  function returns False and `ocr_engine` carries on to its existing
  RapidOCR / "no OCR engine available" handling, exactly as before.
* The version is pinned, so an upstream release cannot silently change OCR
  behaviour underneath the thresholds in `ocr_engine.py`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

# Pinned deliberately. Banner QA thresholds in ocr_engine.py (the 18px
# upscale trigger, the 2px band floor, the confidence-50 debris cutoff) were
# measured against Tesseract 5.x output; letting the version float would let
# an upstream release move results without anything in this repo changing.
# 5.5.0 was verified to produce results identical to a 5.3.4 system install
# across all ten master pages of the BMW July bulletin.
TESSERACT_VERSION = "5.5.0"

_RELEASE_URL = (
    "https://github.com/AlexanderP/tesseract-appimage/releases/download/"
    "v{v}/tesseract-{v}-x86_64.AppImage"
)

# Tried in order if the pinned version ever disappears upstream.
_FALLBACK_VERSIONS = ("5.5.0", "5.4.1", "5.3.4")

_DOWNLOAD_TIMEOUT_SECONDS = 180

# Set once the bootstrap has run, so repeated calls are free. None = not yet
# attempted; True/False = attempted, with that outcome.
_BOOTSTRAP_RESULT: Optional[bool] = None


def _cache_root() -> Path:
    """
    A writable directory that survives for the life of the container.

    Home is preferred (on Community Cloud that is /home/adminuser, which is
    writable); the system temp directory is the fallback for hosts with a
    read-only or missing home.
    """
    for candidate in (
        os.environ.get("OMNIQA_TESSERACT_DIR"),
        os.environ.get("XDG_CACHE_HOME"),
        str(Path.home() / ".cache") if Path.home().exists() else None,
        tempfile.gettempdir(),
    ):
        if not candidate:
            continue
        try:
            root = Path(candidate) / "omniqa-tesseract"
            root.mkdir(parents=True, exist_ok=True)
            probe = root / ".writable"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return root
        except Exception:
            continue
    return Path(tempfile.gettempdir()) / "omniqa-tesseract"


def _apply(app_root: Path) -> bool:
    """
    Points pytesseract at an extracted AppImage and proves it runs.

    `AppRun` is used rather than `usr/bin/tesseract` directly because it sets
    up the bundle's own LD_LIBRARY_PATH for Leptonica and the image codecs.
    TESSDATA_PREFIX is set explicitly to the directory that holds the
    .traineddata files, which is what Tesseract 5.x expects.
    """
    run = app_root / "AppRun"
    tessdata = app_root / "usr" / "share" / "tesseract-ocr" / "5" / "tessdata"
    if not run.is_file() or not (tessdata / "eng.traineddata").is_file():
        return False
    try:
        run.chmod(0o755)
    except Exception:
        pass

    os.environ["TESSDATA_PREFIX"] = str(tessdata)
    try:
        import pytesseract  # imported lazily so this module has no hard dep
        pytesseract.pytesseract.tesseract_cmd = str(run)
        pytesseract.get_tesseract_version()  # raises if the binary won't run
        return True
    except Exception:
        return False


def _download(url: str, dest: Path) -> bool:
    tmp = dest.with_suffix(".part")
    try:
        with urllib.request.urlopen(url, timeout=_DOWNLOAD_TIMEOUT_SECONDS) as r, \
                open(tmp, "wb") as f:
            shutil.copyfileobj(r, f, length=1024 * 256)
        # A truncated or error-page download must never be cached as valid.
        if tmp.stat().st_size < 10 * 1024 * 1024:
            tmp.unlink(missing_ok=True)
            return False
        tmp.replace(dest)
        return True
    except Exception:
        tmp.unlink(missing_ok=True)
        return False


def _extract(appimage: Path, workdir: Path) -> Optional[Path]:
    """
    Unpacks the AppImage in userspace. `--appimage-extract` needs no root and
    no FUSE — it just unpacks the squashfs appended to the ELF — which is the
    whole reason this approach works on a locked-down PaaS container.
    """
    try:
        appimage.chmod(0o755)
        subprocess.run(
            [str(appimage), "--appimage-extract"],
            cwd=str(workdir),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=_DOWNLOAD_TIMEOUT_SECONDS,
        )
    except Exception:
        return None
    root = workdir / "squashfs-root"
    return root if root.is_dir() else None


def ensure_tesseract(force: bool = False) -> bool:
    """
    Makes a usable Tesseract available to pytesseract. Returns True if one is
    now usable (whether it was already there or this call provisioned it).

    Safe to call as often as you like: the outcome is cached in memory, and
    the extracted bundle is cached on disk, so only the very first call on a
    cold container does any work.

    Never raises. A host with no network, a changed upstream release or a
    non-x86_64 architecture all simply return False, and the caller falls
    through to whatever it did before this module existed.
    """
    global _BOOTSTRAP_RESULT
    if _BOOTSTRAP_RESULT is not None and not force:
        return _BOOTSTRAP_RESULT

    # 1. A system install always wins — local dev, Docker, or Community Cloud
    #    once their apt step is repaired. Nothing to do.
    if shutil.which("tesseract"):
        _BOOTSTRAP_RESULT = True
        return True

    # 2. This bundle is Linux x86_64 only. On Windows and macOS the existing
    #    path-probing in ocr_engine._configure_tesseract_path_if_needed is
    #    the right answer, so bow out and let it handle things.
    if not sys.platform.startswith("linux"):
        _BOOTSTRAP_RESULT = False
        return False

    root = _cache_root()

    # 3. Already extracted on a previous run in this container.
    existing = root / "squashfs-root"
    if existing.is_dir() and _apply(existing):
        _BOOTSTRAP_RESULT = True
        return True

    # 4. Download and extract. The pinned version first, then fallbacks, in
    #    case a release is ever pulled upstream.
    versions = [TESSERACT_VERSION] + [
        v for v in _FALLBACK_VERSIONS if v != TESSERACT_VERSION
    ]
    for version in versions:
        appimage = root / f"tesseract-{version}-x86_64.AppImage"
        if not appimage.is_file() and not _download(
            _RELEASE_URL.format(v=version), appimage
        ):
            continue
        extracted = _extract(appimage, root)
        if extracted is not None and _apply(extracted):
            _BOOTSTRAP_RESULT = True
            return True
        # Do not keep a bundle that would not run.
        shutil.rmtree(root / "squashfs-root", ignore_errors=True)

    _BOOTSTRAP_RESULT = False
    return False


def status() -> Tuple[bool, str]:
    """(available, human_readable_message) — for surfacing in the UI."""
    if shutil.which("tesseract"):
        return True, "Tesseract is installed on this machine."
    if _BOOTSTRAP_RESULT is True:
        return True, (
            f"Tesseract {TESSERACT_VERSION} was provisioned automatically "
            "(this host has no system Tesseract available)."
        )
    if _BOOTSTRAP_RESULT is False:
        return False, (
            "Tesseract is not installed and could not be provisioned "
            "automatically. OCR will fall back to RapidOCR if it is "
            "installed, which reads banners less accurately."
        )
    return False, "Tesseract bootstrap has not run yet."

# Confirmed: this will not self-heal. Here is the fix that keeps full quality.

## Why the retry proved it

Between your two builds the expiry counter moved from `5h 34min 50s` to
`5h 46min 50s` — **exactly the 12 minutes that elapsed**. That is a fixed
timestamp in the past receding further, not a transient mirror hiccup.
Debian 11's security Release file expired on 7 Sep and will never become
valid again. Streamlit's build image carries a stale `bullseye-security`
source alongside its current `trixie` ones, `apt-get update` exits non-zero
on the expired Release file, and their installer aborts the whole dependency
step on that exit code — before `packages.txt` is even parsed, and before
`pip install` runs.

Delete-and-recreate is ruled out. Nothing in your repo can change the
outcome **while a `packages.txt` exists**, because that file is what makes
Cloud run the apt step at all.

## The fix

Instead of settling for the degraded RapidOCR fallback, provision a real
Tesseract without apt. A self-contained AppImage carries the binary,
Leptonica, the image codecs and `eng.traineddata` in a single file, and
`--appimage-extract` unpacks it **in userspace — no root, no FUSE**, which
is exactly what a locked-down PaaS container allows.

I built and tested it end to end:

```
ensure_tesseract() -> True
status: Tesseract 5.5.0 was provisioned automatically
cold (download + extract):  1.8s
warm (cached on disk)    :  0.01s
```

And, most importantly, **identical QA results** to the system Tesseract the
earlier fixes were validated against:

| Adapt | System Tesseract 5.3.4 | AppImage 5.5.0 (no apt) | RapidOCR |
|---|---|---|---|
| X7 | Headline Pass | Headline **Pass** | Warn |
| X1 | Headline Pass | Headline **Pass** | **Fail** |
| THE 7 | Headline Pass | Headline **Pass** | Pass |
| THE i7 | Headline Pass | Headline **Pass** | Pass |

## What to change

**1. Delete `packages.txt` from the repo.** This is the whole point — no
file, no apt step, no failure. You were only ever using one of its three
entries anyway: `pdf2image` is imported nowhere in your codebase (so
`poppler-utils` was dead), and `opencv-python-headless` needs no libGL (so
`libgl1` was dead).

**2. Add `modules/tesseract_bootstrap.py`** (new file, attached).

**3. Replace `modules/ocr_engine.py`** with the attached version. The only
change from the one you already have is a six-line hook inside
`_configure_tesseract_path_if_needed()`, which every pytesseract call
already routes through.

**4. Keep `requirements.txt` as-is.** The bootstrap uses `urllib` and
`subprocess` from the standard library — no new dependency.

Nothing else. `app.py` still untouched.

## Why this is safe

* **No-op where apt works.** The first thing it does is `shutil.which
  ("tesseract")`; if one exists — your Windows machine, any Docker image,
  Hugging Face Spaces, or Community Cloud once they repair their image — it
  returns immediately and downloads nothing. Your local behaviour does not
  change at all.
* **Never raises.** Every failure path returns False, and `ocr_engine` falls
  through to the RapidOCR / "no OCR engine available" handling it already
  had. Worst case you are exactly where you'd have been anyway.
* **Version pinned to 5.5.0.** The Banner QA thresholds (the 18px upscale
  trigger, the 2px band floor, the confidence-50 debris cutoff) were
  measured against Tesseract 5.x. Letting the version float would let an
  upstream release move your results with nothing in the repo changing.
  Fallbacks to 5.4.1 / 5.3.4 exist only if a release is pulled.
* **Windows and macOS bow out.** The bundle is Linux x86_64; on other
  platforms the existing install-path probing handles things as before.

## Two honest caveats

**A one-time ~57 MB download on each cold container.** Cached afterwards, so
only the first request after a restart pays the 1.8s. Community Cloud gives
you about 1 GB of disk and the extracted bundle is ~210 MB, which fits, but
it is not free — if you later hit a disk-space error, that is the thing to
look at.

**It depends on a third-party GitHub release** (`AlexanderP/tesseract-appimage`,
a long-running community build of upstream Tesseract). That is a real
supply-chain dependency you would not normally take on. It is pinned rather
than floating, and it fails closed rather than silently. If your org would
not accept that, the clean alternative is a host where you control the image
— Hugging Face Spaces (Streamlit SDK, free) or a four-line Dockerfile on
Render/Railway — where `apt-get install tesseract-ocr` just works and none
of this is needed.

## Verifying it worked

Once deployed, open the **X1** and **THE i7** Banner QA cards. Headline
should be **Pass** on both, and the Advanced QA note should read *"PaddleOCR
not installed/available; used Tesseract instead"*. If it mentions RapidOCR
instead, the bootstrap did not succeed — check the app logs for a network
error reaching `github.com`.

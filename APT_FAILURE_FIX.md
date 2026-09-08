# `installer returned a non-zero exit code` — what actually happened

**This is not your repo, and it is not the CRLF fix.** Your `packages.txt`
was never even read. The build died one step earlier, inside `apt-get
update`, before a single package was considered.

## The log, decoded

```
Hit:1 http://deb.debian.org/debian-security bullseye-security InRelease   <- Debian 11
Hit:2 http://deb.debian.org/debian trixie InRelease                        <- Debian 13
Get:6 https://packages.microsoft.com/debian/11/prod bullseye InRelease     <- Debian 11
...
E: Release file for .../bullseye-security/InRelease is expired
   (invalid since 5h 34min 50s). Updates for this repository will not be applied.
[02:47:56] installer returned a non-zero exit code
```

Streamlit's build container is Debian **trixie** (13) but still carries
**bullseye** (11) entries in its sources list, left over from an older base
image. Debian 11's security Release file has now expired. `apt-get update`
treats an expired Release file as a hard error and exits non-zero, and
Streamlit's installer aborts the whole dependency step on that exit code —
so `pip install` never runs either.

Two details that matter:

* The apt step **only runs when `packages.txt` exists**. <cite index="22-1">Community Cloud detects a `packages.txt` in the repository root, parses it, and installs the listed packages.</cite> No file, no apt step, no failure.
* Streamlit's own docs still describe the image as <cite index="22-1">Debian 11 ("bullseye")</cite> while your log shows trixie — which is exactly the mismatch producing this.

This is a recurring platform bug, not a new one. It has hit Community Cloud
several times before with the same signature (expired or renamed Debian
security repos), and it is tracked upstream as
[streamlit/streamlit#6838](https://github.com/streamlit/streamlit/issues/6838).

---

## Fix 1 — delete the app and create it fresh (try this first)

Not a reboot. **Delete and recreate.** When Streamlit fixed this exact
class of failure previously, their own guidance was that
<cite index="16-1">the underlying issue was resolved for new apps, and anyone hitting it on an existing app needed to delete and recreate it before the fix took effect</cite> — because the broken image is baked into the app's existing container.

From the Community Cloud dashboard: **⋮ → Delete app**, then **Create app**
again pointing at the same repo, branch `main`, main file `app.py`. Costs
about two minutes and it is the fix that worked last time.

While you are there, also swap in the trimmed `packages.txt` below. Two of
your three apt packages were never needed:

| Package | Verdict |
|---|---|
| `poppler-utils` | **Remove.** Only `pdf2image` needs it, and nothing in your codebase imports `pdf2image` — your PDF work all goes through PyMuPDF (`import fitz`). |
| `libgl1` | **Remove.** Only full `opencv-python` needs libGL. You install `opencv-python-headless`, which does not. |
| `tesseract-ocr` | **Keep.** This is the only one that matters. |

Fewer packages is a smaller target, and it makes the failure easier to read
if it recurs.

---

## Fix 2 — if it still fails: remove `packages.txt` entirely

This is the only lever you control. No `packages.txt` means no apt step,
and the deploy will get through to `pip install`. But then Tesseract is not
on the machine, so OCR has to come from pip.

1. Delete `packages.txt` from the repo.
2. Replace `requirements.txt` with `requirements-noapt.txt` (rename it).

That adds `rapidocr-onnxruntime`, which your `ocr_engine.py` already
supports as a last-resort engine and which ships its ONNX models inside the
wheel — no apt, no model download at runtime.

### Be clear-eyed about what this costs

I installed RapidOCR and ran your four adapts through it end to end, with
RapidOCR reading both the Master creative and the dealer email:

| Adapt | Tesseract (validated) | RapidOCR |
|---|---|---|
| THE 7 | Headline **Pass** | Headline **Pass** |
| THE i7 | Headline **Pass** | Headline **Pass** |
| X7 | Headline **Pass** | Headline **Warn** |
| X1 | Headline **Pass** | Headline **Fail** |

On X7 it reads the car's **number plate** as banner copy, so the expected
Headline became `MaSE1438 ALL-IN,NO MOREEXCUSES`. On X1 the giant `X1`
badge outranks the real headline — the master read `X1` and the email read
`X`. It also runs words together everywhere
(`DRIVEYOURMATCHWITHBENEFITSOF5O%ROADTAX.`) and reads `50%` as `5O%`.

And none of the fixes from the last round apply on that path: the small-type
upscale, `_core_line_height` and the alignment-based debris filter all live
inside `_lines_with_tesseract`. RapidOCR builds its lines from polygon boxes
through `_lines_with_rapidocr` instead.

So treat Fix 2 as **keeping the link reachable while Streamlit repair their
image**, not as a substitute. If you end up stuck on it, tell me and I'll
port the same protections onto the RapidOCR path — the number-plate and
badge-line problems are both things the alignment filter would catch.

---

## Fix 3 — if you need production quality now

Community Cloud is the constraint here, not your code. Anywhere you control
the base image will just work:

* **Hugging Face Spaces (Streamlit SDK, free)** — add a `Dockerfile` or a
  `packages.txt`; its Debian base is current.
* **Render / Railway / Fly.io free tier** — a four-line Dockerfile
  (`FROM python:3.12-slim`, `apt-get install -y tesseract-ocr
  tesseract-ocr-eng`, `pip install -r requirements.txt`,
  `streamlit run app.py`).

Both keep Tesseract, which means the results you verified locally are the
results you get live.

---

## What to check in the build log next time

A good run shows the apt step completing and naming your packages:

```
Apt dependencies were installed from .../packages.txt using apt-get.
...
Setting up tesseract-ocr (5.x) ...
```

If you see `E: Release file ... is expired` or `E: Unable to locate
package`, apt did not finish — go to Fix 2.

Once it is up, open the **X1** and **THE i7** Banner QA cards. Headline
should be **Pass** on both, and the Advanced QA note should read *"PaddleOCR
not installed/available; used Tesseract instead"*. If that note instead says
RapidOCR, the apt step silently failed.

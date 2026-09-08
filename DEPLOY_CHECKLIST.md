# Pushing OMNIQA to GitHub → Streamlit Community Cloud

## 1. One thing that will definitely break the deploy

`packages.txt` is saved with **Windows CRLF line endings**:

```
t e s s e r a c t - o c r  \r \n
p o p p l e r - u t i l s  \r \n
l i b g l 1
```

Streamlit Cloud feeds that file straight to `apt-get`, and the trailing
`\r` becomes part of the package name:

```
apt-get install 'tesseract-ocr\r'   -> E: Unable to locate package
apt-get install 'poppler-utils\r'   -> E: Unable to locate package
apt-get install 'libgl1'            -> OK
```

Only `libgl1` installs (it is last, so it has no `\r`). **Tesseract never
gets installed**, and because Tesseract is the engine your app actually
uses — PaddleOCR is not in `requirements.txt` — every Banner QA and Body
OCR check fails at runtime. The app boots fine, so this looks like a code
bug rather than a build problem, which is what makes it nasty.

The build log will not shout about it either: `apt-get` prints those `E:`
lines and Streamlit carries on to `pip install`.

Replacement `packages.txt` is included, LF-only, with `tesseract-ocr-eng`
added explicitly so you are not relying on it arriving as a recommended
dependency.

## 2. `config.toml` is in the wrong place to ever be read

Streamlit only reads `.streamlit/config.toml`. Yours is at the repo root.
`run_app.py` builds a path to it (`config_toml = str(base_path / ...)`) but
never passes it to the CLI, so locally your theme is coming from the
explicit `--server.*` flags plus `modules/theme.py`, and the `[theme]`
block has never actually been applied.

On Cloud that means the selected radio dots and checked checkboxes would
render in Streamlit's default red instead of your indigo — exactly the
thing the comment in that file warns about.

Move it to `.streamlit/config.toml`. The included copy also changes two
values for Cloud, with the reasoning in comments:

| Setting | Yours | Cloud copy | Why |
|---|---|---|---|
| `maxUploadSize` | 5120 (5 GB) | 1024 | Community Cloud has ~2.7 GB RAM total. A real run is ~40 MB. Local desktop is unaffected — `run_app.py` passes 5120 on the CLI and flags beat the file. |
| `enableXsrfProtection` | false | true | The URL is public. If the uploader breaks, flip it back and redeploy — that is the only symptom it causes. |

## 3. Repo layout — the four fixed files go in `modules/`

`app.py` imports `from modules import ocr_engine`, and the fixed files use
relative imports (`from .config import DEFAULT_CONFIG`). Putting them at
the repo root will fail with `ImportError: attempted relative import with
no known parent package`.

```
your-repo/
├── app.py
├── run_app.py
├── requirements.txt          <- replace
├── packages.txt              <- replace (CRLF fix)
├── .python-version           <- new (optional)
├── .gitignore                <- new (optional)
├── .streamlit/
│   └── config.toml           <- MOVED from repo root
└── modules/
    ├── __init__.py
    ├── ocr_engine.py         <- replace
    ├── banner_text_qa.py     <- replace
    ├── master_image.py       <- replace
    ├── config.py             <- replace
    └── ... (all others unchanged)
```

Main file path in the Streamlit Cloud form: `app.py`.
`run_app.py` is only for the packaged desktop build — Cloud never runs it,
and its Tkinter folder-picker would fail on a headless container if it did.

## 4. Nothing else is needed

Checked, and all clear:

* **No disk writes.** The Excel report goes `wb.save(BytesIO)` →
  `st.download_button`. Nothing depends on `OMNIQA_OUTPUT_DIR`, which is
  only set by `run_app.py` for the desktop build. Cloud's ephemeral
  filesystem is never touched.
* **No new dependencies from my changes.** The upscale path uses
  `Image.LANCZOS` (Pillow, already required) and the multi-PSM anchor uses
  `pytesseract`'s `config=` argument (no new package). `pyflakes` is clean
  on all four files apart from one pre-existing unused `typing.Iterable`
  import.
* **The 78-page bulletin scan is cheap.** `index_emailer_pages()` uses
  `page.get_text()`, not rasterisation. Only the one routed page per adapt
  is ever rendered.
* **Memory from the new upscale is small.** It only triggers on banners
  whose median line height is under 18px, and only at 2–3x. Peak is a
  1702x2944 RGB buffer (~15 MB), transient.

## 5. Behaviour on Cloud vs your local machine

Identical. Your screenshots show *"PaddleOCR not installed/available; used
Tesseract instead"*, and Cloud will be the same, so the OCR results you
verified locally are the results you get live. All of the fixes — the
small-type upscale, `_core_line_height`, the multi-PSM `Dear` anchor, the
debris filter — were measured against Tesseract output specifically.

Do **not** add `paddleocr` / `paddlepaddle` to `requirements.txt` for the
Cloud deploy. Between wheels and first-use model downloads they will
exhaust the container, and it would silently switch the OCR engine out from
under the thresholds that were tuned on Tesseract.

## 6. Python version

Community Cloud defaults change over time. Set it explicitly to **3.12** in
*Advanced settings* when you create the app (or leave the included
`.python-version` file in place). `pymupdf`, `opencv-python-headless` and
`scikit-image` all publish 3.12 wheels; on 3.13/3.14 you can end up waiting
on a source build that will time out.

## 7. First-run smoke test

1. Upload the dealer-panel `.xlsx` and confirm *"Loaded N dealer row(s)"*.
2. Upload the bulletin PDF and confirm the routing table lists all ten
   adapts (`X7.zip → PDF page 68`, `i7.zip → PDF page 77`, and so on).
3. Open the **X1** and **THE i7** Advanced QA → Banner QA cards.
   Headline should be **Pass** on both. If the Advanced QA note says
   *"PaddleOCR not installed/available; used Tesseract instead"* and the
   Headline row is nevertheless Pass, the apt packages installed correctly.
4. If instead you see a `TesseractNotFoundError`, `packages.txt` did not
   take — check the build log for `E: Unable to locate package`.

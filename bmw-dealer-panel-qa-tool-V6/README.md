# BMW Dealer Panel QA Tool — Extended

Your original `app.py` behaviour is **100% unchanged**. Everything below is
new, optional, and lives in `modules/` — nothing in your existing code was
rewritten or removed.

## Install

```bash
pip install -r requirements.txt
```

No admin/root password is required for any of this — `pip install` installs
into your own Python environment, exactly like your existing packages.

### About PaddleOCR
- Install it once (`pip install paddleocr paddlepaddle`).
- The **first time** you actually run an OCR check, PaddleOCR downloads its
  detection/recognition models to a local cache folder (`~/.paddleocr`).
  This is the *only* moment it needs internet.
- After that one-time download, it runs **fully offline**, and is faster /
  more accurate / lower-RAM than Tesseract for this kind of banner text.
- If PaddleOCR isn't installed, or the model download hasn't happened yet
  (e.g. fully air-gapped machine), the app **automatically falls back to
  Tesseract** — no crash, no manual switch needed. You can also force
  "Tesseract only" from the sidebar.

### Poppler (for Master PDF support)
`pdf2image` needs the `poppler` binaries on your system PATH:
- **macOS:** `brew install poppler`
- **Windows:** download poppler binaries and add the `bin/` folder to PATH
- If poppler isn't installed, the Master PDF feature shows a clear error —
  everything else in the app keeps working.

## Running

```bash
streamlit run app.py
```

## What's new (all optional, all off by default)

1. **Excel Sheet Selection** — pick any sheet from the workbook instead of
   relying on auto-detected "Mailers - NSC ". Leave on auto-detect to keep
   old behaviour exactly.
2. **Dealer Selection dropdown** — pick a dealer explicitly; becomes the
   master dealer for Dealer Panel QA (skips HTML auto-detection).
3. **Dealer Name Validation** — opt-in checkboxes to verify the dealer name
   appears in the Banner and/or Body.
4. **Manual Text Mode** — type Headline / Subheadline / Dealer Name / Body
   Text directly; if any field is filled, it becomes the top-priority
   Master and disables Dealer Dropdown / Master JPG / PDF / HTML uploads.
5. **Master JPG** — upload a full email screenshot; auto-crops from the top
   down to the "Dear" salutation (via OCR) to isolate the banner.
6. **Master PDF** — same crop logic, with an optional page number or
   automatic "Dear"-page detection.
7. **Master HTML ZIP** — point at a master email's HTML+images zip; the
   banner `<img>` is located and extracted automatically.
8. **Banner Detection** — shared logic that finds the first genuine banner
   image (not a logo/icon) in any HTML, and pulls it from a zip.
9. **Banner Visual Comparison** — OpenCV SSIM + ORB alignment + red-box
   difference highlighting, with Master / Input / Diff / Overlay images.
10. **OCR Text Extraction** — PaddleOCR-preferred with Tesseract fallback,
    banner-only (never OCRs the whole email).
11. **Banner Text QA** — compares Headline/Subheadline/Dealer Name against
    OCR'd banner text, flags missing/extra words.
12. **Body QA (dealer name)** — opt-in dealer-in-body check.
13. **Manual Body Comparison** — As Is / To Be vs the live HTML body, with
    Added/Removed/Modified highlighting.
14. **Priority engine** — Manual Text > Master JPG > Master PDF > Master
    HTML ZIP > Dealer Dropdown > Excel. Only the single highest-priority
    active source is ever used; sources are never combined.
15. **Tabbed results** — Dealer Panel QA / Body QA / Banner QA / Visual QA /
    OCR QA / Summary, each with Pass/Fail/Warn plus images and detail.
16. **Dealer Website Link QA (V6)** — verifies the CTA button's `href`
    AND the Dealer Panel's own "Website: ..." line both belong to the
    correct dealer's domain (derived from the dealer's own name, since
    there's no dedicated Website column in Excel), and that the two agree
    with each other. Uses the dropdown-selected dealer if one is chosen,
    otherwise the auto-detected dealer — same resolution order as the
    rest of Dealer Panel QA. Domain-matched (not exact-URL), so a CTA
    button linking to a deep page like
    `https://www.bmw-birdautomotive.in/new-cars/bmw-iX1` still correctly
    passes against a panel website of `www.bmw-birdautomotive.in`. Three
    rows are added directly below the existing "Website: ..." row in the
    Content QA table: Dealer Panel Website vs dealer name, CTA Button
    Link vs dealer name, and CTA Button Link vs Dealer Panel Website.

To use the new tabs, tick **"Enable Advanced QA tabs for this run"** at the
bottom of the "Advanced QA options" sidebar section. If left unticked, the
app runs exactly as it did before this update.

## Architecture

```
app.py                      <- your original file, only additive edits
modules/
  config.py                 <- every threshold/constant lives here (no hardcoding elsewhere)
  results.py                <- shared QAItem / ModuleResult (Pass/Fail/Warn) types
  excel_loader.py            (1) sheet selection
  dealer_select.py            (2)(3) dealer dropdown + dealer-name validation
  manual_mode.py              (4) manual text master
  master_image.py             (5) JPG -> crop-to-"Dear"
  master_pdf.py                (6) PDF page select + crop-to-"Dear"
  master_html_zip.py            (7) master HTML+zip -> banner
  banner_detect.py               (8) generic banner locator (shared)
  banner_compare.py               (9) SSIM + ORB + diff overlay
  ocr_engine.py                    (10) PaddleOCR w/ Tesseract fallback
  banner_text_qa.py                 (11) banner text word-diff QA
  body_qa.py                         (12)(13) body dealer check + As-Is/To-Be diff
  priority.py                         (14) master-source priority resolver
  results_ui.py                        (15) shared Streamlit rendering for tabs
  website_link_qa.py                    (16) CTA + dealer panel website domain QA
```

Everything runs locally: OpenCV, scikit-image, Pillow, pdf2image,
BeautifulSoup, pandas, and (Paddle)OCR. No network calls, no cloud APIs,
Windows/macOS compatible.

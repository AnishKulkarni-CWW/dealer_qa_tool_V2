# Banner Text QA — why some models detected Headline / Subheadline / Dealer
# correctly and others did not, and what was changed

Everything below was reproduced locally against your own inputs: the July
Sales Push bulletin PDF, the `Bird Automotive` adapts, and Tesseract 5.3.4
(PaddleOCR is not installed on the machine that produced the screenshots —
every Advanced QA card says *"PaddleOCR not installed/available; used
Tesseract instead"*).

Four files changed. **`app.py` is untouched** — every function signature is
the same, so drop these four in and the app picks the fixes up.

---

## 1. X7 — `Warn | Missing word(s): MORE`

`ocr_engine._filter_line_words()` was deleting **real words from a line's
text**. Raw Tesseract output for the X1 banner:

```
YOU(h26,conf88) MISS(h26,96) THE(h26,96) SHOTS(h26,96) YOU(h26,97)
DON'T(h59,94) TAKE.(h59,25)
```

* the confidence pass dropped `TAKE.` (25 < `MIN_WORD_CONFIDENCE` 35)
* the height-outlier pass then dropped `DON'T` (59 > 1.8 x median 26)

so the line's text became `"YOU MISS THE SHOTS YOU"`. Meanwhile
`extract_text()` never ran those filters, which is exactly why your Dealer
Name row showed the full `ALL-IN,NO MORE EXCUSES.` while the Headline row
was missing a word. The two code paths openly disagreed.

Those filters exist to stop a logo box **inflating a line's measured font
height**. They should never have decided the line's text.

**Fix** — measuring and reading are now separate. `_measurement_words()`
picks the subset used to size the type; the line keeps every word it OCR'd.
`extract_text()` and `extract_lines()` now share one word-box pipeline, so
the flat blob and the per-field text can no longer contradict each other.

---

## 2. X1 — `Fail | Missing: DON, T, TAKE; extra: MISS, THE, SHOTS`

The X1 master (PDF page 41) OCRs as:

```
YOU(19) MISS(19) THE(18) SHOTS(19)   -> line measured 19px
YOU(19) DON'T(33) TAKE.(33)          -> line measured 33px
DRIVE ... ROAD TAX.(13-14)           -> line measured 14px
```

One apostrophe inflates `DON'T`'s bounding box to 33px. Because a line's
size was `max(bottom) - min(top)`, two visual lines of the *same* headline
measured 74% apart, so font-size banding put them in different bands:

| | was | now |
|---|---|---|
| expected Headline | `YOU DON'T TAKE.` | `YOU MISS THE SHOTS YOU DON'T TAKE.` |
| expected Subheadline | `YOU MISS THE SHOTS` | `DRIVE YOUR MATCH WITH BENEFITS OF 50%* ROAD TAX.` |

Every X1 dealer mailer was then checked against a headline that was never
the headline.

**Fix** — `_core_line_height()` measures a line as its **smallest** word
box (ignoring subscript debris) instead of its overall extent. Inflation
only ever makes a box taller, so the smallest box is the closest estimate
of real cap height — and it is the same estimate for a line with an
apostrophe as for one without.

This also silently fixed **X5**, which had the identical defect and was
splitting `QUIT PLAYING GAMES WITH YOUR HEART.` across two bands.

---

## 3. THE 7 — `Warn | No expected value provided for this field — skipped`

`crop_banner_top_to_dear()` could not find "Dear" on PDF page 75, fell back
to the blind 35% crop, and **cut the banner text off entirely**. The master
produced zero OCR lines, so Headline and Subheadline had no expected value
at all — and the report blamed the user for not filling something in.

The word is right there in the image. It is a Tesseract page-segmentation
quirk: the default PSM 3 returns four words for the whole 851x1472 creative
and misses it. `--psm 6` finds `Dear` at y=652, confidence 97.

**Fix** — three changes in `master_image.py`:

* the anchor is hunted across PSM 3 / 6 / 11, then again on a 2x upscale
* a one-character OCR slip on the anchor word is tolerated
* if the anchor is still missed, the fallback crop is extended in 5% steps
  (ceiling 60%) only until it actually contains text, instead of handing
  back a photograph

Plus a note in `banner_text_qa` so "master gave nothing" never again reads
like "you forgot to fill this in".

---

## 4. THE i7 — `Warn | Missing word(s): THEI7`

Pure tokenisation mismatch. The master read the badge line as one token
`THEI7` (confidence 17); the email read it as `THE` + `I7`. Bag-of-words
comparison saw zero overlap, so the line was not even attributed to the
Headline field — it landed in `unmatched_lines` and the FOUND column showed
only `BAYERISCHE MOTOREN WERKE`.

**Two fixes, both needed:**

* **Auto-upscale.** These badge lines render at 10-11px. Below
  `OCR_MIN_TEXT_HEIGHT_PX` (18) the image is re-OCR'd enlarged and every
  coordinate divided back down. The i7 master then reads `THE` + `i7` at
  confidence 78 — matching the email exactly — and the "THE?" misread on
  page 75 becomes `THE 7`. The scale decision uses the median of the
  **lines'** sizes, not of word heights: a per-word median is dominated by
  whichever line has the most words, which had a 9-word legal strapline
  outvoting a 5-word headline and triggering upscales that were not needed.
* **`spacing_tolerant_match()`.** Reconciles OCR word split/merge across
  *consecutive* tokens, and nothing else — `THE` + `I7` == `THEI7` is
  accepted, `NO` inside `NOTHING` is not. Verified that real defects still
  fail: `NO MORE EXCUSES` vs `NO EXCUSES` still reports `missing: more`,
  `i7` vs `i8` still fails, `29,999` vs `39,999` still fails.

---

## 5. All four models — `Fail | Dealer Name`

These banners genuinely carry no dealer name; the dealer block is in the
email footer. When content matching found nothing, the fallback chain
compared `Bird Automotive` against the **entire banner blob**, producing a
guaranteed Fail plus:

```
Unexpected/extra word(s) nearby: ALL, IN, NO, MORE, EXCUSES, DRIVE, YOUR,
MATCH, WITH, SMART
Found: ALL-IN,NO MORE EXCUSES.  DRIVE YOUR MATCH WITH SMART OWNERSHIP...
```

on every single adapt — while duplicating the "Dealer exists in Banner"
check you already have switched on.

**Fix** — the whole-blob fallback for Dealer Name is gone, and the band
fallback now demands a line that actually *looks* like a dealer name.
`_dealer_field_status()` gives three honest outcomes: a matched line gets a
normal word diff; a name present in the banner text but not on its own line
gets a Warn saying so; a name that is nowhere on the banner gets one clear
sentence and an **empty** Found column.

Default severity for "no dealer line on the banner" is **Warn**. If your
templates really are supposed to render it on the artwork, flip one line:

```python
# config.py
banner_dealer_name_missing_is_fail: bool = True
```

---

## Bonus fix you had not reported yet

The X3 master was picking up `eet =e See` (confidences 0 / 47 / 36) read out
of a reflection in the photograph. Because a scrap like that becomes a
`TextLine` with a font height of its own, banding will happily hand it a
band — a reflection can become the expected Subheadline for every dealer
version of a campaign.

`_drop_debris_lines()` removes a line only when it is **both** short and
unsure **and** not left-aligned with the banner's real copy. Alignment is
what makes this safe: on the THE 7 creative the badge line comes back at
confidence 0 for both words but starts at x=51.5 against x=52.0 for the
strapline beneath it, so it is kept; the X3 scrap starts at x=380 against
x=118 for the real copy, so it goes. If a banner has no confident line at
all, nothing is dropped — a hard-to-read banner must never come back empty.

---

## Regression check — all 10 master pages in your deck

| Adapt | Result |
|---|---|
| X7 (p68) | unchanged, correct |
| **X1 (p41)** | **fixed** — headline no longer split |
| **X5 (p59)** | **fixed** — headline no longer split |
| 5LWB (p23) | unchanged, correct |
| **THE 7 (p75)** | **fixed** — was empty, now `THE 7 BAYERISCHE MOTOREN WERKE` |
| 2GC (p5) | unchanged, correct |
| 3LWB (p14) | unchanged, correct |
| iX1 (p32) | unchanged, correct |
| **THE i7 (p77)** | **fixed** — `THEI7` now reads `THE i7` |
| **X3 (p50)** | **fixed** — reflection scrap no longer pollutes the subheadline |

Five fixed, five untouched, none broken.

## End-to-end result on the four adapts you reported

| Adapt | Headline | Subheadline | Dealer Name |
|---|---|---|---|
| X7 | Pass | Pass | Warn (no dealer line on banner) |
| X1 | Pass | Pass | Warn (no dealer line on banner) |
| THE 7 | Pass | Warn (master has none) | Warn (no dealer line on banner) |
| THE i7 | Pass | Warn (master has none) | Warn (no dealer line on banner) |

## New tuning knobs (all documented in place, nothing hardcoded)

`ocr_engine.py` — `OCR_MIN_TEXT_HEIGHT_PX`, `OCR_TARGET_TEXT_HEIGHT_PX`,
`OCR_MAX_UPSCALE`, `CORE_HEIGHT_MIN_RATIO`, `JITTER_TOLERANCE_MIN_PX`,
`DEBRIS_LINE_MAX_CHARS`, `DEBRIS_LINE_MAX_CONFIDENCE`,
`DEBRIS_ALIGN_TOLERANCE_RATIO`

`config.py` — `crop_anchor_fallback_max_ratio`,
`crop_anchor_fallback_step_ratio`, `banner_dealer_name_missing_is_fail`

## One thing worth knowing

The upscale costs a second Tesseract pass on small-type banners only, and
both `extract_text()` and `extract_lines()` now share one pipeline, so the
call count per banner is unchanged in practice. If you ever install
PaddleOCR, the Paddle path is untouched by all of this — these fixes are on
the Tesseract path, which is the one your machine is actually using.

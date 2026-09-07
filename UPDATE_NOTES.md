# READ THIS FIRST — why Headline / Subheadline / Dealer Name were blank

**Your machine has no OCR engine installed.** That is the whole cause.

Banner text exists only as pixels — it is not in the email HTML and not as
selectable text in the PDF — so those three checks depend entirely on OCR.
With no engine, `extract_clustered_text()` returned zero lines, both the
Master and the adapt produced empty text, and Banner Text QA printed
"No expected value provided for this field — skipped". That message reads
like the Master was empty, when in fact the tool simply could not look at
it. Your screenshot's note — "engine detected 0 headline-band line(s),
0 subheadline-band line(s)" — is that exact condition.

I ran **your actual files** through the unmodified pipeline here:

| | Detected |
|---|---|
| Master JPG (`P_2013650_...Infinity...png`) | Headline `ENGINEERED TO DELIVER OPTIMAL PERFORMANCE EVERY DAY.` · Subheadline `BMW FUEL ADDITIVES.` · Dealer `Infinity Cars` |
| Adapt (`index.html` + `images/header.jpg`) | Headline `ENGINEERED TO DELIVER OPTIMAL PERFORMANCE EVERY DAY.` · Subheadline `BMW FUEL ADDITIVES.` · Dealer `Bavaria Motors` |
| Banner Text QA | **Headline Pass · Subheadline Pass · Dealer Name Pass** |

Nothing in the logic is broken. It needs an engine to read with.

## Fix — install Tesseract (5 minutes, recommended)

1. Download from <https://github.com/UB-Mannheim/tesseract/wiki>
2. Install with the defaults.
3. Restart the app.

No PATH editing needed: `ocr_engine._configure_tesseract_path_if_needed()`
already checks `C:\Program Files\Tesseract-OCR\`, the x86 folder and
both `%LOCALAPPDATA%` locations. Tesseract gives correct word spacing,
which is what produced the three Passes above.

## Or, with no admin rights

`pip install rapidocr-onnxruntime` — models ship inside the wheel, so
there is nothing to install system-wide. It is a genuine fallback rather
than an equal: it merges words on tight display type ("BavariaMotors"),
so use it only if you cannot install Tesseract.

## What changed in the code

Two files, both narrowly:

**`modules/ocr_engine.py`** — added the RapidOCR engine as a last-resort
fallback and an `ocr_status()` helper. It is reached only when PaddleOCR
*and* Tesseract have both already failed — the exact path that previously
returned nothing. `cluster_lines_by_size()`, `extract_clustered_text()`,
`find_dealer_line()`, `_lines_with_tesseract()` and `_lines_with_paddle()`
are all verified **byte-identical** to your originals. The filters that
corrupted the banding in the previous build are gone and have not
returned.

**`modules/banner_text_qa.py`** — added `space_insensitive`, defaulting to
**False**, so comparison is exactly as strict as it always was. app.py
switches it on only when the RapidOCR fallback actually ran, so a real
spacing defect is still caught on a Tesseract machine.

**`app.py`** — Advanced QA now shows a red error naming the missing engine
and how to install it, instead of leaving you with silent blank values.

The other 13 QA modules remain byte-identical to what you sent.

---

# Update 2 — Colourful layout restored, grouped results, Banner QA fixed

Everything below is on top of the previous multi-adapt update. Your
fifteen original QA modules are still **byte-for-byte identical** to what
you sent — no QA logic, threshold, matching rule or priority order has
been touched in either round.

---

## First: the import crash is fixed

Last time the zip assumed you would unzip **over** your existing project.
You extracted it standalone, so `modules/website_link_qa.py` was missing
and the app died on startup. That is my fault and it is now handled
properly:

* `app.py` imports that module defensively. The app boots cleanly with or
  without it — verified both ways, zero exceptions each.
* If it is missing you get a **Warn row in Content QA** naming the exact
  file to copy and from where, instead of a stack trace that kills every
  other check. A missing module can never be mistaken for a clean pass.

**Still worth copying it in.** The three Dealer Website / CTA Button Link
checks only run when the real module is present:

```
copy "<your-old-project>\modules\website_link_qa.py" "<this-folder>\modules\"
```

---

## 1. The colourful layout is back

Pastel cards, heavy dark borders, rounded corners, white pill labels with
a coloured dot — as it was. The two cards added by the multi-adapt work
were given their own colours from the same palette so they sit alongside
the originals rather than looking bolted on:

| Card | Colour |
|---|---|
| Excel & Mode, Content QA | lavender |
| Email Input | sky |
| Dealer Name Validation, Exact Match QA | lavender |
| Styling QA | amber |
| Manual Text Mode, Master Image, Advanced QA | mint |
| Manual Body Comparison, Master PDF | pink |
| Master HTML (ZIP) | yellow |
| **Master PDF — Emailer Routing** | **peach** (new) |
| **Per-Adapt Masters** | **periwinkle** (new) |
| Per-email job header | slate |
| Consolidated Excel report | green |

---

## 2 + 8. The per-adapt dropdown is gone

The dropdown was worse than it looked. An adapt whose slots had never
been **displayed** had never had its widgets instantiated, so whatever you
had typed for it could silently fall back to the global master — you
effectively had to walk the dropdown top to bottom before pressing Run QA
for every adapt to be checked against its own master. It also risked
losing text on the way out, because Streamlit discards the state of any
widget it did not render on the latest run, and switching the dropdown
re-renders a *different* adapt's widgets in the same pass.

Every adapt now gets its own expander, all rendered on every run. That
removes both problems by construction: every widget exists every time, so
every value is committed to the store every time, and nothing depends on
which adapt you happened to look at last. The expanders start closed, so
the page is no longer than the dropdown version was.

Headers read **"Master for i7.zip"** rather than just the file name,
because the uploaded-file chips and the overview table also show the bare
name and it was unclear which one opened the master slots.

Verified in a real browser: typed a headline into i7, typed a different
one into X3, pressed Run QA **once** — both were applied.

---

## 3. Clear Masters

Sits next to Run QA in the sticky bar. Wipes every Master JPG / PDF /
HTML ZIP and all typed Master text, global and per-adapt together.

`st.file_uploader` has no supported way to be emptied from code —
assigning `None` to its session-state entry raises — so the button bumps
a nonce that is appended to every master widget key. Streamlit sees a new
key and hands back a fresh, empty widget.

---

## 4. Results grouped into collapsible sections

Each email collapses into its own group: `1. i7.zip`, `2. X3.zip`,
`3. iX1.zip` — closed by default so you open them one at a time.

This needed one change underneath: the "Passed (n) — click to view"
disclosure was an `st.expander`, and Streamlit refuses to nest one
expander inside another, so wrapping a job's results would have raised
`StreamlitAPIException`. That disclosure is now a button plus a
session-state flag — same closed-by-default behaviour, no nesting limit,
and it does not render the hidden rows at all until asked.

Group bodies still **execute** when collapsed (Streamlit only hides them
visually), so the consolidated Excel report is always complete regardless
of which groups happen to be open.

---

## 5. Banner QA now runs from a model-folder .zip

**Root cause:** `extract_model_zip()` returned `(html, {name: size})`.
The size map is all the 300KB check needs, so the zip itself was being
thrown away — Banner QA never had any pixels to work with, which is why
it kept asking for "an images .zip" even though `images/` was sitting
right there inside the model folder you had already uploaded.

The raw zip bytes now travel with the job alongside the size map, so
Banner QA reads the real banner straight out of `images/`. The 300KB
check is completely unchanged. Bytes are re-wrapped in a fresh buffer per
email because `zipfile` consumes the stream and several jobs read from it
in one run.

This works against whichever master is in play — Master PDF (including a
per-model routed page), Master JPG, Master HTML ZIP or Manual Text —
since the master side of the comparison was already resolved per adapt.

Confirmed live against your bulletin: Banner Text QA ran for i7 against
page 77 with real OCR output, instead of the "No input banner image
available" message.

---

## 6 + 7. Sticky action bar, and the overlap fixed

Run QA and Clear Masters are pinned in a sticky bar below Streamlit's
toolbar, so Run QA stays reachable however far down a long report you are.

The overlap you spotted was my own doing: I had set the content column's
`padding-top` to `1rem`, well under the ~60px Streamlit toolbar, so the
hero card sat underneath it at the topmost scroll position. Padding is
now `4.75rem` (76px) and the sticky bar uses a matching `top` offset.
Measured in the browser: hero top 96px, toolbar bottom 60px — clear.

---

## 9. Testing

| Suite | Result |
|---|---|
| Mock-Streamlit end-to-end (4 scenarios) | 20 / 20 |
| Per-adapt Master HTML ZIP | 7 / 7 |
| Browser: theme, sticky bar, grouping, Banner QA | 10 / 10 |
| Browser: per-adapt persistence + Clear Masters | 4 / 4 |
| Streamlit `AppTest`, with website_link_qa.py | 0 exceptions |
| Streamlit `AppTest`, without website_link_qa.py | 0 exceptions |
| Real Chromium, full workflow | 0 JS errors |

**41 passing.** Regression checks still green from round one: the
punctuation false positive stays fixed, all three adapts still route to
their own EMAILER page (i7 → p77, X3 → p50, iX1 → p32), a single adapt
with no masters behaves exactly as before, and an adapt with no override
still falls back to the global master.

---

## Install

```
pip install -r requirements.txt
streamlit run app.py
```

`config.toml` and `.streamlit/config.toml` both carry a `[theme]` block —
your `[server]` settings (5 GB limits, XSRF) are unchanged. `primaryColor`
is now `#4F46E5` to match the restored palette; that is what keeps the
selected radio button from rendering in Streamlit's default red.

## Changed / new files

| File | Status |
|---|---|
| `app.py` | modified |
| `modules/theme.py` | colourful palette + sticky bar |
| `modules/results_ui.py` | non-nesting Pass disclosure |
| `modules/multi_master.py` | per-adapt expanders, clear nonce |
| `modules/master_pdf_multi.py` | unchanged from round one |
| `config.toml`, `.streamlit/config.toml` | `[theme]` block |
| `modules/website_link_qa.py` | **not included — copy yours in** |
| all 15 other `modules/*.py` | byte-identical to your originals |

---
---

# Update 3 — Header-bar buttons, instant dropdowns

## Correction: the banner OCR changes were reverted

An earlier version of this update added a "model badge" filter and a
licence-plate filter to `modules/ocr_engine.py`, plus whitespace-tolerant
word matching to `modules/banner_text_qa.py`. Those were wrong. They
changed the font-size clustering for every machine — including ones where
Headline / Subheadline / Dealer Name were already being detected
correctly — and corrupted the Advanced Banner QA output.

**Both files are now restored byte-for-byte to your originals.** All 15
of the original QA modules are byte-identical again, verified with
`diff`. `rapidocr-onnxruntime` has been removed from `requirements.txt`.

The banner logic in the multi-adapt path is your original single-QA
logic. Verified by diffing the two code paths after normalising for the
extra indentation of the per-email group:

* input-banner OCR + clustering block — **identical**
* `run_banner_text_qa()` call — **identical**
* master-derived Headline / Subheadline / Dealer Name block — identical
  except `ext_manual_master` → `job_manual_master`
* expected-value + dealer-priority block — identical except
  `ext_manual_master` → `job_manual_master` and
  `ext_body_to_be` → `job_body_to_be`

Those two substitutions are the entire point of the multi work: each
adapt uses its own Master when one is set, and falls back to the global
Master otherwise, so a single-adapt run behaves exactly as it always did.

Confirmed against your bulletin with Tesseract, per model:

| Model | Expected Headline | Expected Subheadline |
|---|---|---|
| 2GC | TAKE THE IF OUT OF IYKYK. | DRIVE YOUR MATCH. |
| 3LWB | LET'S SKIP TO THE GOOD PART. | DRIVE YOUR MATCH. |
| 5LWB | ALL-IN, NO MORE EXCUSES. | DRIVE YOUR MATCH WITH SMART... |
| iX1 LWB | DOMINATE EVERYDAY. YOUR WAY. | DRIVE YOUR MATCH. |

---


## 1. Run QA and Clear Masters moved onto the toolbar

Both buttons now sit on Streamlit's own top strip, to the left of Deploy,
instead of in a bar that scrolled with the page. They are `position:
fixed`, so they take no vertical space, and the bar stops short of the
Deploy button so the two never collide. Verified by measurement in a real
browser: bar occupies y 9–57px inside the 0–60px toolbar, right edge
1416px against Deploy's left edge at 1492px.

## 3. Pass/Present rows are a real dropdown

"Passed (13) — click to view" was a Streamlit button, which round-tripped
to the server and re-ran the whole script just to reveal rows that were
already computed — hence the reload flash on every click. It is now a
native HTML `<details>` element: the browser opens it, instantly, with no
rerun. It also has no nesting restriction, which is why the button
existed in the first place.

## Testing

20 / 20 and 7 / 7 on the mock suites, 0 exceptions under Streamlit's
`AppTest`, and 6 / 6 in the browser covering toolbar placement, Deploy
collision, native dropdown behaviour, and zero "No expected value
provided" rows remaining.

## Note on modules

All 15 of your original QA modules are byte-identical to what you sent.
`ocr_engine.py` and `banner_text_qa.py` were changed in an earlier draft
of this update and have been fully reverted.

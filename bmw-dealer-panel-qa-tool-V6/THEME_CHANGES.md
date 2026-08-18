# UI Theme Update — What Changed

This update applies a professional SaaS/Startup visual theme to the Dealer
Panel QA Tool. It is a **visual-only change**. No QA logic, matching rule,
threshold, priority order, or data flow was touched.

## Files changed

| File | What changed |
|---|---|
| `app.py` | 3 additions only: one import line, the old bare CSS block replaced with `theme.inject()`, and `st.title()`/`st.caption()` replaced with `theme.render_hero()`. Every other line (1,790+ lines of matching, Excel-parsing, HTML-parsing, and QA logic) is untouched. |
| `modules/theme.py` | **New file.** The entire design system lives here: colors, fonts, card styles, button styles, table styles. Nothing else in the app imports from or depends on this file except the 2 calls in `app.py`. |
| `modules/results_ui.py` | Only the color values changed (hardcoded hex → theme CSS classes). Every function's logic, arguments, and return behavior is byte-for-byte identical to before. |
| All other files in `modules/` | **Completely unchanged** — not even re-saved. `config.py`, `priority.py`, `dealer_select.py`, `manual_mode.py`, `master_image.py`, `master_pdf.py`, `master_html_zip.py`, `banner_detect.py`, `banner_compare.py`, `ocr_engine.py`, `banner_text_qa.py`, `body_qa.py`, `excel_loader.py`, `excel_report.py`, `results.py` are byte-for-byte identical to your originals. |

## Why this approach

Streamlit apps generate plain HTML with stable `data-testid` attributes on
every widget (buttons, file uploaders, sidebars, tables, etc.). The theme
works by injecting one CSS block that re-styles those existing elements —
it never replaces a widget, changes what a function returns, or alters
`session_state` behavior. This is the same technique used by professional
Streamlit theming (Microsoft's own `Streamlit_UI_Template` repo, for
example, uses the identical `st.markdown(f'<style>{css}</style>',
unsafe_allow_html=True)` pattern).

## What the theme looks like

- **Background:** cool slate-white (`#F8FAFC`), not stark white or a
  gradient — standard SaaS dashboard convention.
- **Accent color:** indigo (`#4F46E5`) — used for the primary "Run QA"
  button, active tabs, focused inputs, and the selected radio/checkbox
  state.
- **Pass / Warn / Fail:** every results table row now gets a colored left
  accent bar (green / amber / red) plus a soft tinted background, so a
  reviewer can scan a long table and immediately spot what needs
  attention — this replaces the old flat white-background table.
- **Cards:** the sidebar, file uploaders, metrics (Total/Present/Missing,
  Passed/Warnings/Failed), and the results tables are all now bordered,
  shadowed cards instead of Streamlit's default flat appearance.
- **Hero banner:** the top of the page now shows a branded header card
  with an eyebrow label, title, subtitle, and a "BMW · MINI" badge,
  replacing the plain `st.title()` text.

## One thing to know if you upgrade Streamlit later

A small number of CSS rules in `modules/theme.py` (specifically the radio
button's selected-state color, documented inline with a comment) had to
target a couple of Streamlit's internal auto-generated class names
(`etak9234` / `etak9235`) as a fallback, alongside a more stable
structural selector. Auto-generated class names can change between
Streamlit versions. If a future Streamlit upgrade makes the selected
radio button look red again, that's the one spot to check — everything
else in the theme uses stable `data-testid` selectors that don't have
this risk.

## Verified before delivery

- Every file still parses as valid Python (checked with `ast.parse`).
- The app was actually booted with `streamlit run` and served a clean
  HTTP 200 with no server-side errors.
- Real test data (a dealer Excel sheet + an HTML email with a
  deliberately wrong phone number) was run through the live app to
  confirm the QA logic still produces correct Pass/Fail verdicts, and
  that the new styling renders correctly with real results — not just
  clean/empty screenshots.
- The "Expand" popup (`st.dialog`) was opened and confirmed to render
  correctly with the new table styling.

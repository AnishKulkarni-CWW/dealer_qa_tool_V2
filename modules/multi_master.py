"""
Multi-Adapt Master Assignment.

TERMINOLOGY (fixed across the whole tool)
-----------------------------------------
  MASTER — the approved reference artwork/copy we compare AGAINST
           (Master JPG, Master PDF, Master HTML ZIP, Manual Text).
  ADAPT  — the dealer email(s) being QA'd: the HTML file(s) or the
           model-folder .zip file(s) uploaded under "Email Input".

WHAT THIS SOLVES
----------------
Normal (non-advanced) QA already handled many adapts in one run, because
every adapt is compared against the same Excel sheet. Advanced QA did not:
it only ever had ONE global Master JPG / Master HTML ZIP / Manual Text
block, so uploading five adapts meant every one of them was checked
against a single master — which is only ever correct for one of them.

This module gives every adapt its own master slot:

    Master JPG        -> one per adapt   (this module)
    Master HTML ZIP   -> one per adapt   (this module)
    Manual Text       -> one per adapt   (this module)
    Manual Body       -> one per adapt   (this module)
    Master PDF        -> ONE shared PDF, auto-routed per adapt
                         (see master_pdf_multi.py — a single bulletin deck
                         already contains every model's emailer, so
                         uploading it once is enough)

WHY A SEPARATE STORE INSTEAD OF PLAIN WIDGET STATE
--------------------------------------------------
Only the currently-selected adapt's widgets are rendered, and Streamlit
discards the state of any widget that was not rendered on the latest run.
An uploaded file therefore cannot simply be left sitting in its uploader
and read back later. So the moment a file is uploaded it is copied into a
plain (non-widget) `st.session_state` dictionary keyed by adapt name, and
everything downstream reads that dictionary. Switching the dropdown back
and forth never loses an assignment, and text fields are seeded from the
same store so they survive the round trip too.

Every value here is an OVERRIDE. Any slot an adapt leaves empty falls
through to the global Master controls, so a run with one adapt behaves
exactly as it always has.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from io import BytesIO
from typing import Dict, List, Optional

import streamlit as st

_STORE_KEY = "ext_multi_master_store"


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------

@dataclass
class MasterAssignment:
    """Every per-adapt master override. All fields optional."""
    job_name: str = ""

    jpg_bytes: Optional[bytes] = None
    jpg_name: str = ""

    html_zip_bytes: Optional[bytes] = None
    html_zip_name: str = ""

    headline: str = ""
    subheadline: str = ""
    dealer_name: str = ""
    body_text: str = ""

    body_as_is: str = ""
    body_to_be: str = ""

    # Master PDF: which EMAILER page of the shared deck this adapt uses.
    # 0 / None means "let master_pdf_multi auto-route it".
    pdf_page: int = 0
    pdf_page_source: str = "auto"   # "auto" | "manual"

    # -- convenience -------------------------------------------------------
    def jpg_file(self) -> Optional[BytesIO]:
        """A fresh file-like object every call, so repeated reads across
        several adapts in the same run can never hit an exhausted stream."""
        return BytesIO(self.jpg_bytes) if self.jpg_bytes else None

    def html_zip_file(self) -> Optional[BytesIO]:
        return BytesIO(self.html_zip_bytes) if self.html_zip_bytes else None

    def has_text(self) -> bool:
        return any([
            self.headline.strip(), self.subheadline.strip(),
            self.dealer_name.strip(), self.body_text.strip(),
        ])

    def has_body(self) -> bool:
        return bool(self.body_as_is.strip() or self.body_to_be.strip())

    def has_any(self) -> bool:
        return bool(
            self.jpg_bytes or self.html_zip_bytes
            or self.has_text() or self.has_body() or self.pdf_page
        )

    def summary_bits(self) -> List[str]:
        bits = []
        if self.jpg_bytes:
            bits.append(f"JPG: {self.jpg_name}")
        if self.html_zip_bytes:
            bits.append(f"HTML ZIP: {self.html_zip_name}")
        if self.has_text():
            fields = [
                label for label, val in (
                    ("Headline", self.headline), ("Subheadline", self.subheadline),
                    ("Dealer Name", self.dealer_name), ("Body Text", self.body_text),
                ) if val.strip()
            ]
            bits.append("Text: " + ", ".join(fields))
        if self.has_body():
            bits.append("Manual Body")
        return bits


# --------------------------------------------------------------------------
# Store helpers
# --------------------------------------------------------------------------

def _store() -> Dict[str, MasterAssignment]:
    if _STORE_KEY not in st.session_state:
        st.session_state[_STORE_KEY] = {}
    return st.session_state[_STORE_KEY]


def get_assignment(job_name: str) -> MasterAssignment:
    store = _store()
    if job_name not in store:
        store[job_name] = MasterAssignment(job_name=job_name)
    return store[job_name]


def all_assignments() -> Dict[str, MasterAssignment]:
    return dict(_store())


def prune_to(job_names: List[str]) -> None:
    """Drop assignments for adapts that are no longer uploaded, so a stale
    master from a previous run can never silently attach itself to a new
    adapt that happens to reuse a filename."""
    store = _store()
    for name in list(store.keys()):
        if name not in job_names:
            del store[name]


def clear_all() -> None:
    st.session_state[_STORE_KEY] = {}


def _safe_key(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name or "")[:60]


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------

def render_panel(
    job_names: List[str],
    pdf_index=None,
    pdf_auto_map: Optional[dict] = None,
    nonce: int = 0,
) -> Dict[str, MasterAssignment]:
    """
    Renders one master block PER ADAPT and returns the full assignment map.

    WHY EVERY ADAPT IS RENDERED AT ONCE
    -----------------------------------
    This used to be a dropdown that showed a single adapt's master slots
    at a time. That turned out to be wrong in two ways that only show up
    on a real multi-model run:

      * It made the run order-dependent. An adapt whose slots had never
        been displayed had never had its widgets instantiated, so
        whatever you had typed for it could silently fall back to the
        global master. You effectively had to walk the dropdown top to
        bottom before pressing Run QA for every adapt to be checked
        against its own master.
      * It risked losing typed text on the way out. Streamlit discards
        the state of any widget it did not render on the latest run, and
        changing the dropdown re-renders a DIFFERENT adapt's widgets in
        the same pass - so a value typed but not yet committed could go
        with it.

    Rendering every adapt in its own expander removes both problems by
    construction: every widget exists on every run, so every value is
    committed to the store on every run and nothing depends on which
    adapt you happened to look at last. The expanders start closed, so
    the page is no longer than the dropdown version was.

    job_names   : the adapts currently uploaded, in upload order.
    pdf_index   : an `master_pdf_multi.EmailerIndex`, or None.
    pdf_auto_map: {job_name: (EmailerEntry|None, reason)} used to
                  preselect and explain each adapt's routed master page.
    nonce       : bumped by "Clear Masters" to hand every uploader a
                  fresh widget key (st.file_uploader cannot be emptied
                  from code any other way).
    """
    prune_to(job_names)

    if not job_names:
        st.info("Upload your adapt file(s) under **Email Input** first — a master slot will appear here for each one.")
        return {}

    st.caption(
        f"{len(job_names)} adapt(s) uploaded. Every adapt below keeps its own Master and is "
        "checked against it in the same run — you do not have to open them one at a time. "
        "Any slot left empty falls back to the global Master controls above."
    )

    for job_name in job_names:
        assignment = get_assignment(job_name)
        skey = f"{_safe_key(job_name)}_{nonce}"
        bits = assignment.summary_bits()
        # Prefixed so the header is unambiguous on screen: the uploaded
        # file chips and the overview table both also show the bare file
        # name, which made it unclear which one opened the master slots.
        label = f"Master for {job_name}" + (f"   —   {', '.join(bits)}" if bits else "")

        with st.expander(label, expanded=False):
            _render_one(assignment, skey, job_name, pdf_index, pdf_auto_map)

    # ---- Overview of every adapt ---------------------------------------
    st.markdown("**Master assignment overview**")
    rows = []
    for name in job_names:
        a = get_assignment(name)
        bits = a.summary_bits()
        if a.pdf_page:
            bits.insert(0, f"PDF page {a.pdf_page}"
                           f"{'' if a.pdf_page_source == 'auto' else ' (pinned)'}")
        rows.append({
            "Adapt": name,
            "Master assigned": ", ".join(bits) if bits else "— falls back to the global Master —",
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)

    return all_assignments()


def _render_one(assignment, skey, job_name, pdf_index, pdf_auto_map):
    """All master slots for a single adapt."""

    # ---- Master PDF page routing (shared deck, per-adapt page) ----------
    if pdf_index is not None and pdf_index.entries:
        auto_entry, auto_reason = (pdf_auto_map or {}).get(job_name, (None, ""))
        auto_label = "(auto-detect from the model name)"
        options = [auto_label] + pdf_index.options()

        current = 0
        if assignment.pdf_page_source == "manual" and assignment.pdf_page:
            for i, e in enumerate(pdf_index.entries):
                if e.page_number == assignment.pdf_page:
                    current = i + 1
                    break

        choice = st.selectbox(
            "Master PDF — emailer page for this adapt",
            options=options,
            index=current,
            key=f"ext_mm_pdfpage_{skey}",
            help="One bulletin PDF holds every model's emailer, so it only needs uploading once. "
                 "Leave on auto-detect unless a model was routed incorrectly.",
        )
        if choice == auto_label:
            assignment.pdf_page = auto_entry.page_number if auto_entry else 0
            assignment.pdf_page_source = "auto"
            if auto_entry:
                st.success(f"Auto-routed to **{auto_entry.model_label}** (page {auto_entry.page_number}).")
            elif auto_reason:
                st.warning(auto_reason)
        else:
            picked = pdf_index.from_option(choice)
            assignment.pdf_page = picked.page_number if picked else 0
            assignment.pdf_page_source = "manual"
            if picked:
                st.info(f"Manually pinned to **{picked.model_label}** (page {picked.page_number}).")

    # ---- Master JPG -----------------------------------------------------
    jpg_up = st.file_uploader(
        "Master JPG for this adapt", type=["jpg", "jpeg", "png"],
        key=f"ext_mm_jpg_{skey}",
    )
    if jpg_up is not None:
        assignment.jpg_bytes = jpg_up.getvalue()
        assignment.jpg_name = jpg_up.name
    if assignment.jpg_bytes:
        c1, c2 = st.columns([4, 1])
        c1.success(f"Master JPG assigned: **{assignment.jpg_name}**")
        if c2.button("Remove", key=f"ext_mm_jpg_clear_{skey}", use_container_width=True):
            assignment.jpg_bytes, assignment.jpg_name = None, ""
            st.rerun()

    # ---- Master HTML ZIP ------------------------------------------------
    zip_up = st.file_uploader(
        "Master HTML ZIP for this adapt", type=["zip"],
        key=f"ext_mm_zip_{skey}",
    )
    if zip_up is not None:
        assignment.html_zip_bytes = zip_up.getvalue()
        assignment.html_zip_name = zip_up.name
    if assignment.html_zip_bytes:
        c1, c2 = st.columns([4, 1])
        c1.success(f"Master HTML ZIP assigned: **{assignment.html_zip_name}**")
        if c2.button("Remove", key=f"ext_mm_zip_clear_{skey}", use_container_width=True):
            assignment.html_zip_bytes, assignment.html_zip_name = None, ""
            st.rerun()

    # ---- Manual Text ----------------------------------------------------
    st.markdown("**Manual Text Master for this adapt**")
    st.caption("Typed values always win for their own field; blank fields fall through to the Master JPG / PDF / HTML ZIP.")
    assignment.headline = st.text_input(
        "Headline", value=assignment.headline, key=f"ext_mm_hl_{skey}")
    assignment.subheadline = st.text_input(
        "Subheadline", value=assignment.subheadline, key=f"ext_mm_shl_{skey}")
    assignment.dealer_name = st.text_input(
        "Dealer Name", value=assignment.dealer_name, key=f"ext_mm_dn_{skey}")
    assignment.body_text = st.text_area(
        "Body Text", value=assignment.body_text, key=f"ext_mm_body_{skey}", height=90)

    # ---- Manual Body Comparison ----------------------------------------
    st.markdown("**Manual Body Comparison for this adapt**")
    bc1, bc2 = st.columns(2)
    with bc1:
        assignment.body_as_is = st.text_area(
            "As Is", value=assignment.body_as_is, key=f"ext_mm_asis_{skey}", height=80)
    with bc2:
        assignment.body_to_be = st.text_area(
            "To Be", value=assignment.body_to_be, key=f"ext_mm_tobe_{skey}", height=80)

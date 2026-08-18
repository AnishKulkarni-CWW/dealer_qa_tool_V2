"""
Feature 12 — Body QA (dealer-name-in-body, opt-in).
Feature 13 — Manual Body Comparison (As Is / To Be vs HTML body), with
word-level Added / Removed / Modified highlighting via difflib
(dependency-free, deterministic, offline).
"""

import difflib
import re
from dataclasses import dataclass
from typing import List, Tuple

from .dealer_select import validate_dealer_in_text
from .results import ModuleResult, PASS, FAIL, WARN


def run_body_dealer_qa(has_dealer_in_body_enabled: bool, dealer_name: str, body_text: str) -> ModuleResult:
    """Feature 12 — purely opt-in; skipped entirely if the toggle is off."""
    result = ModuleResult(module_name="Body QA — Dealer Name")
    if not has_dealer_in_body_enabled:
        result.notes.append("'Has Dealer Name in Body' check is disabled — skipped.")
        return result
    if not dealer_name:
        result.add("Body", "Dealer Name in Body", FAIL, detail="No dealer name available to check.")
        return result
    ok = validate_dealer_in_text(dealer_name, body_text or "")
    result.add(
        "Body", "Dealer Name in Body",
        PASS if ok else FAIL,
        detail=f"Dealer '{dealer_name}' {'found' if ok else 'NOT found'} in body text.",
        expected=dealer_name,
        found=(body_text or "")[:300],
    )
    return result


def _word_tokenize(text: str) -> List[str]:
    # Keep whitespace as tokens too, so rejoining preserves original spacing.
    return re.findall(r"\S+|\s+", text or "")


@dataclass
class WordOp:
    op: str          # "equal" | "insert" | "delete" | "replace"
    as_is_text: str
    to_be_text: str


def diff_as_is_to_be(as_is: str, to_be: str) -> List[WordOp]:
    a_tokens = _word_tokenize(as_is)
    b_tokens = _word_tokenize(to_be)
    sm = difflib.SequenceMatcher(a=a_tokens, b=b_tokens, autojunk=False)

    ops: List[WordOp] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        a_seg = "".join(a_tokens[i1:i2])
        b_seg = "".join(b_tokens[j1:j2])
        if tag == "equal":
            ops.append(WordOp("equal", a_seg, b_seg))
        elif tag == "insert":
            ops.append(WordOp("insert", "", b_seg))
        elif tag == "delete":
            ops.append(WordOp("delete", a_seg, ""))
        elif tag == "replace":
            ops.append(WordOp("replace", a_seg, b_seg))
    return ops


def render_diff_html(ops: List[WordOp]) -> str:
    """Small inline-HTML render for Streamlit's st.markdown(unsafe_allow_html=True)."""
    out = []
    for op in ops:
        if op.op == "equal":
            out.append(op.as_is_text)
        elif op.op == "insert":
            out.append(f'<span style="background-color:#d4f7d4;text-decoration:none;">{op.to_be_text}</span>')
        elif op.op == "delete":
            out.append(f'<span style="background-color:#fbd4d4;text-decoration:line-through;">{op.as_is_text}</span>')
        elif op.op == "replace":
            out.append(
                f'<span style="background-color:#fbd4d4;text-decoration:line-through;">{op.as_is_text}</span>'
                f'<span style="background-color:#fff3b0;">{op.to_be_text}</span>'
            )
    return "".join(out)


def run_manual_body_comparison(as_is: str, to_be: str, html_body_text: str) -> ModuleResult:
    """
    Feature 13. Compares `to_be` (what body copy should say) against
    `html_body_text` (what's actually in the HTML). `as_is` is what the
    user believes the current copy is — shown in the diff for reference,
    but the authoritative comparison target is the live HTML body text.
    """
    result = ModuleResult(module_name="Manual Body Comparison")

    if not to_be.strip():
        result.notes.append("No 'To Be' text provided — manual body comparison skipped.")
        return result

    ops_vs_html = diff_as_is_to_be(to_be, html_body_text or "")
    added = sum(1 for o in ops_vs_html if o.op == "insert")
    removed = sum(1 for o in ops_vs_html if o.op == "delete")
    modified = sum(1 for o in ops_vs_html if o.op == "replace")

    status = PASS if (added == 0 and removed == 0 and modified == 0) else FAIL
    detail = f"Added: {added}, Removed: {removed}, Modified: {modified} segment(s) vs. expected 'To Be' text."
    result.add("Body", "To Be vs HTML body", status, detail=detail)
    result.notes.append(render_diff_html(ops_vs_html))

    if as_is.strip():
        ops_as_is_vs_html = diff_as_is_to_be(as_is, html_body_text or "")
        a_added = sum(1 for o in ops_as_is_vs_html if o.op == "insert")
        a_removed = sum(1 for o in ops_as_is_vs_html if o.op == "delete")
        a_modified = sum(1 for o in ops_as_is_vs_html if o.op == "replace")
        result.add(
            "Body", "As Is vs HTML body", WARN,
            detail=f"Reference only — Added: {a_added}, Removed: {a_removed}, Modified: {a_modified}.",
        )
        result.notes.append(render_diff_html(ops_as_is_vs_html))

    return result

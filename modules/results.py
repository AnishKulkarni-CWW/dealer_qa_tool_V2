"""
Shared result types. Every comparison in every module must resolve to one
of these so the UI layer can render Pass/Fail/Warn consistently.
"""

from dataclasses import dataclass, field
from typing import Optional, List


PASS = "Pass"
FAIL = "Fail"
WARN = "Warn"


@dataclass
class QAItem:
    """A single check result."""
    category: str          # e.g. "Banner Text", "Dealer Name", "Body"
    rule: str               # short rule name
    status: str              # Pass / Fail / Warn
    detail: str = ""         # human-readable explanation
    expected: str = ""
    found: str = ""


@dataclass
class ImageArtifact:
    """A named image to display in the UI (as PNG bytes)."""
    label: str
    png_bytes: bytes


@dataclass
class ModuleResult:
    """Aggregated output of one QA module (e.g. Banner QA, Body QA)."""
    module_name: str
    items: List[QAItem] = field(default_factory=list)
    images: List[ImageArtifact] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def add(self, category: str, rule: str, status: str, detail: str = "",
            expected: str = "", found: str = "") -> None:
        self.items.append(QAItem(category, rule, status, detail, expected, found))

    def counts(self):
        p = sum(1 for i in self.items if i.status == PASS)
        f = sum(1 for i in self.items if i.status == FAIL)
        w = sum(1 for i in self.items if i.status == WARN)
        return p, f, w

    def overall_status(self) -> str:
        p, f, w = self.counts()
        if f > 0:
            return FAIL
        if w > 0:
            return WARN
        return PASS

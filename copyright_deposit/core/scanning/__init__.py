"""Pre-flight scanners.

A deposit becomes part of a public record that anyone may inspect, and a
registration may only claim material the applicant actually owns. These
scanners exist to catch both mistakes before the PDF is filed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"

_SEVERITY_ORDER = {SEVERITY_HIGH: 0, SEVERITY_MEDIUM: 1, SEVERITY_LOW: 2}


@dataclass
class Finding:
    id: str
    rel_path: str
    line_number: int
    rule: str
    detail: str
    severity: str = SEVERITY_MEDIUM
    excerpt: str = ""
    category: str = "secret"

    def location(self) -> str:
        return f"{self.rel_path}:{self.line_number}"


@dataclass
class ScanReport:
    secrets: list[Finding] = field(default_factory=list)
    third_party: list[Finding] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def all_findings(self) -> list[Finding]:
        return self.secrets + self.third_party

    def blocking(self, ignored: set[str]) -> list[Finding]:
        return [
            f
            for f in self.secrets
            if f.severity == SEVERITY_HIGH and f.id not in ignored
        ]

    def sorted_secrets(self) -> list[Finding]:
        return sorted(
            self.secrets,
            key=lambda f: (_SEVERITY_ORDER.get(f.severity, 9), f.rel_path, f.line_number),
        )

    def sorted_third_party(self) -> list[Finding]:
        return sorted(
            self.third_party,
            key=lambda f: (_SEVERITY_ORDER.get(f.severity, 9), f.rel_path, f.line_number),
        )

"""Trade-secret redaction (Compendium section 721.7).

Blocked-out material is drawn as a solid bar and the underlying glyphs are
never written into the PDF, so the text cannot be recovered by selecting or
extracting it. Redaction never changes the number of lines, so it cannot
shift pagination.

Region markers are located in the *original* text and tracked by original
line number, because the comment carrying the marker is usually removed by
the stripper before layout ever sees it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..config import MAX_REDACTION_RATIO, RedactionRules
from .strip import SourceLine

Span = tuple[int, int]


@dataclass
class FileRedaction:
    rel_path: str
    spans: dict[int, list[Span]] = field(default_factory=dict)  # index into lines
    redacted_chars: int = 0
    total_chars: int = 0
    marker_lines: int = 0
    regex_hits: int = 0


@dataclass
class RedactionReport:
    files: list[FileRedaction] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def redacted_chars(self) -> int:
        return sum(f.redacted_chars for f in self.files)

    @property
    def total_chars(self) -> int:
        return sum(f.total_chars for f in self.files)

    @property
    def ratio(self) -> float:
        return self.redacted_chars / self.total_chars if self.total_chars else 0.0

    @property
    def compliant(self) -> bool:
        return self.ratio <= MAX_REDACTION_RATIO


def _merge(spans: list[Span]) -> list[Span]:
    if not spans:
        return []
    spans = sorted(spans)
    out = [spans[0]]
    for a, b in spans[1:]:
        last_a, last_b = out[-1]
        if a <= last_b:
            out[-1] = (last_a, max(last_b, b))
        else:
            out.append((a, b))
    return out


def marker_line_numbers(original_text: str, rules: RedactionRules) -> set[int]:
    """Original line numbers enclosed by BEGIN/END markers."""
    if not rules.begin_marker or not rules.end_marker:
        return set()
    inside = False
    result: set[int] = set()
    for number, line in enumerate(original_text.split("\n"), start=1):
        if rules.begin_marker in line:
            inside = True
            continue
        if rules.end_marker in line:
            inside = False
            continue
        if inside:
            result.add(number)
    return result


def compile_regexes(rules: RedactionRules) -> tuple[list[re.Pattern[str]], list[str]]:
    compiled: list[re.Pattern[str]] = []
    warnings: list[str] = []
    for pattern in rules.regexes:
        if not pattern.strip():
            continue
        try:
            compiled.append(re.compile(pattern))
        except re.error as exc:
            warnings.append(f"Invalid redaction pattern '{pattern}': {exc}")
    return compiled, warnings


def compute_file_redaction(
    rel_path: str,
    original_text: str,
    lines: list[SourceLine],
    rules: RedactionRules,
    compiled: list[re.Pattern[str]] | None = None,
    manual: set[str] | None = None,
) -> FileRedaction:
    out = FileRedaction(rel_path=rel_path)
    out.total_chars = sum(len(line.text.strip()) for line in lines)
    if not rules.enabled:
        return out

    if compiled is None:
        compiled, _ = compile_regexes(rules)
    if manual is None:
        manual = {m.replace("\\", "/") for m in rules.manual_lines}

    markers = marker_line_numbers(original_text, rules)

    for index, line in enumerate(lines):
        text = line.text
        if not text.strip():
            continue
        spans: list[Span] = []
        whole = line.number in markers or f"{rel_path}:{line.number}" in manual
        if whole:
            start = len(text) - len(text.lstrip())
            spans.append((start, len(text)))
            out.marker_lines += 1
        else:
            for pattern in compiled:
                for match in pattern.finditer(text):
                    if match.end() > match.start():
                        spans.append((match.start(), match.end()))
                        out.regex_hits += 1
        if spans:
            merged = _merge(spans)
            out.spans[index] = merged
            out.redacted_chars += sum(b - a for a, b in merged)
    return out


def check_compliance(report: RedactionReport, deposit_mode: str) -> list[str]:
    """Warn when blocked-out material exceeds what section 721.7 allows."""
    messages: list[str] = []
    if report.redacted_chars == 0:
        return messages
    percent = report.ratio * 100
    if not report.compliant:
        messages.append(
            f"Redaction covers {percent:.1f}% of the deposited text. "
            f"Compendium sec. 721.7 caps blocked-out material at "
            f"{MAX_REDACTION_RATIO * 100:.0f}% for this deposit option; "
            "reduce the redacted regions or deposit more pages."
        )
    else:
        messages.append(
            f"Redaction covers {percent:.1f}% of the deposited text "
            f"(within the {MAX_REDACTION_RATIO * 100:.0f}% limit)."
        )
    return messages

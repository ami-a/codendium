"""Per-file line selection.

Sometimes only part of a file belongs in the deposit. This module parses a
range spec ("1-50, 120-200, 305-"), applies it, and works out where the
elision markers go.

Two rules govern the design:

* **Original line numbers.** A range means lines as they appear in the
  editor, not positions after comments were stripped. ``SourceLine.number``
  carries the original number through the transform, so selection stays
  intuitive whatever the comment policy is.

* **Gaps come from the spec, not from what survived.** If comment removal
  deleted lines 1-2, the file must not claim "lines 1-2 omitted" - the
  operator did not omit them, the policy did. Elisions are therefore the
  complement of the requested ranges over the file's true length.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .strip import SourceLine

# Stand-in for "to the end of the file" before the total is known.
OPEN_END = 10**9

Range = tuple[int, int]

# "12", "12-40", "12-" (to EOF), "-40" (from the start)
_TOKEN = re.compile(r"^(?:(\d+)\s*-\s*(\d+)?|-\s*(\d+)|(\d+))$")


@dataclass
class Selection:
    """The result of applying a range spec to one file."""

    lines: list[SourceLine] = field(default_factory=list)
    # index into `lines` -> the (first, last) source lines omitted before it
    elisions: dict[int, Range] = field(default_factory=dict)
    trailing: Range | None = None
    omitted_lines: int = 0
    partial: bool = False
    label: str = ""
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def merge(ranges: list[Range]) -> list[Range]:
    """Sort and coalesce overlapping or touching ranges."""
    if not ranges:
        return []
    ordered = sorted(ranges)
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end + 1:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def parse_ranges(spec: str, total: int | None = None) -> tuple[list[Range], list[str]]:
    """Parse a spec into sorted, merged, clamped ranges.

    An empty spec returns an empty list, which means "the whole file".
    """
    warnings: list[str] = []
    if not spec or not spec.strip():
        return [], warnings

    ranges: list[Range] = []
    for raw in re.split(r"[,;]", spec):
        token = raw.strip()
        if not token:
            continue
        match = _TOKEN.match(token)
        if match is None:
            warnings.append(f"Ignored '{token}': expected a line number or a range like 10-40.")
            continue

        start_text, end_text, upto_text, single_text = match.groups()
        if single_text is not None:
            start = end = int(single_text)
        elif upto_text is not None:
            start, end = 1, int(upto_text)
        else:
            start = int(start_text)
            end = int(end_text) if end_text else OPEN_END

        if start < 1:
            start = 1
        if end < start:
            warnings.append(f"Ignored '{token}': it ends before it starts.")
            continue
        ranges.append((start, end))

    ranges = merge(ranges)

    if total is not None and total > 0:
        clamped: list[Range] = []
        for start, end in ranges:
            if start > total:
                warnings.append(
                    f"Ignored lines {start}-{'end' if end >= OPEN_END else end}: "
                    f"the file has only {total} line(s)."
                )
                continue
            clamped.append((start, min(end, total)))
        ranges = merge(clamped)

    return ranges, warnings


def validate(spec: str, total: int | None = None) -> str | None:
    """Return an error message for a bad spec, or None if it is usable."""
    if not spec or not spec.strip():
        return None
    ranges, warnings = parse_ranges(spec, total)
    if warnings:
        return warnings[0]
    if not ranges:
        return "That selects no lines."
    return None


def format_ranges(ranges: list[Range], total: int | None = None) -> str:
    parts: list[str] = []
    for start, end in ranges:
        if total is not None and end >= total:
            end = total
        parts.append(str(start) if start == end else f"{start}-{end}")
    return ", ".join(parts)


def compute_gaps(ranges: list[Range], total: int) -> list[Range]:
    """The complement of `ranges` within 1..total - i.e. what is left out."""
    if not ranges or total <= 0:
        return []
    gaps: list[Range] = []
    cursor = 1
    for start, end in ranges:
        if start > cursor:
            gaps.append((cursor, start - 1))
        cursor = max(cursor, min(end, total) + 1)
    if cursor <= total:
        gaps.append((cursor, total))
    return gaps


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------


def apply_selection(
    lines: list[SourceLine],
    ranges: list[Range],
    total: int,
) -> Selection:
    """Keep only the requested lines and place the elision markers."""
    if not ranges:
        return Selection(lines=lines)

    kept = [line for line in lines if _in_ranges(line.number, ranges)]

    gaps = compute_gaps(ranges, total)
    elisions: dict[int, Range] = {}
    trailing: Range | None = None

    for gap_start, gap_end in gaps:
        index = next((i for i, line in enumerate(kept) if line.number > gap_end), None)
        if index is None:
            # Nothing kept after this gap: it belongs at the end of the file.
            trailing = (
                (min(trailing[0], gap_start), max(trailing[1], gap_end))
                if trailing
                else (gap_start, gap_end)
            )
            continue
        existing = elisions.get(index)
        elisions[index] = (
            (min(existing[0], gap_start), max(existing[1], gap_end))
            if existing
            else (gap_start, gap_end)
        )

    # A spec that happens to cover the whole file is not a partial deposit,
    # so it earns no PARTIAL banner and no elisions.
    selection = Selection(
        lines=kept,
        elisions=elisions,
        trailing=trailing,
        omitted_lines=sum(end - start + 1 for start, end in gaps),
        partial=bool(gaps),
        label=f"{format_ranges(ranges, total)} of {total}" if gaps else "",
    )
    if not kept:
        selection.warnings.append(
            "The selected line range contains no code once the comment policy "
            "has been applied; only the omission notice will be printed."
        )
    return selection


def _in_ranges(number: int, ranges: list[Range]) -> bool:
    for start, end in ranges:
        if start <= number <= end:
            return True
        if start > number:
            break  # ranges are sorted
    return False

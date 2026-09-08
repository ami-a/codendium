"""Pagination onto the fixed page grid.

This module is pure: it takes text and returns pages. It performs no I/O
and never touches reportlab, which is why the page count it produces can
be shown to the user instantly and is guaranteed to equal the page count
of the PDF the renderer later writes from the very same result.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import LayoutOptions
from .metrics import PageGeometry
from .strip import SourceLine

KIND_HEADER = "header"
KIND_RULE = "rule"
KIND_BANNER = "banner"
KIND_CODE = "code"
KIND_BLANK = "blank"
KIND_NOTICE = "notice"
KIND_ELISION = "elision"

Span = tuple[int, int]


@dataclass
class RenderLine:
    text: str = ""
    kind: str = KIND_BLANK
    number: int | None = None  # original source line number, for the gutter
    bold: bool = False
    redactions: tuple[Span, ...] = ()
    file_path: str = ""
    continuation: bool = False


@dataclass
class Page:
    number: int  # 1-based
    lines: list[RenderLine] = field(default_factory=list)


@dataclass
class FileRange:
    rel_path: str
    first_page: int
    last_page: int
    source_lines: int
    rendered_lines: int


@dataclass
class FileBlock:
    """One file's contribution to the deposit."""

    rel_path: str
    lines: list[SourceLine]
    language: str = ""
    # Redaction column spans, keyed by index into `lines`.
    redactions: dict[int, list[Span]] = field(default_factory=dict)
    # Line-range selection. `elisions` maps an index into `lines` to the
    # (first, last) source lines omitted immediately before it; `trailing`
    # covers lines dropped from the end of the file.
    elisions: dict[int, tuple[int, int]] = field(default_factory=dict)
    trailing_elision: tuple[int, int] | None = None
    # Non-empty only when part of the file was selected, e.g.
    # "1-50, 120-200 of 380". Drives the PARTIAL FILE banner.
    range_label: str = ""


@dataclass
class LayoutResult:
    pages: list[Page] = field(default_factory=list)
    file_ranges: list[FileRange] = field(default_factory=list)
    geometry: PageGeometry | None = None
    warnings: list[str] = field(default_factory=list)
    source_lines: int = 0
    rendered_lines: int = 0
    wrapped_lines: int = 0
    glyph_replacements: int = 0
    redacted_chars: int = 0
    total_chars: int = 0

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def redaction_ratio(self) -> float:
        return self.redacted_chars / self.total_chars if self.total_chars else 0.0

    def range_for(self, rel_path: str) -> FileRange | None:
        return next((r for r in self.file_ranges if r.rel_path == rel_path), None)


# ---------------------------------------------------------------------------
# Wrapping
# ---------------------------------------------------------------------------


def wrap_source_line(text: str, width: int, marker: str) -> list[tuple[int, str, str]]:
    """Split an overlong line into (original column, prefix, body) chunks.

    Overlong lines are wrapped, never truncated: the deposit has to be the
    complete text of the pages it contains.
    """
    width = max(1, width)
    if len(text) <= width:
        return [(0, "", text)]

    marker = marker if len(marker) < width else ""
    body_width = max(1, width - len(marker))

    chunks: list[tuple[int, str, str]] = [(0, "", text[:width])]
    position = width
    while position < len(text):
        chunks.append((position, marker, text[position : position + body_width]))
        position += body_width
    return chunks


def _remap_spans(spans: list[Span], start: int, length: int, offset: int) -> tuple[Span, ...]:
    """Move redaction spans into a wrapped chunk's coordinate space."""
    out: list[Span] = []
    end = start + length
    for a, b in spans:
        lo, hi = max(a, start), min(b, end)
        if lo < hi:
            out.append((lo - start + offset, hi - start + offset))
    return tuple(out)


# ---------------------------------------------------------------------------
# Emitter
# ---------------------------------------------------------------------------


class _Emitter:
    def __init__(self, geometry: PageGeometry) -> None:
        self.geometry = geometry
        self.pages: list[Page] = []
        self._current: Page | None = None

    @property
    def rows_left(self) -> int:
        if self._current is None:
            return 0
        return self.geometry.lines_per_page - len(self._current.lines)

    @property
    def current_page_number(self) -> int:
        return len(self.pages) if self._current is not None else len(self.pages) + 1

    def _new_page(self) -> Page:
        page = Page(number=len(self.pages) + 1)
        self.pages.append(page)
        self._current = page
        return page

    def emit(self, line: RenderLine) -> None:
        if self._current is None or self.rows_left == 0:
            self._new_page()
        assert self._current is not None
        self._current.lines.append(line)

    def blank(self, count: int = 1) -> None:
        for _ in range(count):
            self.emit(RenderLine())

    def page_break(self) -> None:
        """Finish the current page so the next emit starts a fresh one."""
        if self._current is None or not self._current.lines:
            return
        self._current = None

    def ensure_rows(self, needed: int) -> None:
        """Start a new page unless `needed` rows remain (widow control)."""
        if self._current is not None and 0 < self.rows_left < needed:
            self.page_break()

    def finish(self) -> list[Page]:
        return self.pages


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


def _banner_lines(block: FileBlock, geometry: PageGeometry) -> list[RenderLine]:
    """The FILE: header, plus a PARTIAL FILE notice when only part is included.

    A reader must never be able to mistake an extract for a whole file, so
    the fact is stated at the boundary as well as at each cut.
    """
    rel_path = block.rel_path
    rule = "-" * min(60, geometry.code_columns)
    lines = [
        RenderLine(text=f"FILE: {rel_path}", kind=KIND_BANNER, bold=True, file_path=rel_path)
    ]
    if block.range_label:
        lines.append(
            RenderLine(
                text=f"PARTIAL FILE - lines {block.range_label} included",
                kind=KIND_BANNER,
                bold=True,
                file_path=rel_path,
            )
        )
    lines.append(RenderLine(text=rule, kind=KIND_RULE, file_path=rel_path))
    return lines


def _dashes(count: int) -> str:
    return ("- " * (count // 2 + 1))[:count] if count > 0 else ""


def elision_text(first: int, last: int, width: int) -> str:
    """A dashed rule naming exactly which source lines are missing."""
    if first == last:
        label = f" [ line {first} omitted ] "
    else:
        label = f" [ lines {first}-{last} omitted ({last - first + 1} lines) ] "
    if len(label) >= width:
        return label.strip()[:width]
    remaining = width - len(label)
    left = remaining // 2
    return _dashes(left) + label + _dashes(remaining - left)


def build_layout(
    blocks: list[FileBlock],
    header_lines: list[str],
    options: LayoutOptions,
    geometry: PageGeometry,
) -> LayoutResult:
    """Lay the identification block and every file onto the page grid."""
    result = LayoutResult(geometry=geometry)
    emitter = _Emitter(geometry)
    font = geometry.font
    width = geometry.code_columns

    # -- identification block, top of page 1 ------------------------------
    if header_lines:
        for index, raw in enumerate(header_lines):
            text, replaced = font.sanitize(raw)
            result.glyph_replacements += replaced
            for _start, prefix, body in wrap_source_line(text, width, options.wrap_marker):
                emitter.emit(
                    RenderLine(
                        text=prefix + body,
                        kind=KIND_HEADER,
                        bold=(index == 0),
                    )
                )
        emitter.emit(RenderLine(text="=" * min(60, width), kind=KIND_RULE))
        emitter.blank()

    # -- files -------------------------------------------------------------
    for position, block in enumerate(blocks):
        if options.start_files_on_new_page and position > 0:
            emitter.page_break()
        elif position > 0 or header_lines:
            if options.file_gap_lines and emitter.rows_left not in (0, geometry.lines_per_page):
                emitter.blank(options.file_gap_lines)

        if options.show_file_banners:
            # Never leave a banner stranded at the foot of a page.
            banner = _banner_lines(block, geometry)
            emitter.ensure_rows(len(banner) + 1)
            for line in banner:
                emitter.emit(line)

        first_page = emitter.current_page_number
        rendered = 0

        def emit_elision(gap: tuple[int, int]) -> None:
            nonlocal rendered
            emitter.emit(
                RenderLine(
                    text=elision_text(gap[0], gap[1], width),
                    kind=KIND_ELISION,
                    file_path=block.rel_path,
                )
            )
            rendered += 1

        for index, source_line in enumerate(block.lines):
            gap = block.elisions.get(index)
            if gap is not None:
                emit_elision(gap)
            text, replaced = font.sanitize(source_line.text)
            result.glyph_replacements += replaced
            spans = block.redactions.get(index, [])
            chunks = wrap_source_line(text, width, options.wrap_marker)
            if len(chunks) > 1:
                result.wrapped_lines += 1

            for chunk_index, (start, prefix, body) in enumerate(chunks):
                mapped = _remap_spans(spans, start, len(body), len(prefix))
                emitter.emit(
                    RenderLine(
                        text=prefix + body,
                        kind=KIND_CODE if body.strip() or spans else KIND_BLANK,
                        number=source_line.number if chunk_index == 0 else None,
                        redactions=mapped,
                        file_path=block.rel_path,
                        continuation=chunk_index > 0,
                    )
                )
                rendered += 1
                result.total_chars += len(body)
                result.redacted_chars += sum(b - a for a, b in mapped)

        if block.trailing_elision is not None:
            emit_elision(block.trailing_elision)

        result.source_lines += len(block.lines)
        result.rendered_lines += rendered
        last_page = emitter.current_page_number
        result.file_ranges.append(
            FileRange(
                rel_path=block.rel_path,
                first_page=first_page,
                last_page=max(first_page, last_page),
                source_lines=len(block.lines),
                rendered_lines=rendered,
            )
        )

    result.pages = emitter.finish()
    if result.glyph_replacements:
        result.warnings.append(
            f"{result.glyph_replacements} character(s) had no glyph in "
            f"{font.regular} and were replaced with '?'."
        )
    return result


def max_source_line_number(blocks: list[FileBlock]) -> int:
    """Widest gutter needed, so the column width is stable across the PDF."""
    best = 0
    for block in blocks:
        for line in block.lines:
            if line.number > best:
                best = line.number
    return best

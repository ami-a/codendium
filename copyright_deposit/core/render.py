"""PDF rendering.

Two properties are load-bearing:

* **Deterministic.** The canvas runs in reportlab's invariant mode with a
  fixed document date, so the same settings and the same sources produce a
  byte-identical PDF. A re-run therefore proves what was filed.
* **Redaction is real.** Blocked-out text is never written to the content
  stream at all - only a filled rectangle is drawn - so it cannot be
  recovered with copy/paste or a text extractor.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .. import DISPLAY_NAME, __version__
from ..config import HeaderInfo, LayoutOptions
from .deposit import MODE_HEAD_TAIL, DepositSelection
from .layout import (
    KIND_BANNER,
    KIND_CODE,
    KIND_ELISION,
    KIND_HEADER,
    KIND_NOTICE,
    KIND_RULE,
    LayoutResult,
    RenderLine,
)
from .metrics import PageGeometry

GUTTER_GRAY = 0.45
HEADER_GRAY = 0.35
ELISION_GRAY = 0.40


@dataclass
class RenderReport:
    output_path: str
    page_count: int
    font: str
    embedded: bool


def _canvas(path: str, geometry: PageGeometry, header: HeaderInfo, fingerprint: str):
    from reportlab.pdfgen import canvas as rl_canvas

    c = rl_canvas.Canvas(
        path,
        pagesize=(geometry.width, geometry.height),
        invariant=1,          # stable document id and creation date
        pageCompression=1,
    )
    c.setTitle(header.title_line())
    c.setAuthor(header.copyright_owner or "")
    c.setSubject(header.deposit_label or "Source code deposit")
    c.setCreator(f"{DISPLAY_NAME} {__version__}")
    c.setKeywords(f"settings-fingerprint:{fingerprint[:16]}")
    return c


def _draw_text_with_redactions(c, geometry: PageGeometry, line: RenderLine, x0: float, y: float) -> None:
    font = geometry.font
    if not line.redactions:
        c.drawString(x0, y, line.text)
        return

    char_w = font.char_width
    bar_bottom = y - font.size * 0.22
    bar_height = font.size * 1.02

    position = 0
    for start, end in line.redactions:
        start = max(0, min(start, len(line.text)))
        end = max(start, min(end, len(line.text)))
        if start > position:
            c.drawString(x0 + position * char_w, y, line.text[position:start])
        c.saveState()
        c.setFillGray(0.0)
        c.rect(x0 + start * char_w, bar_bottom, (end - start) * char_w, bar_height, fill=1, stroke=0)
        c.restoreState()
        position = end
    if position < len(line.text):
        c.drawString(x0 + position * char_w, y, line.text[position:])


def _draw_page(
    c,
    geometry: PageGeometry,
    lines: list[RenderLine],
    *,
    printed_number: int,
    total_label: int,
    title: str,
    sheet_label: str = "",
    show_number: bool = True,
) -> None:
    font = geometry.font
    code_x = geometry.column_x(geometry.gutter_columns)

    if geometry.running_header:
        c.saveState()
        c.setFont(font.regular, max(6.5, font.size * 0.72))
        c.setFillGray(HEADER_GRAY)
        header_y = geometry.height - geometry.margin - font.size * 0.9
        c.drawString(geometry.margin, header_y, title[:70])
        current_file = next((ln.file_path for ln in lines if ln.file_path), "")
        if current_file:
            c.drawRightString(geometry.width - geometry.margin, header_y, current_file[-70:])
        c.restoreState()

    for row, line in enumerate(lines):
        y = geometry.baseline(row)
        if not line.text and not line.redactions:
            continue

        if line.number is not None and geometry.gutter_columns:
            c.saveState()
            c.setFont(font.regular, font.size)
            c.setFillGray(GUTTER_GRAY)
            c.drawRightString(
                geometry.column_x(geometry.gutter_columns - 1),
                y,
                str(line.number),
            )
            c.restoreState()

        c.setFont(font.bold if line.bold else font.regular, font.size)
        # Elision rules are not source text, so they are set in grey: a
        # reader can tell at a glance that nothing was written there.
        c.setFillGray(ELISION_GRAY if line.kind == KIND_ELISION else 0.0)
        x0 = geometry.margin if line.kind in (KIND_HEADER, KIND_NOTICE) else code_x
        _draw_text_with_redactions(c, geometry, line, x0, y)

    if geometry.page_numbers:
        c.saveState()
        c.setFont(font.regular, max(6.5, font.size * 0.78))
        c.setFillGray(HEADER_GRAY)
        footer_y = geometry.margin * 0.55
        if show_number:
            c.drawCentredString(
                geometry.width / 2.0,
                footer_y,
                f"Page {printed_number} of {total_label}",
            )
        if sheet_label:
            c.drawRightString(geometry.width - geometry.margin, footer_y, sheet_label)
        c.restoreState()

    c.showPage()


def _separator_lines(text: str, geometry: PageGeometry) -> list[RenderLine]:
    """Center the omission notice on its own sheet."""
    from .layout import wrap_source_line

    width = min(geometry.code_columns, 72)
    chunks = [body for _s, _p, body in wrap_source_line(text, width, "")]
    top_pad = max(0, (geometry.lines_per_page - len(chunks)) // 2)
    lines = [RenderLine() for _ in range(top_pad)]
    lines.extend(RenderLine(text=chunk, kind=KIND_NOTICE, bold=True) for chunk in chunks)
    return lines


def render_pdf(
    layout: LayoutResult,
    output_path: str | Path,
    header: HeaderInfo,
    options: LayoutOptions,
    *,
    selection: DepositSelection | None = None,
    fingerprint: str = "",
    include_separator: bool = True,
) -> RenderReport:
    """Write `layout` to a PDF, optionally restricted to a deposit selection."""
    geometry = layout.geometry
    if geometry is None:
        raise ValueError("layout has no geometry; build it with build_layout()")

    output_path = str(output_path)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    pages = layout.pages
    total_label = len(pages)
    title = header.title_line()

    if selection is None:
        chosen = list(range(1, len(pages) + 1))
        separator_after = None
        sheets = len(chosen)
    else:
        chosen = list(selection.page_numbers)
        total_label = selection.total_pages
        sheets = len(chosen)
        separator_after = None
        if selection.mode == MODE_HEAD_TAIL and include_separator:
            separator_after = min(len(chosen), max(0, selection_head_count(selection)))

    c = _canvas(output_path, geometry, header, fingerprint)

    emitted = 0
    for position, page_number in enumerate(chosen):
        page = pages[page_number - 1]
        emitted += 1
        _draw_page(
            c,
            geometry,
            page.lines,
            printed_number=page_number,
            total_label=total_label,
            title=title,
            sheet_label=(
                f"Deposit sheet {emitted} of {sheets}" if selection and selection.mode == MODE_HEAD_TAIL else ""
            ),
        )
        if separator_after is not None and position + 1 == separator_after:
            notice = selection.separator_notice() if selection else ""
            if notice:
                _draw_page(
                    c,
                    geometry,
                    _separator_lines(notice, geometry),
                    printed_number=page_number,
                    total_label=total_label,
                    title=title,
                    sheet_label="omission notice",
                    show_number=False,
                )

    c.save()
    return RenderReport(
        output_path=output_path,
        page_count=emitted,
        font=geometry.font.regular,
        embedded=geometry.font.embedded,
    )


def selection_head_count(selection: DepositSelection) -> int:
    """How many leading pages precede the omission gap."""
    if selection.omitted is None:
        return len(selection.page_numbers)
    gap_start = selection.omitted[0]
    return sum(1 for n in selection.page_numbers if n < gap_start)

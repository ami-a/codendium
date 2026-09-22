"""The fixed page grid.

The Office asks for a monospaced face at roughly 9-10 pt and about 40 lines
per page, and forbids compressing the code to disclose less. These tests
hold the grid to that.
"""

from __future__ import annotations


from copyright_deposit.config import LayoutOptions
from copyright_deposit.core import metrics
from copyright_deposit.core.layout import build_layout, wrap_source_line, FileBlock
from copyright_deposit.core.strip import SourceLine


def geometry(**kwargs):
    return metrics.build_geometry(LayoutOptions(**kwargs))


def block(lines: list[str], path: str = "a.py") -> FileBlock:
    return FileBlock(
        rel_path=path,
        lines=[SourceLine(n, t) for n, t in enumerate(lines, start=1)],
    )


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def test_default_grid_matches_the_office_guidance():
    g = geometry()
    assert g.lines_per_page == 40
    assert 9.0 <= g.font.size <= 10.0
    assert g.code_columns >= 80  # a normal 80-column line never wraps
    # 40 lines must actually fit between the margins.
    assert g.leading * g.lines_per_page <= g.text_top - g.text_bottom + 0.01


def test_font_is_monospaced():
    from reportlab.pdfbase import pdfmetrics

    g = geometry()
    widths = {pdfmetrics.stringWidth(ch, g.font.regular, g.font.size) for ch in "iWm.1"}
    assert len(widths) == 1


def test_a4_is_narrower_than_letter():
    assert geometry(page_size="a4").code_columns <= geometry(page_size="letter").code_columns


def test_line_number_gutter_reduces_the_code_width():
    plain = geometry()
    numbered = metrics.build_geometry(LayoutOptions(show_line_numbers=True), 1234)
    assert numbered.code_columns < plain.code_columns


# ---------------------------------------------------------------------------
# Wrapping
# ---------------------------------------------------------------------------


def test_short_lines_are_not_wrapped():
    assert wrap_source_line("abc", 10, ">> ") == [(0, "", "abc")]


def test_long_lines_wrap_and_lose_nothing():
    text = "x" * 250
    chunks = wrap_source_line(text, 88, ">> ")
    assert len(chunks) > 1
    assert "".join(body for _s, _p, body in chunks) == text


def test_wrapped_chunks_never_exceed_the_column_width():
    text = "y" * 500
    for _start, prefix, body in wrap_source_line(text, 88, ">> "):
        assert len(prefix) + len(body) <= 88


def test_wrap_offsets_track_the_original_columns():
    text = "abcdefghij" * 30
    for start, _prefix, body in wrap_source_line(text, 40, ">> "):
        assert text[start : start + len(body)] == body


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def test_no_page_exceeds_the_line_budget():
    g = geometry()
    result = build_layout(
        [block([f"line {i}" for i in range(500)])], ["Program", "Version: 1.0"], LayoutOptions(), g
    )
    assert result.pages
    for page in result.pages:
        assert len(page.lines) <= g.lines_per_page


def test_no_rendered_line_overflows_the_text_column():
    g = geometry()
    long_lines = ["z" * 400 for _ in range(20)]
    result = build_layout([block(long_lines)], [], LayoutOptions(), g)
    for page in result.pages:
        for line in page.lines:
            assert len(line.text) <= g.code_columns


def test_page_count_is_a_pure_function_of_the_lines():
    g = geometry()
    options = LayoutOptions()
    first = build_layout([block([f"l{i}" for i in range(300)])], ["P"], options, g)
    second = build_layout([block([f"l{i}" for i in range(300)])], ["P"], options, g)
    assert first.page_count == second.page_count


def test_identification_block_is_at_the_top_of_page_one():
    g = geometry()
    result = build_layout(
        [block(["x = 1"])], ["My Program", "Version: 2.3"], LayoutOptions(), g
    )
    texts = [line.text for line in result.pages[0].lines[:2]]
    assert texts == ["My Program", "Version: 2.3"]
    assert result.pages[0].lines[0].bold


def test_file_banner_is_printed_at_each_boundary():
    g = geometry()
    result = build_layout(
        [block(["a = 1"], "one.py"), block(["b = 2"], "two.py")], [], LayoutOptions(), g
    )
    banners = [
        line.text
        for page in result.pages
        for line in page.lines
        if line.kind == "banner"
    ]
    assert banners == ["FILE: one.py", "FILE: two.py"]


def test_banner_is_never_stranded_at_the_foot_of_a_page():
    g = geometry()
    options = LayoutOptions()
    blocks = [block([f"a{i}" for i in range(38)], "one.py"), block(["b = 2"], "two.py")]
    result = build_layout(blocks, [], options, g)
    for page in result.pages:
        for index, line in enumerate(page.lines):
            if line.kind == "banner":
                # banner + rule + at least one code line
                assert index <= g.lines_per_page - 3


def test_file_ranges_cover_every_file():
    g = geometry()
    blocks = [block([f"x{i}" for i in range(120)], f"f{n}.py") for n in range(3)]
    result = build_layout(blocks, [], LayoutOptions(), g)
    assert len(result.file_ranges) == 3
    for r in result.file_ranges:
        assert 1 <= r.first_page <= r.last_page <= result.page_count


def test_start_files_on_new_page_puts_each_file_first():
    g = geometry()
    blocks = [block(["a = 1"], "one.py"), block(["b = 2"], "two.py")]
    result = build_layout(blocks, [], LayoutOptions(start_files_on_new_page=True), g)
    assert result.page_count == 2


def test_glyphs_outside_the_font_are_replaced_not_dropped():
    g = geometry()
    result = build_layout([block(["x = '中文'"])], [], LayoutOptions(), g)
    text = result.pages[0].lines[-1].text
    assert "?" in text
    assert result.glyph_replacements == 2

"""End-to-end: the pipeline through to the actual PDF.

The central claim of the design is verified here - the page count shown
before rendering equals the number of pages in the file that gets written.
"""

from __future__ import annotations

import hashlib

import pytest
from pypdf import PdfReader

from copyright_deposit.core.deposit import MODE_ENTIRE, MODE_HEAD_TAIL
from copyright_deposit.core.pipeline import Pipeline

from helpers import big_python_file


def sha256(path) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def page_texts(path) -> list[str]:
    return [page.extract_text() or "" for page in PdfReader(str(path)).pages]


SMALL_TREE = {
    "main.py": "from pkg import core\n\n\ndef main():\n    return core.run()\n",
    "pkg/core.py": '"""Core."""\n\n\ndef run():\n    # work\n    return 42\n',
}


# ---------------------------------------------------------------------------
# The estimate must equal the rendered result
# ---------------------------------------------------------------------------


def test_estimate_equals_the_rendered_page_count(make_tree, settings_for):
    settings = settings_for(make_tree({"big.py": big_python_file(600)}))
    pipeline = Pipeline()
    estimate = pipeline.estimate(settings)
    result = pipeline.build(settings)

    full = next(p for p in result.outputs if p.endswith("_full.pdf"))
    assert len(PdfReader(full).pages) == estimate.page_count
    assert estimate.page_count > 50  # the fixture really does exercise the rule


def test_estimate_equals_rendered_count_for_a_small_program(make_tree, settings_for):
    settings = settings_for(make_tree(SMALL_TREE))
    pipeline = Pipeline()
    estimate = pipeline.estimate(settings)
    result = pipeline.build(settings)
    full = next(p for p in result.outputs if p.endswith("_full.pdf"))
    assert len(PdfReader(full).pages) == estimate.page_count


@pytest.mark.parametrize(
    "overrides",
    [
        {"show_line_numbers": True},
        {"page_size": "a4"},
        {"lines_per_page": 30},
        {"font_size": 10.0},
        {"start_files_on_new_page": True},
        {"show_file_banners": False},
        {"running_header": False, "page_numbers": False},
    ],
)
def test_estimate_matches_rendering_across_layouts(make_tree, settings_for, overrides):
    settings = settings_for(make_tree({"big.py": big_python_file(120)}))
    for key, value in overrides.items():
        setattr(settings.layout, key, value)
    pipeline = Pipeline()
    estimate = pipeline.estimate(settings)
    result = pipeline.build(settings)
    full = next(p for p in result.outputs if p.endswith("_full.pdf"))
    assert len(PdfReader(full).pages) == estimate.page_count


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------


def test_two_builds_are_byte_identical(make_tree, settings_for, tmp_path):
    root = make_tree(SMALL_TREE)
    first = settings_for(root)
    first.output_dir = str(tmp_path / "a")
    second = settings_for(root)
    second.output_dir = str(tmp_path / "b")

    outputs_a = Pipeline().build(first).outputs
    outputs_b = Pipeline().build(second).outputs
    assert outputs_a and len(outputs_a) == len(outputs_b)
    for left, right in zip(outputs_a, outputs_b):
        assert sha256(left) == sha256(right)


def test_output_location_does_not_change_the_document(make_tree, settings_for, tmp_path):
    """The fingerprint stamped in the PDF describes content, not paths."""
    root = make_tree(SMALL_TREE)
    a = settings_for(root)
    a.output_dir = str(tmp_path / "one")
    a.output_basename = "alpha"
    b = settings_for(root)
    b.output_dir = str(tmp_path / "two")
    b.output_basename = "beta"
    assert a.content_fingerprint() == b.content_fingerprint()
    assert a.fingerprint() != b.fingerprint()


# ---------------------------------------------------------------------------
# The 50-page rule in the actual files
# ---------------------------------------------------------------------------


def test_short_program_deposits_every_page(make_tree, settings_for):
    settings = settings_for(make_tree(SMALL_TREE))
    pipeline = Pipeline()
    result = pipeline.build(settings)
    estimate = result.estimate
    assert estimate.selection.mode == MODE_ENTIRE

    deposit = next(p for p in result.outputs if p.endswith("_deposit.pdf"))
    assert len(PdfReader(deposit).pages) == estimate.page_count
    assert "included in full" in estimate.selection.filing_statement()


def test_long_program_deposits_fifty_sheets_plus_a_notice(make_tree, settings_for):
    settings = settings_for(make_tree({"big.py": big_python_file(600)}))
    pipeline = Pipeline()
    result = pipeline.build(settings)
    estimate = result.estimate
    assert estimate.selection.mode == MODE_HEAD_TAIL
    assert estimate.selection.deposited_pages == 50

    deposit = next(p for p in result.outputs if p.endswith("_deposit.pdf"))
    texts = page_texts(deposit)
    assert len(texts) == 51  # 50 content sheets + the omission notice
    assert "intentionally omitted" in texts[25]


def test_deposit_pages_keep_the_original_page_numbers(make_tree, settings_for):
    settings = settings_for(make_tree({"big.py": big_python_file(600)}))
    result = Pipeline().build(settings)
    estimate = result.estimate
    total = estimate.page_count
    deposit = next(p for p in result.outputs if p.endswith("_deposit.pdf"))
    texts = page_texts(deposit)

    assert f"Page 1 of {total}" in texts[0]
    assert f"Page 25 of {total}" in texts[24]
    # The sheet after the notice is the first of the tail block.
    first_tail = estimate.selection.page_numbers[25]
    assert f"Page {first_tail} of {total}" in texts[26]
    assert f"Page {total} of {total}" in texts[-1]


def test_separator_page_can_be_switched_off(make_tree, settings_for):
    settings = settings_for(make_tree({"big.py": big_python_file(600)}))
    settings.deposit.separator_page = False
    result = Pipeline().build(settings)
    deposit = next(p for p in result.outputs if p.endswith("_deposit.pdf"))
    assert len(PdfReader(deposit).pages) == 50


# ---------------------------------------------------------------------------
# Page content
# ---------------------------------------------------------------------------


def test_identification_block_is_on_the_first_page(make_tree, settings_for):
    settings = settings_for(make_tree(SMALL_TREE))
    settings.header.version = "3.1.4"
    settings.header.revision = "abc1234"
    result = Pipeline().build(settings)
    full = next(p for p in result.outputs if p.endswith("_full.pdf"))
    first = page_texts(full)[0]

    assert "Test Program" in first
    assert "Version: 3.1.4" in first
    assert "Release/build date: 2026-01-01" in first
    assert "Source revision/commit: abc1234" in first
    assert "Copyright (c)" in first and "Test Owner" in first
    assert "Deposit Copy" in first


def test_file_paths_are_printed_at_each_boundary(make_tree, settings_for):
    settings = settings_for(make_tree(SMALL_TREE))
    result = Pipeline().build(settings)
    full = next(p for p in result.outputs if p.endswith("_full.pdf"))
    text = "\n".join(page_texts(full))
    assert "FILE: main.py" in text
    assert "FILE: pkg/core.py" in text


def test_pages_are_not_overfilled(make_tree, settings_for):
    """About 40 lines per page: the deposit must stay readable."""
    settings = settings_for(make_tree({"big.py": big_python_file(300)}))
    pipeline = Pipeline()
    estimate = pipeline.estimate(settings)
    for page in estimate.layout.pages:
        assert len(page.lines) <= settings.layout.lines_per_page


def test_comments_are_absent_from_the_pdf(make_tree, settings_for):
    settings = settings_for(
        make_tree({"a.py": "# SECRETCOMMENT\nx = 1  # TRAILINGNOTE\n"})
    )
    result = Pipeline().build(settings)
    full = next(p for p in result.outputs if p.endswith("_full.pdf"))
    text = "\n".join(page_texts(full))
    assert "SECRETCOMMENT" not in text
    assert "TRAILINGNOTE" not in text
    assert "x = 1" in text


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


REDACT_TREE = {
    "algo.py": (
        "def public(x):\n"
        "    return _core(x)\n"
        "\n"
        "# COPYRIGHT-REDACT-BEGIN\n"
        "def _core(x):\n"
        "    MAGICCONSTANT = 1234567\n"
        "    return x ^ MAGICCONSTANT\n"
        "# COPYRIGHT-REDACT-END\n"
    )
}


def test_redacted_text_cannot_be_extracted(make_tree, settings_for):
    settings = settings_for(make_tree(REDACT_TREE))
    settings.redaction.enabled = True
    result = Pipeline().build(settings)
    full = next(p for p in result.outputs if p.endswith("_full.pdf"))
    text = "\n".join(page_texts(full))

    assert "MAGICCONSTANT" not in text
    assert "1234567" not in text
    assert "def public(x):" in text  # the rest of the program is intact


def test_redaction_is_off_unless_enabled(make_tree, settings_for):
    settings = settings_for(make_tree(REDACT_TREE))
    result = Pipeline().build(settings)
    full = next(p for p in result.outputs if p.endswith("_full.pdf"))
    assert "MAGICCONSTANT" in "\n".join(page_texts(full))


def test_redaction_does_not_change_the_page_count(make_tree, settings_for):
    root = make_tree(REDACT_TREE)
    plain = Pipeline().estimate(settings_for(root))
    redacted_settings = settings_for(root)
    redacted_settings.redaction.enabled = True
    redacted = Pipeline().estimate(redacted_settings)
    assert plain.page_count == redacted.page_count


def test_regex_redaction_blacks_out_matches(make_tree, settings_for):
    settings = settings_for(make_tree({"a.py": "key = 'TOPSECRETVALUE'\nz = 1\n"}))
    settings.redaction.enabled = True
    settings.redaction.regexes = ["TOPSECRETVALUE"]
    result = Pipeline().build(settings)
    full = next(p for p in result.outputs if p.endswith("_full.pdf"))
    text = "\n".join(page_texts(full))
    assert "TOPSECRETVALUE" not in text
    assert "z = 1" in text


def test_excessive_redaction_is_reported(make_tree, settings_for):
    settings = settings_for(make_tree(REDACT_TREE))
    settings.redaction.enabled = True
    settings.redaction.regexes = ["."]  # black out everything
    estimate = Pipeline().estimate(settings)
    assert not estimate.redaction_report.compliant
    assert any("721.7" in w for w in estimate.warnings)


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def test_manifest_records_every_file_with_its_hash(make_tree, settings_for):
    import json

    settings = settings_for(make_tree(SMALL_TREE))
    result = Pipeline().build(settings)
    manifest = json.loads(open(result.manifest_path, encoding="utf-8").read())

    paths = {entry["path"] for entry in manifest["files"]}
    assert paths == {"main.py", "pkg/core.py"}
    for entry in manifest["files"]:
        assert len(entry["sha256"]) == 64
        assert entry["first_page"] >= 1
    assert manifest["deposit"]["mode"] == MODE_ENTIRE
    assert manifest["totals"]["pages"] == result.estimate.page_count


def test_summary_contains_the_filing_statement(make_tree, settings_for):
    settings = settings_for(make_tree(SMALL_TREE))
    result = Pipeline().build(settings)
    summary = open(result.summary_path, encoding="utf-8").read()
    assert "COPYRIGHT DEPOSIT BUILD SUMMARY" in summary
    assert "Statement for the application" in summary
    assert "FILE ORDER" in summary


# ---------------------------------------------------------------------------
# What-if
# ---------------------------------------------------------------------------


def test_what_if_pages_decrease_as_more_is_stripped(make_tree, settings_for):
    settings = settings_for(make_tree({"big.py": big_python_file(200)}))
    rows = Pipeline().what_if(settings)
    counts = [pages for _label, pages, _mode in rows]
    assert len(counts) == 4
    assert counts == sorted(counts, reverse=True)
    assert counts[0] > counts[-1]


def test_what_if_reports_the_deposit_mode(make_tree, settings_for):
    settings = settings_for(make_tree(SMALL_TREE))
    rows = Pipeline().what_if(settings)
    assert all(mode == "entire program" for _label, _pages, mode in rows)

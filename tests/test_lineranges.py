"""Per-file line selection and its elision markers."""

from __future__ import annotations

import pytest
from pypdf import PdfReader

from copyright_deposit.core import lineranges
from copyright_deposit.core.lineranges import (
    apply_selection,
    compute_gaps,
    format_ranges,
    parse_ranges,
    validate,
)
from copyright_deposit.core.layout import elision_text
from copyright_deposit.core.pipeline import Pipeline
from copyright_deposit.core.strip import SourceLine


def lines(*numbers: int) -> list[SourceLine]:
    return [SourceLine(n, f"line{n}") for n in numbers]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_empty_spec_means_the_whole_file():
    assert parse_ranges("") == ([], [])
    assert parse_ranges("   ") == ([], [])


@pytest.mark.parametrize(
    "spec,expected",
    [
        ("1-50", [(1, 50)]),
        ("12", [(12, 12)]),
        ("1-50, 120-200", [(1, 50), (120, 200)]),
        ("1-50;120-200", [(1, 50), (120, 200)]),
        ("  1 - 50 ,  120 - 200  ", [(1, 50), (120, 200)]),
        ("-40", [(1, 40)]),
    ],
)
def test_supported_spellings(spec, expected):
    assert parse_ranges(spec)[0] == expected


def test_open_ended_range_runs_to_the_end_of_the_file():
    assert parse_ranges("305-", 400)[0] == [(305, 400)]


def test_overlapping_and_touching_ranges_are_merged():
    assert parse_ranges("1-20, 15-30")[0] == [(1, 30)]
    assert parse_ranges("1-20, 21-30")[0] == [(1, 30)]


def test_ranges_are_sorted_regardless_of_input_order():
    assert parse_ranges("120-200, 1-50")[0] == [(1, 50), (120, 200)]


def test_ranges_are_clamped_to_the_file_length():
    ranges, warnings = parse_ranges("1-500", 100)
    assert ranges == [(1, 100)]
    assert warnings == []


def test_a_range_beyond_the_file_is_dropped_with_a_warning():
    ranges, warnings = parse_ranges("500-600", 100)
    assert ranges == []
    assert "only 100 line(s)" in warnings[0]


def test_an_inverted_range_is_rejected():
    ranges, warnings = parse_ranges("50-10")
    assert ranges == []
    assert "ends before it starts" in warnings[0]


def test_nonsense_is_rejected():
    ranges, warnings = parse_ranges("abc")
    assert ranges == []
    assert "expected a line number" in warnings[0]


def test_validate_accepts_good_specs_and_explains_bad_ones():
    assert validate("") is None
    assert validate("1-50, 120-200") is None
    assert validate("50-10") is not None
    assert validate("banana") is not None
    assert validate("500-600", 100) is not None


def test_format_round_trips():
    ranges, _ = parse_ranges("1-50, 120-200")
    assert format_ranges(ranges) == "1-50, 120-200"
    assert format_ranges([(7, 7)]) == "7"


# ---------------------------------------------------------------------------
# Gaps
# ---------------------------------------------------------------------------


def test_gaps_are_the_complement_of_the_ranges():
    assert compute_gaps([(1, 50), (120, 200)], 380) == [(51, 119), (201, 380)]


def test_a_leading_gap_is_reported():
    assert compute_gaps([(100, 200)], 200) == [(1, 99)]


def test_full_coverage_leaves_no_gaps():
    assert compute_gaps([(1, 100)], 100) == []


def test_no_ranges_means_no_gaps():
    assert compute_gaps([], 100) == []


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def test_no_ranges_keeps_everything_and_marks_nothing():
    selection = apply_selection(lines(1, 2, 3), [], 3)
    assert len(selection.lines) == 3
    assert not selection.partial
    assert selection.elisions == {}
    assert selection.trailing is None


def test_only_the_selected_lines_survive():
    selection = apply_selection(lines(1, 5, 10, 15, 20), [(1, 6), (14, 16)], 20)
    assert [line.number for line in selection.lines] == [1, 5, 15]


def test_an_interior_gap_becomes_an_elision_before_the_next_line():
    selection = apply_selection(lines(1, 5, 15, 20), [(1, 6), (14, 20)], 20)
    assert selection.elisions == {2: (7, 13)}
    assert selection.trailing is None


def test_a_trailing_gap_becomes_a_trailing_elision():
    selection = apply_selection(lines(1, 5, 15), [(1, 6)], 20)
    assert selection.trailing == (7, 20)


def test_a_leading_gap_is_marked_before_the_first_kept_line():
    selection = apply_selection(lines(1, 50, 60), [(40, 100)], 100)
    assert selection.elisions == {0: (1, 39)}


def test_lines_removed_by_the_comment_policy_are_not_reported_as_omitted():
    """The operator omitted nothing here - stripping did. No marker is due."""
    # Lines 1-2 were comments and are already gone from `lines`.
    selection = apply_selection(lines(3, 4, 5), [(1, 5)], 5)
    assert selection.elisions == {}
    assert selection.trailing is None
    assert not selection.partial


def test_the_label_states_what_was_included_and_the_total():
    selection = apply_selection(lines(1, 130), [(1, 50), (120, 200)], 380)
    assert selection.label == "1-50, 120-200 of 380"


def test_omitted_line_count_is_reported():
    selection = apply_selection(lines(1), [(1, 50)], 100)
    assert selection.omitted_lines == 50


def test_a_selection_that_keeps_nothing_warns_and_still_marks_the_gap():
    # Lines 90-100 were requested but none survived; the only gap is 1-89.
    selection = apply_selection(lines(1, 2, 3), [(90, 100)], 100)
    assert selection.lines == []
    assert selection.trailing == (1, 89)
    assert selection.warnings


# ---------------------------------------------------------------------------
# The marker itself
# ---------------------------------------------------------------------------


def test_elision_text_names_the_missing_lines_and_fits_the_column():
    text = elision_text(51, 119, 88)
    assert "lines 51-119 omitted" in text
    assert "69 lines" in text
    assert len(text) <= 88
    assert text.startswith("-")


def test_elision_text_is_singular_for_one_line():
    assert "line 51 omitted" in elision_text(51, 51, 88)


def test_elision_text_survives_a_narrow_column():
    assert len(elision_text(51, 119, 20)) <= 20


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------


def sample_source(count: int = 38) -> str:
    body = ["# leading comment", "# another comment"]
    for index in range(1, count + 1):
        body.append(f"def function_{index:02d}():")
        body.append(f"    return {index}")
        body.append("")
    return "\n".join(body) + "\n"


def build_with_ranges(make_tree, settings_for, spec: str):
    settings = settings_for(make_tree({"sample.py": sample_source()}))
    if spec:
        settings.line_ranges = {"sample.py": spec}
    result = Pipeline().build(settings)
    full = next(p for p in result.outputs if p.endswith("_full.pdf"))
    text = "\n".join(page.extract_text() or "" for page in PdfReader(full).pages)
    return result, text


def test_only_selected_lines_reach_the_pdf(make_tree, settings_for):
    _result, text = build_with_ranges(make_tree, settings_for, "1-20, 60-80")
    assert "function_01" in text        # line 3, inside 1-20
    assert "function_06" in text        # line 18, inside 1-20
    assert "function_10" not in text    # line 30, inside the gap
    assert "function_20" in text        # line 60, inside 60-80


def test_partial_file_banner_is_printed(make_tree, settings_for):
    _result, text = build_with_ranges(make_tree, settings_for, "1-20, 60-80")
    assert "PARTIAL FILE - lines 1-20, 60-80 of 116 included" in text


def test_elision_markers_are_printed_at_each_cut(make_tree, settings_for):
    _result, text = build_with_ranges(make_tree, settings_for, "1-20, 60-80")
    assert "[ lines 21-59 omitted" in text
    assert "[ lines 81-116 omitted" in text


def test_a_whole_file_gets_no_partial_marking(make_tree, settings_for):
    _result, text = build_with_ranges(make_tree, settings_for, "")
    assert "PARTIAL FILE" not in text
    assert "omitted" not in text


def test_selecting_the_entire_range_gets_no_partial_marking(make_tree, settings_for):
    _result, text = build_with_ranges(make_tree, settings_for, "1-116")
    assert "PARTIAL FILE" not in text
    assert "omitted" not in text


def test_ranges_reduce_the_page_count(make_tree, settings_for):
    settings = settings_for(make_tree({"sample.py": sample_source(300)}))
    whole = Pipeline().estimate(settings)
    settings.line_ranges = {"sample.py": "1-100"}
    part = Pipeline().estimate(settings)
    assert part.page_count < whole.page_count


def test_the_estimate_still_matches_the_rendered_pdf(make_tree, settings_for):
    settings = settings_for(make_tree({"sample.py": sample_source(300)}))
    settings.line_ranges = {"sample.py": "1-100, 400-600"}
    pipeline = Pipeline()
    estimate = pipeline.estimate(settings)
    result = pipeline.build(settings)
    full = next(p for p in result.outputs if p.endswith("_full.pdf"))
    assert len(PdfReader(full).pages) == estimate.page_count


def test_ranges_do_not_disturb_redaction_alignment(make_tree, settings_for):
    source = "\n".join(
        [
            "def keep():",
            "    return 1",
            "",
            "def hidden():",
            "    SECRETVALUE = 99",
            "    return SECRETVALUE",
            "",
            "def tail():",
            "    return 2",
        ]
    )
    settings = settings_for(make_tree({"a.py": source}))
    settings.line_ranges = {"a.py": "1-6"}
    settings.redaction.enabled = True
    settings.redaction.regexes = ["SECRETVALUE"]
    result = Pipeline().build(settings)
    full = next(p for p in result.outputs if p.endswith("_full.pdf"))
    text = "\n".join(page.extract_text() or "" for page in PdfReader(full).pages)

    assert "SECRETVALUE" not in text     # redacted, within the selected range
    assert "def keep():" in text
    assert "def tail():" not in text     # outside the selected range


def test_manifest_records_the_selection(make_tree, settings_for):
    import json

    settings = settings_for(make_tree({"sample.py": sample_source()}))
    settings.line_ranges = {"sample.py": "1-20, 60-80"}
    result = Pipeline().build(settings)
    manifest = json.loads(open(result.manifest_path, encoding="utf-8").read())

    entry = manifest["files"][0]
    assert entry["partial"] is True
    assert entry["line_ranges"] == "1-20, 60-80"
    assert entry["line_range_label"] == "1-20, 60-80 of 116"
    assert entry["lines_omitted_by_range"] == 75
    assert manifest["totals"]["partial_files"] == 1


def test_summary_lists_partial_files(make_tree, settings_for):
    settings = settings_for(make_tree({"sample.py": sample_source()}))
    settings.line_ranges = {"sample.py": "1-20"}
    result = Pipeline().build(settings)
    summary = open(result.summary_path, encoding="utf-8").read()
    assert "PARTIAL FILES" in summary
    assert "[PARTIAL]" in summary


def test_settings_with_ranges_round_trip():
    from copyright_deposit.config import BuildSettings

    settings = BuildSettings()
    settings.line_ranges = {"a.py": "1-50", "b/c.py": "10-20, 30-"}
    restored = BuildSettings.from_json(settings.to_json())
    assert restored.line_ranges == settings.line_ranges


def test_an_invalid_range_warns_but_does_not_stop_the_build(make_tree, settings_for):
    settings = settings_for(make_tree({"sample.py": sample_source()}))
    settings.line_ranges = {"sample.py": "9000-9100"}
    estimate = Pipeline().estimate(settings)
    assert any("only 116 line(s)" in w for w in estimate.warnings)
    assert estimate.page_count >= 1

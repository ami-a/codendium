"""Compendium section 721.6 page selection."""

from __future__ import annotations

from copyright_deposit.config import DepositOptions
from copyright_deposit.core.deposit import (
    MODE_ENTIRE,
    MODE_HEAD_TAIL,
    files_entirely_omitted,
    files_partially_shown,
    select_pages,
)
from copyright_deposit.core.layout import FileRange


def test_short_program_is_deposited_whole():
    selection = select_pages(49)
    assert selection.mode == MODE_ENTIRE
    assert selection.page_numbers == list(range(1, 50))
    assert selection.omitted is None


def test_exactly_fifty_pages_is_still_deposited_whole():
    selection = select_pages(50)
    assert selection.mode == MODE_ENTIRE
    assert selection.deposited_pages == 50


def test_long_program_takes_the_first_and_last_twenty_five():
    selection = select_pages(137)
    assert selection.mode == MODE_HEAD_TAIL
    assert selection.deposited_pages == 50
    assert selection.page_numbers[:25] == list(range(1, 26))
    assert selection.page_numbers[25:] == list(range(113, 138))
    assert selection.omitted == (26, 112)


def test_fifty_one_pages_omits_a_single_page():
    selection = select_pages(51)
    assert selection.mode == MODE_HEAD_TAIL
    assert selection.omitted == (26, 26)
    assert selection.deposited_pages == 50


def test_rule_can_be_switched_off():
    selection = select_pages(200, DepositOptions(apply_rule=False))
    assert selection.mode == MODE_ENTIRE
    assert selection.deposited_pages == 200


def test_filing_statement_reports_the_whole_program():
    assert "included in full" in select_pages(20).filing_statement()


def test_filing_statement_describes_the_split():
    statement = select_pages(137).filing_statement()
    assert "first 25 pages" in statement
    assert "113-137" in statement


def test_separator_notice_names_the_omitted_range():
    notice = select_pages(137).separator_notice()
    assert "26-112" in notice
    assert "721.6" in notice


def test_files_inside_the_gap_are_reported_as_unseen():
    selection = select_pages(137)
    ranges = [
        FileRange("head.py", 1, 10, 100, 100),
        FileRange("middle.py", 40, 60, 100, 100),
        FileRange("straddle.py", 20, 30, 100, 100),
        FileRange("tail.py", 120, 137, 100, 100),
    ]
    assert files_entirely_omitted(selection, ranges) == ["middle.py"]
    assert files_partially_shown(selection, ranges) == ["straddle.py"]


def test_no_files_are_omitted_from_a_whole_deposit():
    selection = select_pages(30)
    ranges = [FileRange("a.py", 1, 30, 10, 10)]
    assert files_entirely_omitted(selection, ranges) == []

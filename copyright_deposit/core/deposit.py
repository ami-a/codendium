"""The Compendium section 721.6 page-selection rule.

For a first registration:

* 50 pages or fewer  -> deposit the entire program, and tell the Office the
  complete code is included.
* more than 50 pages -> deposit the first 25 and the last 25 pages.

Selection operates on the laid-out pages, so the deposit is assembled from
the same grid as the full copy and page numbers continue to refer to the
complete program.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import DepositOptions

MODE_ENTIRE = "entire"
MODE_HEAD_TAIL = "head_tail"


@dataclass
class DepositSelection:
    mode: str
    total_pages: int
    page_numbers: list[int] = field(default_factory=list)  # 1-based, in order
    omitted: tuple[int, int] | None = None  # inclusive range of skipped pages

    @property
    def deposited_pages(self) -> int:
        return len(self.page_numbers)

    @property
    def omitted_count(self) -> int:
        if self.omitted is None:
            return 0
        return self.omitted[1] - self.omitted[0] + 1

    def separator_notice(self) -> str:
        if self.omitted is None:
            return ""
        first, last = self.omitted
        return (
            f"[ Pages {first}-{last} intentionally omitted. "
            f"Pursuant to Compendium (Third) sec. 721.6, this deposit contains "
            f"the first 25 and the last 25 pages of the program. ]"
        )

    def filing_statement(self) -> str:
        """The sentence to put in the application's note to the Office."""
        if self.mode == MODE_ENTIRE:
            return (
                f"The entire source code for this program is {self.total_pages} "
                "page(s) and is included in full in this deposit."
            )
        return (
            f"The complete program is {self.total_pages} pages. In accordance with "
            "Compendium (Third) sec. 721.6, this deposit contains the first 25 pages "
            f"(pages 1-{self.page_numbers[24] if len(self.page_numbers) > 24 else 25}) "
            f"and the last 25 pages (pages {self.page_numbers[-25]}-{self.total_pages}) "
            "of the source code."
        )


def select_pages(total_pages: int, options: DepositOptions | None = None) -> DepositSelection:
    """Apply the 50-page rule to a laid-out document."""
    options = options or DepositOptions()
    total = max(0, int(total_pages))

    if not options.apply_rule or total <= options.threshold:
        return DepositSelection(MODE_ENTIRE, total, list(range(1, total + 1)))

    head = max(0, options.head_pages)
    tail = max(0, options.tail_pages)
    if head + tail >= total:
        return DepositSelection(MODE_ENTIRE, total, list(range(1, total + 1)))

    head_pages = list(range(1, head + 1))
    tail_pages = list(range(total - tail + 1, total + 1))
    return DepositSelection(
        mode=MODE_HEAD_TAIL,
        total_pages=total,
        page_numbers=head_pages + tail_pages,
        omitted=(head + 1, total - tail),
    )


def files_entirely_omitted(selection: DepositSelection, file_ranges) -> list[str]:
    """Files that fall wholly inside the omitted middle.

    Worth surfacing: this is code the Office will never see, which may
    change how the operator orders the deposit.
    """
    if selection.omitted is None:
        return []
    low, high = selection.omitted
    return [
        r.rel_path
        for r in file_ranges
        if r.first_page >= low and r.last_page <= high
    ]


def files_partially_shown(selection: DepositSelection, file_ranges) -> list[str]:
    """Files that straddle the omission boundary."""
    if selection.omitted is None:
        return []
    low, high = selection.omitted
    out = []
    for r in file_ranges:
        inside = r.first_page >= low and r.last_page <= high
        overlaps = r.first_page <= high and r.last_page >= low
        if overlaps and not inside:
            out.append(r.rel_path)
    return out

"""The estimate: page count, which pages get deposited, and what to change.

The number shown here is not a projection. Estimating runs the same
discovery, stripping and layout the renderer uses and stops just before
writing the PDF, so the page count is exact.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.deposit import MODE_ENTIRE


def _cell(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    return item


class EstimatePanel(QWidget):
    whatIfRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self.page_count = QLabel("-")
        big = QFont()
        big.setPointSize(20)
        big.setBold(True)
        self.page_count.setFont(big)

        self.rule_line = QLabel("Run an estimate to see the page count.")
        self.rule_line.setWordWrap(True)
        self.grid_line = QLabel("")
        self.grid_line.setStyleSheet("color: palette(mid);")

        summary = QGroupBox("Result")
        summary_layout = QVBoxLayout(summary)
        summary_layout.addWidget(self.page_count)
        summary_layout.addWidget(self.rule_line)
        summary_layout.addWidget(self.grid_line)

        self.statement = QLabel("")
        self.statement.setWordWrap(True)
        self.statement.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.statement.setStyleSheet(
            "QLabel { background: palette(base); border: 1px solid palette(mid); padding: 8px; }"
        )
        statement_row = QHBoxLayout()
        statement_row.addWidget(self.statement, 1)
        self.copy_button = QPushButton("Copy")
        self.copy_button.setToolTip("Copy the statement to give the Copyright Office")
        self.copy_button.clicked.connect(self._copy_statement)
        statement_row.addWidget(self.copy_button)
        summary_layout.addWidget(QLabel("Statement for the application:"))
        summary_layout.addLayout(statement_row)

        layout.addWidget(summary)

        what_if = QGroupBox("Page count by comment policy")
        what_if_layout = QVBoxLayout(what_if)
        hint = QLabel(
            "If the whole program fits in the threshold you may deposit all of it, "
            "which is simpler than the first-25/last-25 split."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(mid);")
        what_if_layout.addWidget(hint)

        self.what_if_table = QTableWidget(0, 3)
        self.what_if_table.setHorizontalHeaderLabels(["Policy", "Pages", "Deposit"])
        self.what_if_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.what_if_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.what_if_table.setMaximumHeight(150)
        what_if_layout.addWidget(self.what_if_table)

        self.compare_button = QPushButton("Compare policies")
        self.compare_button.clicked.connect(self.whatIfRequested.emit)
        what_if_layout.addWidget(self.compare_button)
        layout.addWidget(what_if)

        details = QHBoxLayout()

        omitted_box = QGroupBox("Files the Office will not see")
        omitted_layout = QVBoxLayout(omitted_box)
        self.omitted_list = QListWidget()
        omitted_layout.addWidget(self.omitted_list)
        details.addWidget(omitted_box, 1)

        warnings_box = QGroupBox("Warnings")
        warnings_layout = QVBoxLayout(warnings_box)
        self.warnings_list = QListWidget()
        warnings_layout.addWidget(self.warnings_list)
        details.addWidget(warnings_box, 1)

        layout.addLayout(details, 1)

    # -- population --------------------------------------------------------

    def apply_estimate(self, estimate) -> None:
        selection = estimate.selection
        total = estimate.page_count
        self.page_count.setText(f"{total} page{'s' if total != 1 else ''}")

        if selection.mode == MODE_ENTIRE:
            self.rule_line.setText(
                f"At or under the {estimate.settings.deposit.threshold}-page threshold, "
                "so the entire program is deposited."
            )
        else:
            first, last = selection.omitted or (0, 0)
            self.rule_line.setText(
                f"Over the threshold: the deposit contains "
                f"{estimate.settings.deposit.head_pages} + "
                f"{estimate.settings.deposit.tail_pages} pages "
                f"({selection.deposited_pages} sheets); pages {first}-{last} are omitted."
            )
        self.grid_line.setText(
            f"{estimate.geometry_note}   |   {len(estimate.prepared)} files, "
            f"{estimate.layout.rendered_lines} lines "
            f"({estimate.layout.wrapped_lines} wrapped)"
        )
        self.statement.setText(selection.filing_statement())

        self.omitted_list.clear()
        omitted = estimate.omitted_files()
        if omitted:
            self.omitted_list.addItems(omitted)
        else:
            self.omitted_list.addItem("(every file appears in the deposit)")

        self.warnings_list.clear()
        if estimate.warnings:
            self.warnings_list.addItems(estimate.warnings)
        else:
            self.warnings_list.addItem("(no warnings)")

    def apply_what_if(self, rows: list[tuple[str, int, str]]) -> None:
        self.what_if_table.setRowCount(len(rows))
        for row, (label, pages, mode) in enumerate(rows):
            self.what_if_table.setItem(row, 0, _cell(label))
            self.what_if_table.setItem(row, 1, _cell(str(pages)))
            self.what_if_table.setItem(row, 2, _cell(mode))

    def _copy_statement(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.statement.text())

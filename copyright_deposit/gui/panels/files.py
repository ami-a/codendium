"""The file list: what goes in the deposit, and in what order.

The table *is* the order list. Rows can be dragged, nudged with the
buttons, or replaced wholesale by an imported list or the suggested
dependency order. Files nobody named are appended and tinted, so an
automatic decision never passes for a deliberate one.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core import lineranges, ordering
from ...core.discovery import DiscoveredFile, DiscoveryResult
from ...core.ordering import SOURCE_UNLISTED, OrderPlan

COL_INCLUDE = 0
COL_PATH = 1
COL_LANGUAGE = 2
COL_LINES = 3
COL_RANGES = 4
COL_ORIGIN = 5
COL_PAGES = 6

UNLISTED_TINT = QColor(255, 193, 7, 45)
OMITTED_TINT = QColor(128, 128, 128, 40)
PARTIAL_TINT = QColor(64, 140, 255, 45)

RANGE_HINT = (
    "Blank = the whole file. Otherwise list the lines to deposit, using the "
    "line numbers you see in your editor:\n"
    "    1-50, 120-200      two blocks\n"
    "    1-80               one block\n"
    "    305-               from line 305 to the end\n"
    "    -40                the first 40 lines\n"
    "Omitted stretches are marked in the PDF with a dashed rule naming the "
    "missing lines, and the file gets a PARTIAL FILE banner."
)


class ReorderTable(QTableWidget):
    """A table whose rows can be dragged into a new order."""

    orderChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDragDropOverwriteMode(False)
        self.setDropIndicatorShown(True)
        self.verticalHeader().setSectionsMovable(False)

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.source() is not self:
            super().dropEvent(event)
            return

        target = self.indexAt(event.position().toPoint()).row()
        if target < 0:
            target = self.rowCount()

        rows = sorted({index.row() for index in self.selectedIndexes()})
        if not rows:
            event.ignore()
            return

        taken: list[list[QTableWidgetItem | None]] = []
        for row in reversed(rows):
            taken.insert(0, [self.takeItem(row, col) for col in range(self.columnCount())])
            self.removeRow(row)

        target -= sum(1 for row in rows if row < target)
        target = max(0, min(target, self.rowCount()))

        for offset, cells in enumerate(taken):
            self.insertRow(target + offset)
            for col, item in enumerate(cells):
                if item is not None:
                    self.setItem(target + offset, col, item)

        self.clearSelection()
        for offset in range(len(taken)):
            self.selectRow(target + offset)
        event.accept()
        self.orderChanged.emit()


class FilesPanel(QWidget):
    changed = Signal()
    rescanRequested = Signal()
    suggestRequested = Signal()
    rangeError = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        self.rescan_button = QPushButton("Rescan folder")
        self.rescan_button.clicked.connect(self.rescanRequested.emit)
        self.suggest_button = QPushButton("Suggest order")
        self.suggest_button.setToolTip(
            "Order by entry point, then the import / #include graph, so the deposit "
            "has an identifiable beginning"
        )
        self.suggest_button.clicked.connect(self.suggestRequested.emit)
        self.import_button = QPushButton("Import list...")
        self.import_button.clicked.connect(self._import_order)
        self.export_button = QPushButton("Export list...")
        self.export_button.clicked.connect(self._export_order)
        for button in (
            self.rescan_button, self.suggest_button, self.import_button, self.export_button
        ):
            toolbar.addWidget(button)
        toolbar.addStretch(1)

        self.lines_button = QPushButton("Deposit lines...")
        self.lines_button.setToolTip(RANGE_HINT)
        self.lines_button.clicked.connect(self._prompt_ranges)
        self.include_button = QPushButton("Include")
        self.include_button.clicked.connect(lambda: self._set_included(True))
        self.exclude_button = QPushButton("Exclude")
        self.exclude_button.clicked.connect(lambda: self._set_included(False))
        toolbar.addWidget(self.lines_button)
        toolbar.addWidget(self.include_button)
        toolbar.addWidget(self.exclude_button)

        move_bar = QHBoxLayout()
        for label, handler in (
            ("Top", self._move_top),
            ("Up", lambda: self._move(-1)),
            ("Down", lambda: self._move(1)),
            ("Bottom", self._move_bottom),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            move_bar.addWidget(button)
        move_bar.addStretch(1)
        self.summary = QLabel("No folder scanned yet.")
        move_bar.addWidget(self.summary)

        self.table = ReorderTable()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["In", "Path", "Language", "Lines", "Deposit lines", "Origin", "Pages"]
        )
        self.table.horizontalHeaderItem(COL_RANGES).setToolTip(RANGE_HINT)
        self.table.orderChanged.connect(self.changed.emit)
        self.table.itemChanged.connect(self._on_item_changed)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_PATH, QHeaderView.ResizeMode.Stretch)
        for column in (COL_INCLUDE, COL_LANGUAGE, COL_LINES, COL_ORIGIN, COL_PAGES):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_RANGES, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(COL_RANGES, 150)

        layout.addLayout(toolbar)
        layout.addLayout(move_bar)
        layout.addWidget(self.table, 1)

        self._files: dict[str, DiscoveredFile] = {}
        # Range specs are held here, not read back from cells, so they
        # survive a rescan and a reorder.
        self._ranges: dict[str, str] = {}
        self._loading = False

    # -- population --------------------------------------------------------

    def populate(self, discovery: DiscoveryResult, plan: OrderPlan) -> None:
        self._files = discovery.by_path()
        excluded = set(plan.excluded)
        rows = [(item.rel_path, item.source) for item in plan.items]
        rows += [(path, SOURCE_UNLISTED) for path in sorted(excluded)]

        self._loading = True
        try:
            self.table.setRowCount(len(rows))
            for row, (path, origin) in enumerate(rows):
                file = self._files.get(path)
                include = QTableWidgetItem()
                include.setFlags(
                    Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsDragEnabled
                )
                include.setCheckState(
                    Qt.CheckState.Unchecked if path in excluded else Qt.CheckState.Checked
                )
                self.table.setItem(row, COL_INCLUDE, include)

                path_item = QTableWidgetItem(path)
                path_item.setData(Qt.ItemDataRole.UserRole, path)
                path_item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsDragEnabled
                )
                self.table.setItem(row, COL_PATH, path_item)

                self._set_cell(row, COL_LANGUAGE, file.language if file else "")
                self._set_cell(row, COL_LINES, str(file.raw_line_count) if file else "")
                self._set_range_cell(row, self._ranges.get(path, ""))
                self._set_cell(
                    row,
                    COL_ORIGIN,
                    "auto" if origin == SOURCE_UNLISTED else "listed",
                )
                self._set_cell(row, COL_PAGES, "")

                if origin == SOURCE_UNLISTED and path not in excluded:
                    self._tint_row(row, UNLISTED_TINT)
                    path_item.setToolTip(
                        "Not named in the order list; appended automatically."
                    )
                if path in excluded:
                    self._grey_row(row)
        finally:
            self._loading = False

        self._update_summary()
        self.changed.emit()

    def apply_estimate(self, estimate) -> None:
        """Fill in the Pages column and flag files the Office will not see."""
        ranges = {r.rel_path: r for r in estimate.layout.file_ranges}
        omitted = set(estimate.omitted_files())
        partial = set(estimate.split_files())

        self._loading = True
        try:
            for row in range(self.table.rowCount()):
                path = self._path_at(row)
                page_range = ranges.get(path)
                if page_range is None:
                    self._set_cell(row, COL_PAGES, "-")
                    continue
                if page_range.first_page == page_range.last_page:
                    label = str(page_range.first_page)
                else:
                    label = f"{page_range.first_page}-{page_range.last_page}"
                if path in omitted:
                    label += "  (not deposited)"
                elif path in partial:
                    label += "  (part deposited)"
                self._set_cell(row, COL_PAGES, label)
                if path in omitted:
                    self._tint_row(row, OMITTED_TINT)
        finally:
            self._loading = False

    def _set_cell(self, row: int, column: int, text: str) -> None:
        item = QTableWidgetItem(text)
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
        )
        self.table.setItem(row, column, item)

    def _set_range_cell(self, row: int, spec: str) -> None:
        """The one editable column: which lines of this file to deposit."""
        item = QTableWidgetItem(spec)
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
            | Qt.ItemFlag.ItemIsEditable
        )
        # Remember the last accepted value so a bad edit can be reverted.
        item.setData(Qt.ItemDataRole.UserRole, spec)
        if spec:
            item.setBackground(QBrush(PARTIAL_TINT))
            item.setToolTip(f"Only lines {spec} of this file are deposited.")
        else:
            item.setToolTip(RANGE_HINT)
        self.table.setItem(row, COL_RANGES, item)

    def _tint_row(self, row: int, colour: QColor) -> None:
        brush = QBrush(colour)
        path = self._path_at(row)
        for column in range(self.table.columnCount()):
            # A partial-file marker outranks the row tint: it is the more
            # important fact about that cell.
            if column == COL_RANGES and self._ranges.get(path):
                continue
            item = self.table.item(row, column)
            if item is not None:
                item.setBackground(brush)

    def _grey_row(self, row: int) -> None:
        font = QFont()
        font.setStrikeOut(True)
        for column in range(self.table.columnCount()):
            item = self.table.item(row, column)
            if item is not None:
                item.setForeground(QBrush(QColor(128, 128, 128)))
                if column == COL_PATH:
                    item.setFont(font)

    # -- interaction -------------------------------------------------------

    def _path_at(self, row: int) -> str:
        item = self.table.item(row, COL_PATH)
        return item.text() if item is not None else ""

    def _selected_rows(self) -> list[int]:
        return sorted({index.row() for index in self.table.selectedIndexes()})

    def _move(self, delta: int) -> None:
        rows = self._selected_rows()
        if not rows:
            return
        ordered = rows if delta < 0 else list(reversed(rows))
        for row in ordered:
            target = row + delta
            if target < 0 or target >= self.table.rowCount():
                return
            self._swap(row, target)
        self.table.clearSelection()
        for row in rows:
            self.table.selectRow(row + delta)
        self.changed.emit()

    def _swap(self, a: int, b: int) -> None:
        self._loading = True
        try:
            for column in range(self.table.columnCount()):
                item_a = self.table.takeItem(a, column)
                item_b = self.table.takeItem(b, column)
                if item_b is not None:
                    self.table.setItem(a, column, item_b)
                if item_a is not None:
                    self.table.setItem(b, column, item_a)
        finally:
            self._loading = False

    def _move_top(self) -> None:
        self._move_to_edge(top=True)

    def _move_bottom(self) -> None:
        self._move_to_edge(top=False)

    def _move_to_edge(self, top: bool) -> None:
        rows = self._selected_rows()
        if not rows:
            return
        order = self.current_order()
        selected = [order[row] for row in rows]
        remaining = [path for index, path in enumerate(order) if index not in set(rows)]
        new_order = selected + remaining if top else remaining + selected
        self.reorder_to(new_order)

    def _set_included(self, included: bool) -> None:
        self._loading = True
        try:
            for row in self._selected_rows():
                item = self.table.item(row, COL_INCLUDE)
                if item is not None:
                    item.setCheckState(
                        Qt.CheckState.Checked if included else Qt.CheckState.Unchecked
                    )
                if included:
                    self._tint_row(row, QColor(0, 0, 0, 0))
                    for column in range(self.table.columnCount()):
                        cell = self.table.item(row, column)
                        if cell is not None:
                            cell.setForeground(QBrush())
                            cell.setFont(QFont())
                else:
                    self._grey_row(row)
        finally:
            self._loading = False
        self._update_summary()
        self.changed.emit()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading:
            return
        if item.column() == COL_RANGES:
            self._on_range_edited(item)
            return
        if item.column() != COL_INCLUDE:
            return
        row = item.row()
        if item.checkState() == Qt.CheckState.Unchecked:
            self._grey_row(row)
        else:
            self._loading = True
            try:
                for column in range(self.table.columnCount()):
                    cell = self.table.item(row, column)
                    if cell is not None:
                        cell.setForeground(QBrush())
                        cell.setFont(QFont())
            finally:
                self._loading = False
        self._update_summary()
        self.changed.emit()

    def _on_range_edited(self, item: QTableWidgetItem) -> None:
        """Validate an edited range spec; revert and explain if it is bad."""
        row = item.row()
        path = self._path_at(row)
        spec = item.text().strip()
        previous = item.data(Qt.ItemDataRole.UserRole) or ""

        file = self._files.get(path)
        total = file.raw_line_count if file else None
        error = lineranges.validate(spec, total)
        if error:
            self.rangeError.emit(f"{path}: {error}")
            self._loading = True
            try:
                self._set_range_cell(row, previous)
            finally:
                self._loading = False
            return

        if spec:
            # Store the tidied form so the table shows what will be used.
            ranges, _ = lineranges.parse_ranges(spec, total)
            spec = lineranges.format_ranges(ranges, total)
            self._ranges[path] = spec
        else:
            self._ranges.pop(path, None)

        self._loading = True
        try:
            self._set_range_cell(row, spec)
        finally:
            self._loading = False
        self._update_summary()
        self.changed.emit()

    def _prompt_ranges(self) -> None:
        rows = self._selected_rows()
        if not rows:
            return
        current = self._ranges.get(self._path_at(rows[0]), "")
        spec, ok = QInputDialog.getText(
            self,
            "Deposit only part of these files",
            RANGE_HINT + "\n\nLines to deposit:",
            text=current,
        )
        if not ok:
            return
        spec = spec.strip()
        error = lineranges.validate(spec)
        if error:
            QMessageBox.warning(self, "That range is not valid", error)
            return
        self._loading = True
        try:
            for row in rows:
                path = self._path_at(row)
                file = self._files.get(path)
                total = file.raw_line_count if file else None
                if spec:
                    ranges, _ = lineranges.parse_ranges(spec, total)
                    tidied = lineranges.format_ranges(ranges, total)
                    if not ranges:
                        continue
                    self._ranges[path] = tidied
                else:
                    tidied = ""
                    self._ranges.pop(path, None)
                self._set_range_cell(row, tidied)
        finally:
            self._loading = False
        self._update_summary()
        self.changed.emit()

    def _update_summary(self) -> None:
        total = self.table.rowCount()
        included = len(self.included_paths())
        text = f"{included} of {total} file(s) included"
        ranged = sum(1 for path in self.included_paths() if self._ranges.get(path))
        if ranged:
            text += f", {ranged} with a line range"
        self.summary.setText(text)

    # -- order -------------------------------------------------------------

    def current_order(self) -> list[str]:
        return [self._path_at(row) for row in range(self.table.rowCount())]

    def included_paths(self) -> list[str]:
        result = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, COL_INCLUDE)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                result.append(self._path_at(row))
        return result

    def excluded_paths(self) -> list[str]:
        included = set(self.included_paths())
        return [path for path in self.current_order() if path not in included]

    def line_ranges(self) -> dict[str, str]:
        """Per-file range specs, for files that are actually included."""
        included = set(self.included_paths())
        return {
            path: spec
            for path, spec in sorted(self._ranges.items())
            if spec and path in included
        }

    def set_line_ranges(self, ranges: dict[str, str]) -> None:
        self._ranges = {
            path.replace("\\", "/"): spec for path, spec in ranges.items() if spec
        }
        self._loading = True
        try:
            for row in range(self.table.rowCount()):
                self._set_range_cell(row, self._ranges.get(self._path_at(row), ""))
        finally:
            self._loading = False
        self._update_summary()

    def set_included(self, paths: list[str], included: bool) -> None:
        """Include or exclude specific files by path."""
        wanted = set(paths)
        rows = [
            row for row in range(self.table.rowCount()) if self._path_at(row) in wanted
        ]
        if not rows:
            return
        self.table.clearSelection()
        for row in rows:
            self.table.selectRow(row)
        self._set_included(included)

    def reorder_to(self, order: list[str]) -> None:
        """Rearrange existing rows to match `order`; unknown paths keep place."""
        current = self.current_order()
        position = {path: index for index, path in enumerate(current)}
        wanted = [path for path in order if path in position]
        wanted += [path for path in current if path not in set(wanted)]
        if wanted == current:
            return

        self._loading = True
        try:
            snapshot = {
                path: [self.table.takeItem(position[path], col) for col in range(self.table.columnCount())]
                for path in current
            }
            for row, path in enumerate(wanted):
                for column, item in enumerate(snapshot[path]):
                    if item is not None:
                        self.table.setItem(row, column, item)
        finally:
            self._loading = False
        self.changed.emit()

    def _import_order(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import order list", "", "Text files (*.txt *.lst);;All files (*)"
        )
        if not path:
            return
        entries = ordering.parse_order_text(Path(path).read_text(encoding="utf-8"))
        resolved: list[str] = []
        known = set(self.current_order())
        missing: list[str] = []
        for entry in entries:
            normalised = entry.replace("\\", "/").lstrip("./")
            if normalised in known:
                resolved.append(normalised)
                continue
            suffix = "/" + normalised
            hits = [p for p in known if p.endswith(suffix)]
            if len(hits) == 1:
                resolved.append(hits[0])
            elif not hits:
                missing.append(entry)
            else:
                QMessageBox.warning(
                    self,
                    "Ambiguous entry",
                    f"'{entry}' matches {len(hits)} files:\n\n"
                    + "\n".join(hits)
                    + "\n\nUse a fuller path to say which one you mean.",
                )
                missing.append(entry)
        self.reorder_to(resolved)
        if missing:
            QMessageBox.information(
                self,
                "Some entries were not used",
                "These entries did not match a discovered file:\n\n" + "\n".join(missing[:20]),
            )

    def _export_order(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export order list", "deposit_order.txt", "Text files (*.txt)"
        )
        if not path:
            return
        Path(path).write_text(
            ordering.format_order_text(self.included_paths()), encoding="utf-8"
        )

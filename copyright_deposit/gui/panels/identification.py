"""Source/output locations and the identification block.

The Copyright Office requires the program title and version on the first
page of the deposit, so these fields are not optional decoration - they are
part of what makes the filing acceptable.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...config import BuildSettings
from ...core.discovery import git_revision


class _PathRow(QWidget):
    """A line edit with a Browse button."""

    changed = Signal(str)

    def __init__(self, placeholder: str, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.textChanged.connect(self.changed.emit)
        self.button = QPushButton("Browse...")
        self.button.clicked.connect(self._browse)
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.button)

    def _browse(self) -> None:
        start = self.edit.text() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Select folder", start)
        if chosen:
            self.edit.setText(chosen)

    def text(self) -> str:
        return self.edit.text().strip()

    def setText(self, value: str) -> None:
        self.edit.setText(value)


class IdentificationPanel(QWidget):
    sourceChanged = Signal(str)
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)

        locations = QGroupBox("Locations")
        form = QFormLayout(locations)
        self.source = _PathRow("folder containing the source code")
        self.source.changed.connect(self._on_source_changed)
        self.output = _PathRow("where the PDFs are written")
        self.output.changed.connect(lambda _: self.changed.emit())
        self.basename = QLineEdit("deposit")
        self.basename.textChanged.connect(lambda _: self.changed.emit())
        form.addRow("Source folder", self.source)
        form.addRow("Output folder", self.output)
        form.addRow("File name prefix", self.basename)

        identification = QGroupBox("Identification block (printed on page 1)")
        id_form = QFormLayout(identification)

        self.program_name = QLineEdit()
        self.program_name.setPlaceholderText("e.g. Acme Route Planner")
        self.version = QLineEdit("1.0.0")
        self.release_date = QLineEdit(date.today().isoformat())
        self.release_date.setPlaceholderText("YYYY-MM-DD")

        revision_row = QWidget()
        revision_layout = QHBoxLayout(revision_row)
        revision_layout.setContentsMargins(0, 0, 0, 0)
        self.revision = QLineEdit()
        self.revision.setPlaceholderText("optional; pins the exact code deposited")
        self.git_button = QPushButton("From git")
        self.git_button.setToolTip("Read the short commit hash of the source folder")
        self.git_button.clicked.connect(self._fill_revision)
        revision_layout.addWidget(self.revision, 1)
        revision_layout.addWidget(self.git_button)

        self.owner = QLineEdit()
        self.owner.setPlaceholderText("the person or company claiming copyright")
        self.year = QLineEdit(str(date.today().year))
        self.deposit_label = QLineEdit("Deposit Copy - Identifying Portions of Source Code")

        for widget in (
            self.program_name, self.version, self.release_date, self.revision,
            self.owner, self.year, self.deposit_label,
        ):
            widget.textChanged.connect(lambda _: self.changed.emit())

        id_form.addRow("Program name", self.program_name)
        id_form.addRow("Version", self.version)
        id_form.addRow("Release/build date", self.release_date)
        id_form.addRow("Revision/commit", revision_row)
        id_form.addRow("Copyright owner", self.owner)
        id_form.addRow("Copyright year", self.year)
        id_form.addRow("Deposit label", self.deposit_label)

        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet(
            "QLabel { font-family: 'Courier New', monospace; background: palette(base); "
            "border: 1px solid palette(mid); padding: 8px; }"
        )
        id_form.addRow("Preview", self.preview)
        self.changed.connect(self._refresh_preview)

        outer.addWidget(locations)
        outer.addWidget(identification)
        outer.addStretch(1)
        self._refresh_preview()

    # -- helpers -----------------------------------------------------------

    def _on_source_changed(self, value: str) -> None:
        if value and not self.output.text():
            self.output.setText(str(Path(value) / "copyright_deposit_output"))
        if value and not self.program_name.text():
            self.program_name.setText(Path(value).name)
        self.sourceChanged.emit(value)
        self.changed.emit()

    def _fill_revision(self) -> None:
        revision = git_revision(self.source.text())
        self.revision.setText(revision or "")
        if not revision:
            self.revision.setPlaceholderText("no git revision found for this folder")

    def _refresh_preview(self) -> None:
        settings = BuildSettings()
        self.collect(settings)
        self.preview.setText("\n".join(settings.header.lines()))

    # -- settings ----------------------------------------------------------

    def collect(self, settings: BuildSettings) -> None:
        settings.source_root = self.source.text()
        settings.output_dir = self.output.text()
        settings.output_basename = self.basename.text().strip() or "deposit"
        header = settings.header
        header.program_name = self.program_name.text().strip()
        header.version = self.version.text().strip()
        header.release_date = self.release_date.text().strip()
        header.revision = self.revision.text().strip()
        header.copyright_owner = self.owner.text().strip()
        header.copyright_year = self.year.text().strip()
        header.deposit_label = self.deposit_label.text().strip()

    def apply(self, settings: BuildSettings) -> None:
        blockers = [
            self.source.edit, self.output.edit, self.basename, self.program_name,
            self.version, self.release_date, self.revision, self.owner,
            self.year, self.deposit_label,
        ]
        for widget in blockers:
            widget.blockSignals(True)
        try:
            self.source.setText(settings.source_root)
            self.output.setText(settings.output_dir)
            self.basename.setText(settings.output_basename)
            header = settings.header
            self.program_name.setText(header.program_name)
            self.version.setText(header.version)
            self.release_date.setText(header.release_date)
            self.revision.setText(header.revision)
            self.owner.setText(header.copyright_owner)
            self.year.setText(header.copyright_year)
            self.deposit_label.setText(header.deposit_label)
        finally:
            for widget in blockers:
                widget.blockSignals(False)
        self._refresh_preview()
        self.changed.emit()

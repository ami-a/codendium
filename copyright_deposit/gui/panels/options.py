"""Every policy toggle, grouped by what it affects.

The comment policy defaults to removing everything, with independent
switches for comments and docstrings so the operator can trade page count
against disclosure without editing any source.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...config import DEFAULT_EXTENSIONS, BuildSettings


class OptionsPanel(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)

        layout.addWidget(self._comment_group())
        layout.addWidget(self._grid_group())
        layout.addWidget(self._deposit_group())
        layout.addWidget(self._discovery_group())
        layout.addWidget(self._redaction_group())
        layout.addWidget(self._scanning_group())
        layout.addStretch(1)

        scroll.setWidget(inner)
        outer.addWidget(scroll)
        self._wire()

    # -- groups ------------------------------------------------------------

    def _comment_group(self) -> QGroupBox:
        box = QGroupBox("Comment policy")
        form = QVBoxLayout(box)

        self.strip_comments = QCheckBox("Remove comments")
        self.strip_docstrings = QCheckBox("Remove docstrings")
        self.preserve_legal = QCheckBox(
            "Keep leading comment blocks that carry a copyright or licence notice"
        )
        self.preserve_shebang = QCheckBox("Keep the #! line")
        self.trim_trailing = QCheckBox("Trim trailing whitespace")
        self.expand_tabs = QCheckBox("Expand tabs")

        self.strip_comments.setChecked(True)
        self.strip_docstrings.setChecked(True)
        self.preserve_shebang.setChecked(True)
        self.trim_trailing.setChecked(True)
        self.expand_tabs.setChecked(True)

        self.tab_width = QSpinBox()
        self.tab_width.setRange(1, 16)
        self.tab_width.setValue(4)

        self.collapse_blanks = QCheckBox("Collapse runs of blank lines to at most")
        self.collapse_blanks.setChecked(True)
        self.max_blank_run = QSpinBox()
        self.max_blank_run.setRange(0, 10)
        self.max_blank_run.setValue(1)

        form.addWidget(self.strip_comments)
        form.addWidget(self.strip_docstrings)
        form.addWidget(self.preserve_legal)
        form.addWidget(self.preserve_shebang)

        blank_row = QHBoxLayout()
        blank_row.addWidget(self.collapse_blanks)
        blank_row.addWidget(self.max_blank_run)
        blank_row.addWidget(QLabel("line(s)"))
        blank_row.addStretch(1)
        form.addLayout(blank_row)

        tab_row = QHBoxLayout()
        tab_row.addWidget(self.expand_tabs)
        tab_row.addWidget(QLabel("to"))
        tab_row.addWidget(self.tab_width)
        tab_row.addWidget(QLabel("spaces"))
        tab_row.addStretch(1)
        form.addLayout(tab_row)
        form.addWidget(self.trim_trailing)

        note = QLabel(
            "Python stripping is verified: if removing comments would change the "
            "parse tree, that file is kept verbatim and a warning is raised."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(placeholderText);")
        form.addWidget(note)
        return box

    def _grid_group(self) -> QGroupBox:
        box = QGroupBox("Page grid")
        form = QFormLayout(box)

        self.page_size = QComboBox()
        self.page_size.addItems(["letter", "a4"])

        font_row = QWidget()
        font_layout = QHBoxLayout(font_row)
        font_layout.setContentsMargins(0, 0, 0, 0)
        self.font_name = QLineEdit("Courier")
        self.font_name.setToolTip(
            "'Courier' is a built-in PDF font: always monospaced, no embedding "
            "needed. You may also point at a monospaced .ttf file."
        )
        font_button = QPushButton("Choose .ttf...")
        font_button.clicked.connect(self._choose_font)
        font_layout.addWidget(self.font_name, 1)
        font_layout.addWidget(font_button)

        self.font_size = QDoubleSpinBox()
        self.font_size.setRange(6.0, 14.0)
        self.font_size.setSingleStep(0.5)
        self.font_size.setValue(9.5)

        self.lines_per_page = QSpinBox()
        self.lines_per_page.setRange(20, 80)
        self.lines_per_page.setValue(40)

        self.margin = QDoubleSpinBox()
        self.margin.setRange(18.0, 108.0)
        self.margin.setValue(54.0)

        self.show_line_numbers = QCheckBox("Show original source line numbers")
        self.show_file_banners = QCheckBox("Print a FILE: banner at each boundary")
        self.show_file_banners.setChecked(True)
        self.running_header = QCheckBox("Running header with program name")
        self.running_header.setChecked(True)
        self.page_numbers = QCheckBox("Continuous page numbers")
        self.page_numbers.setChecked(True)
        self.new_page_per_file = QCheckBox("Start each file on a new page")

        form.addRow("Page size", self.page_size)
        form.addRow("Font", font_row)
        form.addRow("Font size (pt)", self.font_size)
        form.addRow("Lines per page", self.lines_per_page)
        form.addRow("Margin (pt)", self.margin)
        form.addRow("", self.show_line_numbers)
        form.addRow("", self.show_file_banners)
        form.addRow("", self.running_header)
        form.addRow("", self.page_numbers)
        form.addRow("", self.new_page_per_file)

        guidance = QLabel(
            "The Office asks for a monospaced face at roughly 9-10 pt and about "
            "40 lines per page. Compressing more lines onto a page to disclose "
            "less is not permitted."
        )
        guidance.setWordWrap(True)
        guidance.setStyleSheet("color: palette(placeholderText);")
        form.addRow(guidance)
        return box

    def _deposit_group(self) -> QGroupBox:
        box = QGroupBox("Deposit rule (Compendium sec. 721.6)")
        form = QFormLayout(box)

        self.apply_rule = QCheckBox(
            "Apply the rule: whole program at or under the threshold, otherwise first/last pages"
        )
        self.apply_rule.setChecked(True)
        self.threshold = QSpinBox()
        self.threshold.setRange(1, 500)
        self.threshold.setValue(50)
        self.head_pages = QSpinBox()
        self.head_pages.setRange(0, 250)
        self.head_pages.setValue(25)
        self.tail_pages = QSpinBox()
        self.tail_pages.setRange(0, 250)
        self.tail_pages.setValue(25)
        self.separator_page = QCheckBox("Insert a sheet noting which pages were omitted")
        self.separator_page.setChecked(True)

        form.addRow(self.apply_rule)
        form.addRow("Threshold (pages)", self.threshold)
        form.addRow("First pages", self.head_pages)
        form.addRow("Last pages", self.tail_pages)
        form.addRow("", self.separator_page)
        return box

    def _discovery_group(self) -> QGroupBox:
        box = QGroupBox("Which files to include")
        form = QFormLayout(box)

        self.extensions = QLineEdit(" ".join(DEFAULT_EXTENSIONS))
        self.extensions.setToolTip("Space-separated list of file extensions")
        self.respect_gitignore = QCheckBox("Respect .gitignore")
        self.respect_gitignore.setChecked(True)
        self.skip_minified = QCheckBox("Skip minified and generated files")
        self.skip_minified.setChecked(True)
        self.max_size = QSpinBox()
        self.max_size.setRange(1, 64)
        self.max_size.setValue(2)
        self.max_size.setSuffix(" MB")
        self.ignore_dirs = QPlainTextEdit()
        self.ignore_dirs.setPlaceholderText("one directory name per line")
        self.ignore_dirs.setMaximumHeight(90)

        form.addRow("Extensions", self.extensions)
        form.addRow("", self.respect_gitignore)
        form.addRow("", self.skip_minified)
        form.addRow("Maximum file size", self.max_size)
        form.addRow("Ignored folders", self.ignore_dirs)
        return box

    def _redaction_group(self) -> QGroupBox:
        box = QGroupBox("Trade-secret redaction (Compendium sec. 721.7)")
        form = QFormLayout(box)

        self.redaction_enabled = QCheckBox("Black out marked material")
        self.begin_marker = QLineEdit("COPYRIGHT-REDACT-BEGIN")
        self.end_marker = QLineEdit("COPYRIGHT-REDACT-END")
        self.redaction_regexes = QPlainTextEdit()
        self.redaction_regexes.setPlaceholderText("one regular expression per line")
        self.redaction_regexes.setMaximumHeight(80)
        self.manual_lines = QPlainTextEdit()
        self.manual_lines.setPlaceholderText("path/to/file.py:42 - added from the Pre-flight tab")
        self.manual_lines.setMaximumHeight(80)

        form.addRow(self.redaction_enabled)
        form.addRow("Begin marker", self.begin_marker)
        form.addRow("End marker", self.end_marker)
        form.addRow("Patterns", self.redaction_regexes)
        form.addRow("Specific lines", self.manual_lines)

        note = QLabel(
            "Redacted text is never written into the PDF, so it cannot be copied "
            "or extracted. Blocked-out material must stay at or under 49% of the "
            "deposited text."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(placeholderText);")
        form.addRow(note)
        return box

    def _scanning_group(self) -> QGroupBox:
        box = QGroupBox("Pre-flight checks")
        layout = QVBoxLayout(box)
        self.scan_secrets = QCheckBox("Scan for credentials and personal data")
        self.scan_secrets.setChecked(True)
        self.scan_third_party = QCheckBox("Scan for third-party or generated code")
        self.scan_third_party.setChecked(True)
        self.block_on_secrets = QCheckBox("Refuse to build while credentials are unresolved")
        self.block_on_secrets.setChecked(True)
        layout.addWidget(self.scan_secrets)
        layout.addWidget(self.scan_third_party)
        layout.addWidget(self.block_on_secrets)

        note = QLabel(
            "A deposit becomes a public record. Anything left in the code can be "
            "read by anyone who inspects the filing."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(placeholderText);")
        layout.addWidget(note)
        return box

    # -- wiring ------------------------------------------------------------

    def _wire(self) -> None:
        checkboxes = [
            self.strip_comments, self.strip_docstrings, self.preserve_legal,
            self.preserve_shebang, self.trim_trailing, self.expand_tabs,
            self.collapse_blanks, self.show_line_numbers, self.show_file_banners,
            self.running_header, self.page_numbers, self.new_page_per_file,
            self.apply_rule, self.separator_page, self.respect_gitignore,
            self.skip_minified, self.redaction_enabled, self.scan_secrets,
            self.scan_third_party, self.block_on_secrets,
        ]
        for box in checkboxes:
            box.toggled.connect(lambda _: self.changed.emit())
        for spin in (
            self.tab_width, self.max_blank_run, self.lines_per_page,
            self.threshold, self.head_pages, self.tail_pages, self.max_size,
        ):
            spin.valueChanged.connect(lambda _: self.changed.emit())
        for spin in (self.font_size, self.margin):
            spin.valueChanged.connect(lambda _: self.changed.emit())
        for edit in (self.font_name, self.extensions, self.begin_marker, self.end_marker):
            edit.textChanged.connect(lambda _: self.changed.emit())
        for text in (self.redaction_regexes, self.manual_lines, self.ignore_dirs):
            text.textChanged.connect(self.changed.emit)
        self.page_size.currentTextChanged.connect(lambda _: self.changed.emit())

        self.collapse_blanks.toggled.connect(self.max_blank_run.setEnabled)
        self.expand_tabs.toggled.connect(self.tab_width.setEnabled)

    def _choose_font(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a monospaced TrueType font", "", "TrueType fonts (*.ttf)"
        )
        if path:
            self.font_name.setText(path)

    # -- settings ----------------------------------------------------------

    def collect(self, settings: BuildSettings) -> None:
        transform = settings.transform
        transform.strip_comments = self.strip_comments.isChecked()
        transform.strip_docstrings = self.strip_docstrings.isChecked()
        transform.preserve_legal_headers = self.preserve_legal.isChecked()
        transform.preserve_shebang = self.preserve_shebang.isChecked()
        transform.collapse_blank_runs = self.collapse_blanks.isChecked()
        transform.max_blank_run = self.max_blank_run.value()
        transform.trim_trailing_whitespace = self.trim_trailing.isChecked()
        transform.expand_tabs = self.expand_tabs.isChecked()
        transform.tab_width = self.tab_width.value()

        layout = settings.layout
        layout.page_size = self.page_size.currentText()
        layout.font_name = self.font_name.text().strip() or "Courier"
        layout.font_size = self.font_size.value()
        layout.lines_per_page = self.lines_per_page.value()
        layout.margin = self.margin.value()
        layout.show_line_numbers = self.show_line_numbers.isChecked()
        layout.show_file_banners = self.show_file_banners.isChecked()
        layout.running_header = self.running_header.isChecked()
        layout.page_numbers = self.page_numbers.isChecked()
        layout.start_files_on_new_page = self.new_page_per_file.isChecked()

        deposit = settings.deposit
        deposit.apply_rule = self.apply_rule.isChecked()
        deposit.threshold = self.threshold.value()
        deposit.head_pages = self.head_pages.value()
        deposit.tail_pages = self.tail_pages.value()
        deposit.separator_page = self.separator_page.isChecked()

        discovery = settings.discovery
        extensions = [e if e.startswith(".") else f".{e}" for e in self.extensions.text().split()]
        discovery.extensions = extensions or list(DEFAULT_EXTENSIONS)
        discovery.respect_gitignore = self.respect_gitignore.isChecked()
        discovery.skip_minified = self.skip_minified.isChecked()
        discovery.max_file_bytes = self.max_size.value() * 1024 * 1024
        ignore_text = self.ignore_dirs.toPlainText().strip()
        if ignore_text:
            discovery.ignore_dirs = [line.strip() for line in ignore_text.splitlines() if line.strip()]

        redaction = settings.redaction
        redaction.enabled = self.redaction_enabled.isChecked()
        redaction.begin_marker = self.begin_marker.text().strip()
        redaction.end_marker = self.end_marker.text().strip()
        redaction.regexes = [
            line.strip() for line in self.redaction_regexes.toPlainText().splitlines() if line.strip()
        ]
        redaction.manual_lines = [
            line.strip() for line in self.manual_lines.toPlainText().splitlines() if line.strip()
        ]

        scan = settings.scan
        scan.scan_secrets = self.scan_secrets.isChecked()
        scan.scan_third_party = self.scan_third_party.isChecked()
        scan.block_on_secrets = self.block_on_secrets.isChecked()

    def apply(self, settings: BuildSettings) -> None:
        self.blockSignals(True)
        try:
            transform = settings.transform
            self.strip_comments.setChecked(transform.strip_comments)
            self.strip_docstrings.setChecked(transform.strip_docstrings)
            self.preserve_legal.setChecked(transform.preserve_legal_headers)
            self.preserve_shebang.setChecked(transform.preserve_shebang)
            self.collapse_blanks.setChecked(transform.collapse_blank_runs)
            self.max_blank_run.setValue(transform.max_blank_run)
            self.trim_trailing.setChecked(transform.trim_trailing_whitespace)
            self.expand_tabs.setChecked(transform.expand_tabs)
            self.tab_width.setValue(transform.tab_width)

            layout = settings.layout
            self.page_size.setCurrentText(layout.page_size)
            self.font_name.setText(layout.font_name)
            self.font_size.setValue(layout.font_size)
            self.lines_per_page.setValue(layout.lines_per_page)
            self.margin.setValue(layout.margin)
            self.show_line_numbers.setChecked(layout.show_line_numbers)
            self.show_file_banners.setChecked(layout.show_file_banners)
            self.running_header.setChecked(layout.running_header)
            self.page_numbers.setChecked(layout.page_numbers)
            self.new_page_per_file.setChecked(layout.start_files_on_new_page)

            deposit = settings.deposit
            self.apply_rule.setChecked(deposit.apply_rule)
            self.threshold.setValue(deposit.threshold)
            self.head_pages.setValue(deposit.head_pages)
            self.tail_pages.setValue(deposit.tail_pages)
            self.separator_page.setChecked(deposit.separator_page)

            discovery = settings.discovery
            self.extensions.setText(" ".join(discovery.extensions))
            self.respect_gitignore.setChecked(discovery.respect_gitignore)
            self.skip_minified.setChecked(discovery.skip_minified)
            self.max_size.setValue(max(1, discovery.max_file_bytes // (1024 * 1024)))
            self.ignore_dirs.setPlainText("\n".join(discovery.ignore_dirs))

            redaction = settings.redaction
            self.redaction_enabled.setChecked(redaction.enabled)
            self.begin_marker.setText(redaction.begin_marker)
            self.end_marker.setText(redaction.end_marker)
            self.redaction_regexes.setPlainText("\n".join(redaction.regexes))
            self.manual_lines.setPlainText("\n".join(redaction.manual_lines))

            scan = settings.scan
            self.scan_secrets.setChecked(scan.scan_secrets)
            self.scan_third_party.setChecked(scan.scan_third_party)
            self.block_on_secrets.setChecked(scan.block_on_secrets)
        finally:
            self.blockSignals(False)
        self.changed.emit()

    def queue_redactions(self, locations: list[str]) -> None:
        """Add 'path:line' entries from the Pre-flight tab."""
        existing = [
            line.strip() for line in self.manual_lines.toPlainText().splitlines() if line.strip()
        ]
        for location in locations:
            if location not in existing:
                existing.append(location)
        self.manual_lines.setPlainText("\n".join(existing))
        self.redaction_enabled.setChecked(True)

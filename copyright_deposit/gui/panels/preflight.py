"""Pre-flight findings, with the two actions that actually resolve them.

A credential can be blocked out (which queues a redaction) or acknowledged.
A third-party file can be dropped from the deposit. Anything merely noted
and left alone stays visible, because the point is to force a decision
before the filing rather than after it.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.scanning import SEVERITY_HIGH, SEVERITY_LOW, SEVERITY_MEDIUM, Finding

_SEVERITY_COLOUR = {
    SEVERITY_HIGH: QColor(220, 53, 69),
    SEVERITY_MEDIUM: QColor(214, 143, 0),
    SEVERITY_LOW: QColor(120, 120, 120),
}


def _read_only(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    return item


class PreflightPanel(QWidget):
    redactRequested = Signal(list)   # ["path:line", ...]
    excludeRequested = Signal(list)  # ["path", ...]
    ignoreChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self.headline = QLabel("Run an estimate to check the selected files.")
        self.headline.setWordWrap(True)
        layout.addWidget(self.headline)

        layout.addWidget(self._secrets_group(), 1)
        layout.addWidget(self._third_party_group(), 1)

        self._secret_findings: list[Finding] = []
        self._third_party_findings: list[Finding] = []
        self._ignored: set[str] = set()

    # -- construction ------------------------------------------------------

    def _secrets_group(self) -> QGroupBox:
        box = QGroupBox("Credentials and personal data")
        layout = QVBoxLayout(box)

        note = QLabel(
            "A deposit is a public record. Block out or remove anything here "
            "before filing."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(mid);")
        layout.addWidget(note)

        self.secrets_table = QTableWidget(0, 5)
        self.secrets_table.setHorizontalHeaderLabels(
            ["Severity", "Location", "What was found", "Excerpt", "Acknowledged"]
        )
        self.secrets_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.secrets_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.secrets_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.secrets_table.itemChanged.connect(self._on_ignore_toggled)
        layout.addWidget(self.secrets_table, 1)

        buttons = QHBoxLayout()
        redact = QPushButton("Black out selected")
        redact.setToolTip("Queue these lines for redaction under Compendium sec. 721.7")
        redact.clicked.connect(self._emit_redactions)
        acknowledge = QPushButton("Acknowledge selected")
        acknowledge.setToolTip("Mark as reviewed so it no longer blocks the build")
        acknowledge.clicked.connect(lambda: self._set_ignored(True))
        unacknowledge = QPushButton("Un-acknowledge selected")
        unacknowledge.clicked.connect(lambda: self._set_ignored(False))
        buttons.addWidget(redact)
        buttons.addWidget(acknowledge)
        buttons.addWidget(unacknowledge)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return box

    def _third_party_group(self) -> QGroupBox:
        box = QGroupBox("Possible third-party or generated code")
        layout = QVBoxLayout(box)

        note = QLabel(
            "A registration only covers your own authorship. Exclude anything "
            "you did not write, or disclaim it in the application."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(mid);")
        layout.addWidget(note)

        self.third_party_table = QTableWidget(0, 4)
        self.third_party_table.setHorizontalHeaderLabels(
            ["Severity", "File", "Rule", "Why it was flagged"]
        )
        self.third_party_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.third_party_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.third_party_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.third_party_table, 1)

        buttons = QHBoxLayout()
        exclude = QPushButton("Exclude these files from the deposit")
        exclude.clicked.connect(self._emit_exclusions)
        buttons.addWidget(exclude)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return box

    # -- population --------------------------------------------------------

    def apply_estimate(self, estimate) -> None:
        self._secret_findings = estimate.scan.sorted_secrets()
        self._third_party_findings = estimate.scan.sorted_third_party()

        self.secrets_table.blockSignals(True)
        try:
            self.secrets_table.setRowCount(len(self._secret_findings))
            for row, finding in enumerate(self._secret_findings):
                severity = _read_only(finding.severity)
                severity.setForeground(
                    QBrush(_SEVERITY_COLOUR.get(finding.severity, QColor(120, 120, 120)))
                )
                self.secrets_table.setItem(row, 0, severity)
                self.secrets_table.setItem(row, 1, _read_only(finding.location()))
                self.secrets_table.setItem(row, 2, _read_only(finding.detail))
                self.secrets_table.setItem(row, 3, _read_only(finding.excerpt))
                acknowledged = QTableWidgetItem()
                acknowledged.setFlags(
                    Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                )
                acknowledged.setCheckState(
                    Qt.CheckState.Checked
                    if finding.id in self._ignored
                    else Qt.CheckState.Unchecked
                )
                acknowledged.setData(Qt.ItemDataRole.UserRole, finding.id)
                self.secrets_table.setItem(row, 4, acknowledged)
        finally:
            self.secrets_table.blockSignals(False)

        self.third_party_table.setRowCount(len(self._third_party_findings))
        for row, finding in enumerate(self._third_party_findings):
            severity = _read_only(finding.severity)
            severity.setForeground(
                QBrush(_SEVERITY_COLOUR.get(finding.severity, QColor(120, 120, 120)))
            )
            self.third_party_table.setItem(row, 0, severity)
            self.third_party_table.setItem(row, 1, _read_only(finding.rel_path))
            self.third_party_table.setItem(row, 2, _read_only(finding.rule))
            self.third_party_table.setItem(row, 3, _read_only(finding.detail))

        self._refresh_headline()

    def _refresh_headline(self) -> None:
        blocking = [
            f
            for f in self._secret_findings
            if f.severity == SEVERITY_HIGH and f.id not in self._ignored
        ]
        parts = []
        if blocking:
            parts.append(f"{len(blocking)} unresolved credential finding(s) - the build is blocked")
        elif self._secret_findings:
            parts.append(f"{len(self._secret_findings)} credential/PII finding(s), all reviewed")
        else:
            parts.append("No credentials or personal data found")
        if self._third_party_findings:
            parts.append(f"{len(self._third_party_findings)} third-party indicator(s)")
        self.headline.setText("  |  ".join(parts))

    # -- actions -----------------------------------------------------------

    def _selected_secret_findings(self) -> list[Finding]:
        rows = sorted({index.row() for index in self.secrets_table.selectedIndexes()})
        return [self._secret_findings[row] for row in rows if row < len(self._secret_findings)]

    def _emit_redactions(self) -> None:
        locations = [f.location() for f in self._selected_secret_findings()]
        if locations:
            self.redactRequested.emit(locations)

    def _emit_exclusions(self) -> None:
        rows = sorted({index.row() for index in self.third_party_table.selectedIndexes()})
        paths = [
            self._third_party_findings[row].rel_path
            for row in rows
            if row < len(self._third_party_findings)
        ]
        if paths:
            self.excludeRequested.emit(sorted(set(paths)))

    def _set_ignored(self, ignored: bool) -> None:
        rows = sorted({index.row() for index in self.secrets_table.selectedIndexes()})
        self.secrets_table.blockSignals(True)
        try:
            for row in rows:
                item = self.secrets_table.item(row, 4)
                if item is None:
                    continue
                item.setCheckState(
                    Qt.CheckState.Checked if ignored else Qt.CheckState.Unchecked
                )
                finding_id = item.data(Qt.ItemDataRole.UserRole)
                if ignored:
                    self._ignored.add(finding_id)
                else:
                    self._ignored.discard(finding_id)
        finally:
            self.secrets_table.blockSignals(False)
        self._refresh_headline()
        self.ignoreChanged.emit()

    def _on_ignore_toggled(self, item: QTableWidgetItem) -> None:
        if item.column() != 4:
            return
        finding_id = item.data(Qt.ItemDataRole.UserRole)
        if not finding_id:
            return
        if item.checkState() == Qt.CheckState.Checked:
            self._ignored.add(finding_id)
        else:
            self._ignored.discard(finding_id)
        self._refresh_headline()
        self.ignoreChanged.emit()

    def ignored_ids(self) -> list[str]:
        return sorted(self._ignored)

    def set_ignored_ids(self, ids: list[str]) -> None:
        self._ignored = set(ids)
        self._refresh_headline()

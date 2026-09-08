"""Main window: wires the panels to the pipeline.

Only one worker runs at a time and the actions are disabled while it does,
which keeps the shared pipeline cache single-writer without any locking.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import DISPLAY_NAME, __version__
from ..config import BuildSettings
from ..core.pipeline import Pipeline
from .history import HistoryStore, RunRecord
from .panels.estimate import EstimatePanel
from .panels.files import FilesPanel
from .panels.identification import IdentificationPanel
from .panels.options import OptionsPanel
from .panels.preflight import PreflightPanel
from .workers import (
    BuildWorker,
    DiscoverWorker,
    EstimateWorker,
    SuggestOrderWorker,
    WhatIfWorker,
)


class HistoryDialog(QDialog):
    def __init__(self, runs: list[RunRecord], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Previous builds")
        self.resize(640, 420)
        self.selected: RunRecord | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("Open a previous build to restore the exact settings it used.")
        )
        self.list = QListWidget()
        for run in runs:
            item = QListWidgetItem(run.label())
            item.setData(Qt.ItemDataRole.UserRole, run)
            item.setToolTip(
                f"{run.source_root}\n"
                f"{run.deposit_pages} page(s) deposited ({run.deposit_mode})\n"
                + "\n".join(run.outputs)
            )
            self.list.addItem(item)
        self.list.itemDoubleClicked.connect(lambda _: self.accept())
        layout.addWidget(self.list, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:
        item = self.list.currentItem()
        if item is not None:
            self.selected = item.data(Qt.ItemDataRole.UserRole)
        super().accept()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{DISPLAY_NAME} {__version__}")
        self.resize(1120, 820)

        self.pipeline = Pipeline()
        self.history = HistoryStore()
        self._worker = None
        self._estimate = None
        self._discovery = None

        self.identification = IdentificationPanel()
        self.files = FilesPanel()
        self.options = OptionsPanel()
        self.preflight = PreflightPanel()
        self.estimate_panel = EstimatePanel()

        self.tabs = QTabWidget()
        self.tabs.addTab(self.identification, "1. Program")
        self.tabs.addTab(self.files, "2. Files and order")
        self.tabs.addTab(self.options, "3. Options")
        self.tabs.addTab(self.preflight, "4. Pre-flight")
        self.tabs.addTab(self.estimate_panel, "5. Estimate and build")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.addWidget(self.tabs, 1)
        layout.addLayout(self._action_bar())
        self.setCentralWidget(container)

        self._build_menu()
        self._connect()
        self._set_status("Choose a source folder to begin.")

    # -- construction ------------------------------------------------------

    def _action_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.setVisible(False)

        self.estimate_button = QPushButton("Estimate pages")
        self.estimate_button.setToolTip("Exact page count without writing a PDF (Ctrl+E)")
        self.estimate_button.clicked.connect(self.run_estimate)

        self.build_button = QPushButton("Build deposit")
        self.build_button.setToolTip("Render the PDFs, manifest and summary (Ctrl+B)")
        self.build_button.clicked.connect(self.run_build)
        self.build_button.setDefault(True)

        bar.addWidget(self.status, 1)
        bar.addWidget(self.progress)
        bar.addWidget(self.estimate_button)
        bar.addWidget(self.build_button)
        return bar

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        new_action = QAction("&New settings", self)
        new_action.setShortcut(QKeySequence.StandardKey.New)
        new_action.triggered.connect(self.reset_settings)
        file_menu.addAction(new_action)

        file_menu.addSeparator()
        save_profile = QAction("&Save profile...", self)
        save_profile.setShortcut(QKeySequence.StandardKey.Save)
        save_profile.triggered.connect(self.save_profile)
        file_menu.addAction(save_profile)

        load_profile = QAction("&Load profile...", self)
        load_profile.setShortcut(QKeySequence.StandardKey.Open)
        load_profile.triggered.connect(self.load_profile)
        file_menu.addAction(load_profile)

        delete_profile = QAction("&Delete profile...", self)
        delete_profile.triggered.connect(self.delete_profile)
        file_menu.addAction(delete_profile)

        file_menu.addSeparator()
        history_action = QAction("Previous &builds...", self)
        history_action.setShortcut("Ctrl+H")
        history_action.triggered.connect(self.show_history)
        file_menu.addAction(history_action)

        file_menu.addSeparator()
        export_settings = QAction("&Export settings to JSON...", self)
        export_settings.triggered.connect(self.export_settings)
        file_menu.addAction(export_settings)
        import_settings = QAction("&Import settings from JSON...", self)
        import_settings.triggered.connect(self.import_settings)
        file_menu.addAction(import_settings)

        file_menu.addSeparator()
        quit_action = QAction("E&xit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        build_menu = self.menuBar().addMenu("&Build")
        estimate_action = QAction("&Estimate pages", self)
        estimate_action.setShortcut("Ctrl+E")
        estimate_action.triggered.connect(self.run_estimate)
        build_menu.addAction(estimate_action)

        build_action = QAction("&Build deposit", self)
        build_action.setShortcut("Ctrl+B")
        build_action.triggered.connect(self.run_build)
        build_menu.addAction(build_action)

        compare_action = QAction("&Compare comment policies", self)
        compare_action.triggered.connect(self.run_what_if)
        build_menu.addAction(compare_action)

        help_menu = self.menuBar().addMenu("&Help")
        about_action = QAction("&About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def _connect(self) -> None:
        self.identification.sourceChanged.connect(self._on_source_changed)
        self.identification.changed.connect(self._mark_stale)
        self.options.changed.connect(self._mark_stale)
        self.files.changed.connect(self._mark_stale)
        self.files.rescanRequested.connect(self.rescan)
        self.files.suggestRequested.connect(self.suggest_order)
        self.files.rangeError.connect(self._set_status)
        self.preflight.redactRequested.connect(self._queue_redactions)
        self.preflight.excludeRequested.connect(self._exclude_files)
        self.preflight.ignoreChanged.connect(self._mark_stale)
        self.estimate_panel.whatIfRequested.connect(self.run_what_if)

    # -- settings ----------------------------------------------------------

    def collect_settings(self) -> BuildSettings:
        settings = BuildSettings()
        self.identification.collect(settings)
        self.options.collect(settings)
        # The table is the order list: included rows, in their shown order.
        settings.order_entries = self.files.included_paths()
        settings.excluded = self.files.excluded_paths()
        settings.line_ranges = self.files.line_ranges()
        settings.include_unlisted = True
        settings.scan.ignored_findings = self.preflight.ignored_ids()
        return settings

    def apply_settings(self, settings: BuildSettings) -> None:
        self.identification.apply(settings)
        self.options.apply(settings)
        self.preflight.set_ignored_ids(settings.scan.ignored_findings)
        # Ranges must be in place before the rescan repopulates the table,
        # so restored rows show their selection immediately.
        self.files.set_line_ranges(settings.line_ranges)
        if settings.source_root and Path(settings.source_root).is_dir():
            self.rescan(then_order=settings.order_entries)

    def reset_settings(self) -> None:
        self.files.set_line_ranges({})
        self.apply_settings(BuildSettings())
        self.files.table.setRowCount(0)
        self._set_status("Settings reset.")

    # -- status / worker plumbing -----------------------------------------

    def _set_status(self, message: str) -> None:
        self.status.setText(message)

    def _mark_stale(self) -> None:
        if self._estimate is not None:
            self._set_status("Settings changed - the estimate is out of date.")
            self._estimate = None

    def _busy(self, busy: bool) -> None:
        for widget in (self.estimate_button, self.build_button, self.tabs):
            widget.setEnabled(not busy)
        self.progress.setVisible(busy)
        if not busy:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)

    def _on_progress(self, stage: str, current: int, total: int) -> None:
        self._set_status(f"{stage}...")
        if total > 1:
            self.progress.setRange(0, total)
            self.progress.setValue(current)
        else:
            self.progress.setRange(0, 0)

    def _on_failure(self, message: str) -> None:
        self._busy(False)
        self._worker = None
        self._set_status("Failed.")
        QMessageBox.critical(self, "Something went wrong", message)

    def _start(self, worker) -> bool:
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "Busy", "Another task is still running.")
            return False
        self._worker = worker
        worker.progressed.connect(self._on_progress)
        worker.failed.connect(self._on_failure)
        self._busy(True)
        worker.start()
        return True

    def _require_source(self) -> BuildSettings | None:
        settings = self.collect_settings()
        if not settings.source_root or not Path(settings.source_root).is_dir():
            QMessageBox.warning(
                self, "No source folder", "Choose a folder containing the source code first."
            )
            self.tabs.setCurrentIndex(0)
            return None
        return settings

    # -- actions -----------------------------------------------------------

    def _on_source_changed(self, path: str) -> None:
        self._mark_stale()
        if path and Path(path).is_dir():
            self.rescan()

    def rescan(self, then_order: list[str] | None = None) -> None:
        settings = self.collect_settings()
        if not settings.source_root or not Path(settings.source_root).is_dir():
            return
        settings.order_entries = list(then_order) if then_order else settings.order_entries

        worker = DiscoverWorker(self.pipeline, settings, self)

        def done(discovery) -> None:
            self._discovery = discovery
            from ..core import ordering

            plan = ordering.resolve_order(
                settings.order_entries,
                discovery.files,
                include_unlisted=True,
                excluded=settings.excluded,
            )
            self.files.populate(discovery, plan)
            self._busy(False)
            self._worker = None
            skipped = len(discovery.skipped)
            self._set_status(
                f"Found {len(discovery.files)} source file(s)"
                + (f"; {skipped} skipped." if skipped else ".")
            )

        worker.completed.connect(done)
        self._start(worker)

    def suggest_order(self) -> None:
        settings = self._require_source()
        if settings is None:
            return
        worker = SuggestOrderWorker(self.pipeline, settings, self)

        def done(order: list[str]) -> None:
            self.files.reorder_to(order)
            self._busy(False)
            self._worker = None
            self._set_status(
                "Order suggested from the entry points and the dependency graph."
            )

        worker.completed.connect(done)
        self._start(worker)

    def run_estimate(self) -> None:
        settings = self._require_source()
        if settings is None:
            return
        worker = EstimateWorker(self.pipeline, settings, self)

        def done(estimate) -> None:
            self._estimate = estimate
            self.estimate_panel.apply_estimate(estimate)
            self.preflight.apply_estimate(estimate)
            self.files.apply_estimate(estimate)
            self._busy(False)
            self._worker = None
            self.tabs.setCurrentWidget(self.estimate_panel)
            self._set_status(
                f"{estimate.page_count} page(s); "
                f"{estimate.selection.deposited_pages} would be deposited."
            )

        worker.completed.connect(done)
        self._start(worker)

    def run_what_if(self) -> None:
        settings = self._require_source()
        if settings is None:
            return
        worker = WhatIfWorker(self.pipeline, settings, self)

        def done(rows) -> None:
            self.estimate_panel.apply_what_if(rows)
            self._busy(False)
            self._worker = None
            self.tabs.setCurrentWidget(self.estimate_panel)
            self._set_status("Comparison complete.")

        worker.completed.connect(done)
        self._start(worker)

    def run_build(self, force: bool = False) -> None:
        settings = self._require_source()
        if settings is None:
            return
        if not settings.output_dir:
            QMessageBox.warning(self, "No output folder", "Choose where to write the PDFs.")
            self.tabs.setCurrentIndex(0)
            return
        if not settings.header.program_name.strip():
            answer = QMessageBox.question(
                self,
                "No program name",
                "The Copyright Office requires the program title on the first page.\n\n"
                "Build anyway with a placeholder?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.tabs.setCurrentIndex(0)
                return

        worker = BuildWorker(self.pipeline, settings, force=force, parent=self)

        def done(result) -> None:
            self._busy(False)
            self._worker = None
            self._estimate = result.estimate
            self.estimate_panel.apply_estimate(result.estimate)
            self.preflight.apply_estimate(result.estimate)
            self.files.apply_estimate(result.estimate)

            if result.blocked_by:
                self._handle_blocked(result)
                return

            self.history.record_run(
                settings,
                result.estimate.page_count,
                result.estimate.selection.deposited_pages,
                result.estimate.selection.mode,
                result.outputs,
                len(result.estimate.warnings),
            )
            self._set_status(f"Built {len(result.outputs)} file(s).")
            self._show_success(result)

        worker.completed.connect(done)
        self._start(worker)

    def _handle_blocked(self, result) -> None:
        self.tabs.setCurrentWidget(self.preflight)
        listing = "\n".join(
            f"  {f.location()} - {f.detail} ({f.excerpt})" for f in result.blocked_by[:12]
        )
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Possible credentials in the deposit")
        box.setText(
            f"{len(result.blocked_by)} finding(s) look like real credentials.\n\n"
            "A deposit is a public record, so anything left in the code can be read "
            "by anyone who inspects the filing."
        )
        box.setDetailedText(listing)
        review = box.addButton("Review findings", QMessageBox.ButtonRole.AcceptRole)
        anyway = box.addButton("Build anyway", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is anyway:
            self.run_build(force=True)
        elif box.clickedButton() is review:
            self.tabs.setCurrentWidget(self.preflight)

    def _show_success(self, result) -> None:
        outputs = list(result.outputs)
        if result.manifest_path:
            outputs += [result.manifest_path, result.summary_path]
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Deposit built")
        box.setText(
            f"{result.estimate.page_count} page(s) laid out; "
            f"{result.estimate.selection.deposited_pages} deposited."
        )
        box.setInformativeText(
            result.estimate.selection.filing_statement()
            + "\n\nWritten:\n"
            + "\n".join(outputs)
        )
        open_button = box.addButton("Open folder", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() is open_button and outputs:
            self._reveal(Path(outputs[0]).parent)

    @staticmethod
    def _reveal(folder: Path) -> None:
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(folder))  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.run(["open", str(folder)], check=False)
            else:
                subprocess.run(["xdg-open", str(folder)], check=False)
        except OSError:
            pass

    # -- pre-flight follow-ups --------------------------------------------

    def _queue_redactions(self, locations: list[str]) -> None:
        self.options.queue_redactions(locations)
        self.tabs.setCurrentWidget(self.options)
        self._set_status(
            f"{len(locations)} line(s) queued for redaction. Re-run the estimate to confirm."
        )

    def _exclude_files(self, paths: list[str]) -> None:
        self.files.set_included(paths, False)
        self.tabs.setCurrentWidget(self.files)
        self._set_status(f"{len(paths)} file(s) excluded from the deposit.")

    # -- profiles and history ---------------------------------------------

    def save_profile(self) -> None:
        settings = self.collect_settings()
        default = settings.header.program_name or Path(settings.source_root).name
        name, ok = QInputDialog.getText(self, "Save profile", "Profile name:", text=default)
        if not ok or not name.strip():
            return
        self.history.save_profile(name.strip(), settings)
        self._set_status(f"Profile '{name.strip()}' saved.")

    def load_profile(self) -> None:
        names = self.history.profile_names()
        if not names:
            QMessageBox.information(self, "No profiles", "No profiles have been saved yet.")
            return
        name, ok = QInputDialog.getItem(self, "Load profile", "Profile:", names, 0, False)
        if not ok:
            return
        settings = self.history.load_profile(name)
        if settings is None:
            QMessageBox.warning(self, "Could not load", f"Profile '{name}' could not be read.")
            return
        self.apply_settings(settings)
        self._set_status(f"Profile '{name}' loaded.")

    def delete_profile(self) -> None:
        names = self.history.profile_names()
        if not names:
            return
        name, ok = QInputDialog.getItem(self, "Delete profile", "Profile:", names, 0, False)
        if ok and name:
            self.history.delete_profile(name)
            self._set_status(f"Profile '{name}' deleted.")

    def show_history(self) -> None:
        runs = self.history.recent_runs()
        if not runs:
            QMessageBox.information(self, "No history", "No builds have been recorded yet.")
            return
        dialog = HistoryDialog(runs, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected is not None:
            try:
                settings = dialog.selected.settings()
            except (ValueError, TypeError):
                QMessageBox.warning(self, "Could not load", "That run's settings could not be read.")
                return
            self.apply_settings(settings)
            self._set_status(f"Restored settings from {dialog.selected.label()}.")

    def export_settings(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export settings", "deposit_settings.json", "JSON (*.json)"
        )
        if path:
            Path(path).write_text(self.collect_settings().to_json(), encoding="utf-8")
            self._set_status(f"Settings written to {path}")

    def import_settings(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import settings", "", "JSON (*.json)")
        if not path:
            return
        try:
            settings = BuildSettings.from_json(Path(path).read_text(encoding="utf-8"))
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Could not read", str(exc))
            return
        self.apply_settings(settings)
        self._set_status(f"Settings loaded from {path}")

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            f"About {DISPLAY_NAME}",
            f"<b>{DISPLAY_NAME} {__version__}</b>"
            "<p>Builds source-code deposit PDFs for US copyright registration.</p>"
            "<ul>"
            "<li>Monospaced type at 9.5 pt, about 40 lines per page, continuous "
            "page numbers and clear file paths.</li>"
            "<li>Applies Compendium sec. 721.6: the whole program at or under 50 "
            "pages, otherwise the first 25 and last 25.</li>"
            "<li>Supports blocked-out material under sec. 721.7, with the 49% "
            "limit checked.</li>"
            "<li>Page estimates are exact - they come from the same layout the "
            "renderer uses.</li>"
            "</ul>"
            "<p>This tool prepares a deposit; it is not legal advice.</p>",
        )

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(3000)
        self.history.close()
        super().closeEvent(event)

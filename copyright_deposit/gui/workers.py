"""Background workers.

Discovery, stripping and layout are CPU-bound and can take seconds on a
large tree, so they run off the GUI thread. A single worker runs at a time
and the window disables its actions while one is active, which keeps the
shared `Pipeline` cache free of concurrent writers.
"""

from __future__ import annotations

import traceback

from PySide6.QtCore import QThread, Signal

from ..config import BuildSettings
from ..core.pipeline import Pipeline


class _BaseWorker(QThread):
    progressed = Signal(str, int, int)
    failed = Signal(str)

    def __init__(self, pipeline: Pipeline, settings: BuildSettings, parent=None) -> None:
        super().__init__(parent)
        self.pipeline = pipeline
        self.settings = settings

    def _progress(self, stage: str, current: int, total: int) -> None:
        self.progressed.emit(stage, current, total)


class DiscoverWorker(_BaseWorker):
    """Walks the tree so the file table can be populated quickly."""

    completed = Signal(object)

    def run(self) -> None:
        try:
            self._progress("Scanning folder", 0, 1)
            result = self.pipeline.discover(self.settings, refresh=True)
            self.completed.emit(result)
        except Exception:
            self.failed.emit(traceback.format_exc(limit=6))


class EstimateWorker(_BaseWorker):
    completed = Signal(object)

    def run(self) -> None:
        try:
            estimate = self.pipeline.estimate(self.settings, progress=self._progress)
            self.completed.emit(estimate)
        except Exception:
            self.failed.emit(traceback.format_exc(limit=6))


class WhatIfWorker(_BaseWorker):
    completed = Signal(object)

    def run(self) -> None:
        try:
            rows = self.pipeline.what_if(self.settings, progress=self._progress)
            self.completed.emit(rows)
        except Exception:
            self.failed.emit(traceback.format_exc(limit=6))


class BuildWorker(_BaseWorker):
    completed = Signal(object)

    def __init__(self, pipeline, settings, force: bool = False, parent=None) -> None:
        super().__init__(pipeline, settings, parent)
        self.force = force

    def run(self) -> None:
        try:
            result = self.pipeline.build(
                self.settings, progress=self._progress, force=self.force
            )
            self.completed.emit(result)
        except Exception:
            self.failed.emit(traceback.format_exc(limit=6))


class SuggestOrderWorker(_BaseWorker):
    completed = Signal(object)

    def run(self) -> None:
        try:
            from ..core import ordering

            self._progress("Reading dependency graph", 0, 1)
            found = self.pipeline.discover(self.settings)
            self.completed.emit(ordering.suggest_order(found.files))
        except Exception:
            self.failed.emit(traceback.format_exc(limit=6))

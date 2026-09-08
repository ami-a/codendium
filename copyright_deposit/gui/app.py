"""QApplication bootstrap."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .. import APP_NAME, DISPLAY_NAME, __version__
from .branding import app_icon, claim_taskbar_identity


def run(argv: list[str] | None = None) -> int:
    # Must happen before the first window exists, or Windows has already
    # decided which taskbar group this process belongs to.
    claim_taskbar_identity()

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(DISPLAY_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(APP_NAME)
    # Applies to every window and dialog, not just the main one.
    app.setWindowIcon(app_icon())

    from .main_window import MainWindow

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())

"""The application icon.

The logo is rasterised at a fixed set of sizes rather than handed to Qt as
an SVG file, for two reasons: it works when the package is imported from a
zip or a wheel (where there is no filesystem path to give Qt), and it lets
the window manager pick a crisp pre-rendered size instead of scaling one
bitmap for the title bar, the alt-tab switcher and the taskbar alike.

Everything here degrades quietly. A missing or unreadable logo costs the
window its icon; it must never stop the application from starting.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap

from .. import APP_NAME

#: Sizes Windows, macOS and common Linux desktops actually ask for.
ICON_SIZES = (16, 20, 24, 32, 48, 64, 128, 256)

_cached_icon: QIcon | None = None


def logo_bytes() -> bytes | None:
    """Read the packaged logo, whether installed as files or in a zip."""
    try:
        from importlib.resources import files

        return (files("copyright_deposit.assets") / "logo.svg").read_bytes()
    except Exception:
        return None


def app_icon() -> QIcon:
    """The Codendium mark as a multi-resolution icon."""
    global _cached_icon
    if _cached_icon is not None:
        return _cached_icon

    icon = QIcon()
    data = logo_bytes()
    if data:
        try:
            from PySide6.QtSvg import QSvgRenderer

            renderer = QSvgRenderer(QByteArray(data))
            if renderer.isValid():
                for size in ICON_SIZES:
                    image = QImage(size, size, QImage.Format.Format_ARGB32)
                    image.fill(Qt.GlobalColor.transparent)
                    painter = QPainter(image)
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                    renderer.render(painter, QRectF(0, 0, size, size))
                    painter.end()
                    icon.addPixmap(QPixmap.fromImage(image))
        except Exception:
            pass

    _cached_icon = icon
    return icon


def claim_taskbar_identity() -> None:
    """Let Windows show our icon in the taskbar instead of Python's.

    Without an explicit AppUserModelID, Windows groups the process under
    the host interpreter and shows python.exe's icon on the taskbar, no
    matter what window icon is set. Harmless and skipped elsewhere.
    """
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            f"{APP_NAME}.desktop.1"
        )
    except Exception:
        pass

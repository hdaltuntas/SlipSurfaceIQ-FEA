"""Persistent appearance preferences shared by all windows (SlipSurfaceIQ shell)."""

from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication


def settings() -> QSettings:
    """INI file per user; tests redirect it with ``QSettings.setPath``."""
    return QSettings(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, "SlipSurface", "SlipSurfaceIQ-FEA"
    )


def available_geometry(widget=None):
    """Usable area (without taskbar / dock) of the widget's screen or the primary one."""
    app = QApplication.instance()
    screen = (widget.screen() if widget is not None else None) or app.primaryScreen()
    return screen.availableGeometry()


DESIGN_SIZE = (1920, 1080)  # logical resolution the window sizes were designed for (LE)


def fit_to_screen(widget, width: int, height: int, center: bool = True) -> None:
    """Size a window for the detected screen resolution (LE logic): designed sizes
    scale with the screen (relative to 1920x1080) and never exceed 95% of the area."""
    avail = available_geometry(widget)
    scale = min(avail.width() / DESIGN_SIZE[0], avail.height() / DESIGN_SIZE[1])
    scale = min(max(scale, 0.6), 1.6)
    w = min(int(width * scale), int(avail.width() * 0.95))
    h = min(int(height * scale), int(avail.height() * 0.95))
    widget.resize(max(w, 200), max(h, 150))
    if center:
        frame = widget.frameGeometry()
        frame.moveCenter(avail.center())
        widget.move(frame.topLeft())


def fit_to_screen(widget, width: int, height: int, center: bool = True) -> None:
    widget.resize(width, height)
    if center:
        frame = widget.frameGeometry()
        frame.moveCenter(available_geometry(widget).center())
        widget.move(frame.topLeft())


def show_screen_sized(window) -> None:
    window.setGeometry(available_geometry(window))
    window.showMaximized()


def apply_theme(dark: bool | None = None) -> None:
    """Apply the LE-style palette (light default, optional dark) and app stylesheet.

    Mirrors SlipSurfaceIQ-LE ``slipsurface/ui/preferences.py: apply_theme``:
    the same two palettes, stylesheet and the persisted ``dark`` setting.
    """
    from .theme import apply_le_theme

    if dark is None:
        dark = settings().value("dark", False, type=bool)
    settings().setValue("dark", dark)
    app = QApplication.instance()
    if app.property("slipsurface_le_theme") == dark:
        return
    app.setStyle("Fusion")
    hints = app.styleHints()
    if hasattr(hints, "setColorScheme"):  # keep the OS dark mode out of the light app
        from PySide6.QtCore import Qt

        hints.setColorScheme(Qt.ColorScheme.Dark if dark else Qt.ColorScheme.Light)
    apply_le_theme(app, dark)
    app.setProperty("slipsurface_le_theme", dark)

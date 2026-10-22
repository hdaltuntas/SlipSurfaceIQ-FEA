"""Persistent appearance preferences shared by all windows (SlipSurfaceIQ shell)."""

from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication


def settings() -> QSettings:
    return QSettings("SlipSurface", "SlipSurfaceIQ-FEA")


def available_geometry(widget=None):
    """Usable area (without taskbar / dock) of the widget's screen or the primary one."""
    app = QApplication.instance()
    screen = (widget.screen() if widget is not None else None) or app.primaryScreen()
    return screen.availableGeometry()


def fit_to_screen(widget, width: int, height: int, center: bool = True) -> None:
    widget.resize(width, height)
    if center:
        frame = widget.frameGeometry()
        frame.moveCenter(available_geometry(widget).center())
        widget.move(frame.topLeft())


def show_screen_sized(window) -> None:
    window.setGeometry(available_geometry(window))
    window.showMaximized()


def apply_theme() -> None:
    """Use explicit light colours, including native menus on dark desktops."""
    from .theme import apply_light_theme

    app = QApplication.instance()
    if app.property("slipsurface_light_theme"):
        return
    app.setStyle("Fusion")
    apply_light_theme(app)
    app.setProperty("slipsurface_light_theme", True)

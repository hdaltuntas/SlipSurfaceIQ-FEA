"""Persistent appearance preferences shared by all windows (SlipSurfaceIQ shell)."""

from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QPalette
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
    """Light Slide-style theme: fixed light palette so result colour maps are
    always read on a light background."""
    app = QApplication.instance()
    bg, base, text, border = "#f1f5f9", "#ffffff", "#243348", "#d9e2ed"
    pal = QPalette()
    for role in (QPalette.Window, QPalette.Button):
        pal.setColor(role, QColor(bg))
    for role in (QPalette.Base, QPalette.AlternateBase, QPalette.ToolTipBase):
        pal.setColor(role, QColor(base))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText, QPalette.ToolTipText):
        pal.setColor(role, QColor(text))
        pal.setColor(QPalette.Disabled, role, QColor("#8491a4"))
    pal.setColor(QPalette.Highlight, QColor("#287ae6"))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    app.setPalette(pal)
    app.setStyleSheet(f"""
        QWidget {{ font-size: 14px; }}
        QMainWindow, QDialog {{ background: {bg}; }}
        QToolBar {{ spacing: 5px; padding: 7px; border: none;
                    border-bottom: 1px solid {border}; }}
        QToolButton {{ padding: 6px; border-radius: 6px; }}
        QToolButton:hover, QPushButton:hover {{ background: {border}; }}
        QToolButton:checked {{ background: #315b88; color: white; }}
        QPushButton {{ padding: 7px 16px; border: 1px solid {border}; border-radius: 6px; }}
        QLineEdit, QComboBox, QPlainTextEdit {{
            padding: 5px; border: 1px solid {border}; border-radius: 5px;
            background: {base}; color: {text}; }}
        QSpinBox, QDoubleSpinBox {{ background: {base}; color: {text}; min-height: 28px; }}
        QSpinBox QLineEdit, QDoubleSpinBox QLineEdit {{ padding: 0; border: none; }}
        QTreeWidget, QListWidget, QTableWidget {{ border: 1px solid {border}; }}
        QMenu {{ padding: 5px; }}
        QMenu::item {{ padding: 7px 26px; }}
        QMenu::item:selected {{ background: #287ae6; color: white; }}
        QStatusBar {{ border-top: 1px solid {border}; }}
        QDockWidget::title {{ background: {border}; padding: 6px; }}
    """)

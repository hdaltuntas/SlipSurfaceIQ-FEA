"""LE-mirrored appearance: the same two palettes and stylesheet as SlipSurfaceIQ-LE
(``slipsurface/ui/preferences.py``), plus painter tokens for canvas/plot widgets."""

from PySide6.QtGui import QColor, QPalette

# Canvas / chart painter tokens (light default; dark set by apply_le_theme)
CANVAS_BG = "#f5f8fa"
PLOT_BG = "#ffffff"
PLOT_TEXT = "#213547"
PLOT_GRID = "#cbd5e1"
PLOT_LINE = "#087f9b"
MESH_PEN = "#42657b"
REGION_COLORS = ("#c5dfe8", "#dfd4b8", "#cbdcc4", "#d7cce5", "#f2d0c4", "#bfe3dc")


def _stylesheet(dark: bool) -> str:
    bg, base, text, border = (
        ("#161e2c", "#202c3e", "#e6edf7", "#36465d")
        if dark
        else ("#f1f5f9", "#ffffff", "#243348", "#d9e2ed")
    )
    return f"""
        QWidget {{ font-size: 14px; }}
        QMainWindow, QDialog {{ background: {bg}; }}
        QToolBar {{ spacing: 5px; padding: 7px; border: none;
                    border-bottom: 1px solid {border}; background: {bg}; }}
        QToolButton {{ padding: 6px; border-radius: 6px; color: {text}; }}
        QToolButton:hover, QPushButton:hover {{ background: {border}; }}
        QToolButton:checked {{ background: #315b88; color: white; }}
        QPushButton {{ padding: 7px 16px; border: 1px solid {border}; border-radius: 6px;
                      background: {base}; color: {text}; }}
        QLineEdit, QComboBox, QPlainTextEdit, QTextEdit {{
            padding: 5px; border: 1px solid {border}; border-radius: 5px;
            background: {base}; color: {text}; }}
        QSpinBox, QDoubleSpinBox {{ background: {base}; color: {text}; min-height: 28px; }}
        QSpinBox QLineEdit, QDoubleSpinBox QLineEdit {{ padding: 0; border: none; }}
        QTreeWidget, QListWidget, QTableWidget {{ border: 1px solid {border};
            background: {base}; color: {text}; }}
        QHeaderView::section {{ background: {border}; color: {text}; padding: 4px; }}
        QMenuBar {{ background: {bg}; color: {text}; }}
        QMenu {{ padding: 5px; background: {base}; color: {text}; }}
        QMenu::item {{ padding: 7px 26px; }}
        QMenu::item:selected {{ background: #287ae6; color: white; }}
        QStatusBar {{ border-top: 1px solid {border}; background: {bg}; color: {text}; }}
        QDockWidget {{ color: {text}; }}
        QDockWidget::title {{ background: {base}; color: {text}; padding: 6px; }}
        QTabWidget::pane {{ border: 1px solid {border}; background: {base}; }}
        QTabBar::tab {{ color: {text}; padding: 6px 12px; }}
        QTabBar::tab:selected {{ background: {border}; color: {text}; }}
        QCheckBox {{ color: {text}; }}
        QGroupBox {{ color: {text}; border: 1px solid {border}; border-radius: 6px; }}
        QLabel {{ color: {text}; }}
    """


def apply_le_theme(app, dark: bool) -> None:
    """Apply LE's palette + stylesheet; repaint token colours for painters."""
    global CANVAS_BG, PLOT_BG, PLOT_TEXT, PLOT_GRID, PLOT_LINE, MESH_PEN, REGION_COLORS
    if dark:
        bg, base, text, border = "#161e2c", "#202c3e", "#e6edf7", "#36465d"
        CANVAS_BG = "#161e2c"
        PLOT_BG = "#202c3e"
        PLOT_TEXT = "#e6edf7"
        PLOT_GRID = "#36465d"
        PLOT_LINE = "#5aa9f0"
        MESH_PEN = "#8fa3bd"
        REGION_COLORS = ("#3E5A6B", "#6B5E3E", "#4A6B4A", "#5D5470", "#6B4A3E", "#3E6B66")
    else:
        bg, base, text, border = "#f1f5f9", "#ffffff", "#243348", "#d9e2ed"
        CANVAS_BG = "#f5f8fa"
        PLOT_BG = "#ffffff"
        PLOT_TEXT = "#213547"
        PLOT_GRID = "#cbd5e1"
        PLOT_LINE = "#087f9b"
        MESH_PEN = "#42657b"
        REGION_COLORS = ("#c5dfe8", "#dfd4b8", "#cbdcc4", "#d7cce5", "#f2d0c4", "#bfe3dc")
    pal = QPalette()
    for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Button):
        pal.setColor(role, QColor(bg))
    for role in (QPalette.ColorRole.Base, QPalette.ColorRole.AlternateBase, QPalette.ColorRole.ToolTipBase):
        pal.setColor(role, QColor(base))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText,
                 QPalette.ColorRole.ButtonText, QPalette.ColorRole.ToolTipText):
        pal.setColor(role, QColor(text))
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor("#8491a4"))
    pal.setColor(QPalette.ColorRole.Highlight, QColor("#287ae6"))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    app.setPalette(pal)
    app.setStyleSheet(_stylesheet(dark))


def apply_theme(widget) -> None:
    """Backward-compatible alias: apply the LE light theme."""
    apply_le_theme(widget, False)


def apply_light_theme(widget):
    apply_le_theme(widget, False)

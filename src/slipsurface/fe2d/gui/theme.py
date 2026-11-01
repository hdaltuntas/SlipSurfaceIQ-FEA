"""Nordic Dark: one native PySide6 design system, shared with SlipSurfaceIQ-Suite.

The FEA desktop deliberately has no light-mode stylesheet; it mirrors the
Suite's ``slipsurface.desktop.theme`` palette and QSS (object names kept
distinct: ``fea*``) so both apps look identical. Canvas/plot painters read
the semantic tokens below instead of hardcoding light colours.
"""

from PySide6.QtGui import QColor, QPalette

THEME_NAME = "Nordic Dark"

COLORS = {
    "canvas": "#2B303B",
    "sidebar": "#303744",
    "surface": "#363E4D",
    "raised": "#414B5D",
    "input": "#262D39",
    "text": "#EDF1F7",
    "secondary": "#C2CCD9",
    "muted": "#B5C1CE",
    "border": "#586676",
    "accent": "#8FC9C3",
    "accent_hover": "#A9DEDA",
    "accent_text": "#17292E",
    "selected": "#385960",
    "ok": "#A3BE8C",
    "warning": "#EBCB8B",
    "error": "#E6949D",
}

# Canvas / chart painter tokens (used by canvas.py, result_tools.py, tunnel_designer.py)
CANVAS_BG = COLORS["canvas"]
PLOT_BG = COLORS["input"]
PLOT_TEXT = COLORS["text"]
PLOT_GRID = COLORS["border"]
PLOT_LINE = "#8FC9C3"
MESH_PEN = COLORS["border"]
REGION_COLORS = ("#3E5A6B", "#6B5E3E", "#4A6B4A", "#5D5470", "#6B4A3E", "#3E6B66")

STYLE = """
QWidget {
    background: #2B303B;
    color: #EDF1F7;
    font-family: "Segoe UI";
    font-size: 12px;
}
QMainWindow, QDialog, QSplitter, QScrollArea, QStackedWidget, QTabWidget::pane {
    background: #2B303B;
}
QMenuBar { background: #303744; color: #EDF1F7; padding: 2px 5px; }
QMenuBar::item { padding: 5px 11px; }
QMenuBar::item:selected, QMenuBar::item:pressed {
    background: #414B5D; color: #EDF1F7; border-radius: 5px;
}
QMenu { background: #363E4D; color: #EDF1F7; border: 1px solid #586676; }
QMenu::item { padding: 7px 22px 7px 16px; }
QMenu::item:selected { color: #EDF1F7; background: #385960; }
QMenu::separator { height: 1px; background: #586676; margin: 4px 8px; }
QToolBar { background: #303744; color: #EDF1F7; border: 0; border-bottom: 1px solid #586676; spacing: 4px; padding: 5px; }
QToolButton, QPushButton {
    color: #EDF1F7; background: #414B5D;
    border: 1px solid #586676; border-radius: 8px;
    min-height: 25px; padding: 6px 12px;
}
QToolButton:hover, QPushButton:hover { background: #506074; border-color: #8FC9C3; }
QToolButton:checked, QPushButton:checked { background: #385960; color: #D9FAF5; }
QPushButton:pressed, QToolButton:pressed { background: #385960; }
QPushButton:focus { border: 2px solid #8FC9C3; }
QPushButton:disabled, QToolButton:disabled { color: #9FAEBF; background: #353D4B; border-color: #485464; }
QWidget:disabled { color: #9FAEBF; }
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QTextEdit, QPlainTextEdit {
    color: #EDF1F7; background: #262D39;
    border: 1px solid #586676; border-radius: 7px;
    selection-background-color: #385960; selection-color: #FFFFFF;
    padding: 5px 8px; min-height: 24px;
}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus,
QTextEdit:focus, QPlainTextEdit:focus { border: 1px solid #8FC9C3; }
QComboBox QAbstractItemView {
    color: #EDF1F7; background: #303744;
    selection-background-color: #385960; selection-color: #FFFFFF;
    border: 1px solid #586676; outline: none;
}
QAbstractSpinBox { background: #262D39; color: #EDF1F7; selection-background-color: #385960; }
QAbstractItemView::item:selected { background: #385960; color: #EDF1F7; }
QListWidget {
    color: #EDF1F7; background: #303744;
    border: 1px solid #465463; border-radius: 9px; outline: none;
}
QListWidget::item { padding: 10px 11px; border-radius: 5px; }
QListWidget::item:hover:!selected { background: #414B5D; }
QListWidget::item:selected { color: #EDF1F7; background: #385960; border-left: 3px solid #8FC9C3; }
QTabWidget::pane { border: 1px solid #586676; border-radius: 8px; background: #303744; }
QTabBar::tab {
    color: #C2CCD9; background: #303744;
    padding: 9px 14px; border: 1px solid #495769;
    border-bottom: 0px; border-top-left-radius: 7px; border-top-right-radius: 7px;
    margin-right: 3px;
}
QTabBar::tab:hover:!selected { color: #EDF1F7; background: #414B5D; }
QTabBar::tab:selected { color: #D9FAF5; background: #385960; border-color: #8FC9C3; }
QGroupBox {
    color: #EDF1F7; font-weight: 600; background: #363E4D;
    border: 1px solid #586676; border-radius: 9px;
    margin-top: 17px; padding: 12px 10px 8px 10px;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0px 7px; }
QTableWidget, QTableView {
    color: #EDF1F7; background: #303744;
    alternate-background-color: #363E4D;
    selection-background-color: #385960; selection-color: #FFFFFF;
    gridline-color: #4B5969; border: 1px solid #586676; border-radius: 7px;
}
QHeaderView::section {
    background: #414B5D; color: #EDF1F7;
    border: 0px; border-right: 1px solid #586676; border-bottom: 1px solid #586676; padding: 7px 9px;
}
QDockWidget { color: #EDF1F7; }
QDockWidget::title { background: #303744; color: #EDF1F7; padding: 6px; border-bottom: 1px solid #586676; }
QScrollBar:vertical { background: #2B303B; width: 12px; margin: 0px; }
QScrollBar::handle:vertical { background: #586676; border-radius: 5px; min-height: 28px; }
QScrollBar:horizontal { background: #2B303B; height: 12px; margin: 0px; }
QScrollBar::handle:horizontal { background: #586676; border-radius: 5px; min-width: 28px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0px; width: 0px; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QCheckBox { color: #EDF1F7; spacing: 8px; }
QCheckBox::indicator { width: 15px; height: 15px; }
QCheckBox::indicator:checked { background: #8FC9C3; border: 1px solid #8FC9C3; border-radius: 3px; }
QCheckBox::indicator:unchecked { background: #262D39; border: 1px solid #8D9BA9; border-radius: 3px; }
QProgressBar { color: #EDF1F7; background: #262D39; border: 1px solid #586676; border-radius: 5px; }
QProgressBar::chunk { background: #8FC9C3; border-radius: 4px; }
QStatusBar { background: #303744; color: #C2CCD9; border-top: 1px solid #586676; }
QToolTip { color: #EDF1F7; background: #414B5D; border: 1px solid #586676; padding: 5px; }
QSplitter::handle { background: #586676; }
QLabel { color: #EDF1F7; background: transparent; }
"""


def apply_theme(widget) -> None:
    """Apply the single Nordic Dark theme (light-mode request maps to it)."""
    palette = QPalette()
    colors = {
        "Window": "#2B303B",
        "WindowText": "#EDF1F7",
        "Base": "#262D39",
        "AlternateBase": "#303744",
        "Text": "#EDF1F7",
        "Button": "#414B5D",
        "ButtonText": "#EDF1F7",
        "Highlight": "#385960",
        "HighlightedText": "#EDF1F7",
        "ToolTipBase": "#414B5D",
        "ToolTipText": "#EDF1F7",
        "PlaceholderText": "#B5C1CE",
        "Light": "#414B5D",
        "Midlight": "#363E4D",
        "Mid": "#586676",
        "Dark": "#303744",
        "Shadow": "#1E232C",
        "Link": "#8FC9C3",
    }
    for role, color in colors.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(color))
    for role in ("Text", "WindowText", "ButtonText"):
        palette.setColor(
            QPalette.ColorGroup.Disabled, getattr(QPalette.ColorRole, role), QColor("#9FAEBF")
        )
    widget.setPalette(palette)
    widget.setStyleSheet(STYLE)


def apply_light_theme(widget):
    """Backward-compatible alias: the app is Nordic Dark only."""
    apply_theme(widget)

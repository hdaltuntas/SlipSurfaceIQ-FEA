"""Explicit light palette: independent of the Windows/system dark palette."""

from PySide6.QtGui import QColor, QPalette

STYLE = """
QWidget { color:#243746; font-size:12px; }
QMainWindow,QDialog { background:#f1f4f7; }
QMenuBar,QMenu,QToolBar { background:#ffffff; color:#243746; }
QMenuBar::item { padding:7px 12px; background:transparent; }
QMenuBar::item:selected,QMenu::item:selected { background:#dcecf7; color:#124d70; }
QMenu::item { padding:7px 26px; }
QToolBar { border:0; border-bottom:1px solid #d3dde5; spacing:4px; padding:5px; }
QToolButton,QPushButton { background:#ffffff; color:#243746; border:1px solid #ccd7e0;
    border-radius:4px; padding:6px 9px; min-height:18px; }
QToolButton:hover,QPushButton:hover { background:#e7f1f8; border-color:#6e9dbb; }
QToolButton:checked,QPushButton:checked { background:#d9edf9; color:#075780; border-color:#3684b1; }
QWidget:disabled { color:#71818d; }
QToolButton:disabled,QPushButton:disabled { background:#edf1f4; border-color:#dce2e7; }
QDockWidget::title { background:#e6edf3; color:#243746; padding:6px; }
QCheckBox::indicator { width:14px; height:14px; border:1px solid #7891a3; border-radius:2px; }
QCheckBox::indicator:unchecked { background:#ffffff; }
QCheckBox::indicator:checked { background:#2182b3; border-color:#156798; }
QLabel,QCheckBox,QGroupBox { color:#243746; background:transparent; }
QLineEdit,QPlainTextEdit,QTextEdit,QComboBox,QAbstractSpinBox,QAbstractItemView {
    background:#ffffff; color:#243746; selection-background-color:#cce5f6;
    selection-color:#123f5b; border:1px solid #ccd7e0; border-radius:3px; padding:4px; }
QAbstractItemView::item:selected { background:#d9edf9; color:#124d70; }
QListWidget::item { padding:7px; }
QHeaderView::section { background:#e6edf3; color:#314858; padding:6px; border:1px solid #d1dce5; }
QTabWidget::pane { border:1px solid #ccd7e0; background:#ffffff; }
QTabBar::tab { background:#e6edf3; color:#334b5d; padding:8px 13px; }
QTabBar::tab:selected { background:#ffffff; color:#075780; border-bottom:2px solid #2182b3; }
QSplitter::handle { background:#dce5ec; }
QStatusBar { background:#e7eef4; color:#334b5d; }
QProgressBar { background:#e6edf3; color:#243746; border:0; text-align:center; }
QProgressBar::chunk { background:#2b91b7; }
QToolTip { background:#243746; color:#ffffff; border:0; padding:5px; }
"""


def apply_light_theme(widget):
    palette = QPalette()
    colors = {
        "Window": "#f1f4f7",
        "WindowText": "#243746",
        "Base": "#ffffff",
        "AlternateBase": "#edf3f7",
        "Text": "#243746",
        "Button": "#ffffff",
        "ButtonText": "#243746",
        "Highlight": "#cce5f6",
        "HighlightedText": "#123f5b",
        "ToolTipBase": "#243746",
        "ToolTipText": "#ffffff",
        "PlaceholderText": "#667b8b",
        "Light": "#ffffff",
        "Midlight": "#e6edf3",
        "Mid": "#b7c6d2",
        "Dark": "#647a8a",
        "Shadow": "#344b5b",
        "Link": "#076b9e",
    }
    for role, color in colors.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(color))
    for role in ("Text", "WindowText", "ButtonText"):
        palette.setColor(
            QPalette.ColorGroup.Disabled, getattr(QPalette.ColorRole, role), QColor("#71818d")
        )
    widget.setPalette(palette)
    widget.setStyleSheet(STYLE)

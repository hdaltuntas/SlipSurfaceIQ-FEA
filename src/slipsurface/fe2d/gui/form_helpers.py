"""Shared native form controls; no model mutation occurs in these helpers."""

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
)


class EditorDialog(QDialog):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.updated = None
        self.root = QVBoxLayout(self)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#a32d26")

    def finish_layout(self, accept):
        self.root.addWidget(self.status)
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        box.button(QDialogButtonBox.StandardButton.Ok).setText("Uygula")
        box.button(QDialogButtonBox.StandardButton.Cancel).setText("İptal")
        box.accepted.connect(accept)
        box.rejected.connect(self.reject)
        self.root.addWidget(box)

    def error(self, exc):
        self.status.setText(str(exc))


def toolbar(layout, actions):
    row = QHBoxLayout()
    for title, callback in actions:
        b = QPushButton(title)
        b.clicked.connect(callback)
        row.addWidget(b)
    row.addStretch()
    layout.addLayout(row)


def table(headers):
    result = QTableWidget(0, len(headers))
    result.setHorizontalHeaderLabels(headers)
    result.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    return result


def remove_row(widget):
    if widget.currentRow() >= 0:
        widget.removeRow(widget.currentRow())

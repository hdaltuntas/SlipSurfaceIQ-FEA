"""Read-only gap/pressure stage history for an exact stored contact point."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..io.contact_history_csv import export_contact_history_csv
from ..post.contact_history import contact_history_segments, contact_point_history


class ContactHistoryPlot(QWidget):
    """Two-dimensional Qt plot with explicit holes for unavailable measurements."""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.title = title
        self.segments = ()
        self.stage_count = 0
        self.selected_stage = -1
        self.setMinimumSize(380, 225)
        self.setAccessibleName(title)

    def set_history(self, history, field):
        self.segments = contact_history_segments(history, field)
        self.stage_count = len(history)
        self.update()

    def select_stage(self, index):
        self.selected_stage = index
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        painter.fillRect(self.rect(), palette.brush(QPalette.ColorRole.Base))
        painter.setPen(palette.color(QPalette.ColorRole.Text))
        painter.drawText(QRectF(10, 6, self.width() - 20, 24),
                         Qt.AlignmentFlag.AlignCenter, self.title)
        points = [p for segment in self.segments for p in segment]
        if not points:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No available samples")
            return
        # Normalize first to avoid overflow from subtracting very large finite values.
        scale = max(abs(value) for _, value in points) or 1.0
        values = [value / scale for _, value in points]
        low, high = min(0.0, min(values)), max(0.0, max(values))
        if low == high:
            low, high = -0.5, 0.5
        pad = (high - low) * 0.08
        low, high = low - pad, high + pad
        area = QRectF(86, 38, max(1, self.width() - 110), max(1, self.height() - 96))
        maximum_index = max(1, self.stage_count - 1)

        def screen(index, value):
            return QPointF(area.left() + index / maximum_index * area.width(),
                           area.bottom() - (value / scale - low) / (high - low) * area.height())

        painter.drawLine(area.bottomLeft(), area.bottomRight())
        painter.drawLine(area.bottomLeft(), area.topLeft())
        for i in range(5):
            level = low + (high - low) * i / 4
            y = area.bottom() - i * area.height() / 4
            # Extreme finite values may overflow only in tick padding; keep ticks finite.
            value = level * scale
            label = f"{value:.4g}" if math.isfinite(value) else f"{level:.3g}×{scale:.3g}"
            painter.drawText(QRectF(2, y - 10, 78, 20),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label)
        stride = max(1, (self.stage_count - 1 + 6) // 7)
        indices = sorted({*range(0, self.stage_count, stride), self.stage_count - 1})
        for index in indices:
            x = screen(index, 0.0).x()
            painter.drawText(QRectF(x - 20, area.bottom() + 5, 40, 20),
                             Qt.AlignmentFlag.AlignCenter, str(index))
        painter.drawText(QRectF(0, self.height() - 27, self.width(), 22),
                         Qt.AlignmentFlag.AlignCenter, "Stage index (0 = initial; not time)")
        if 0 <= self.selected_stage < self.stage_count:
            x = screen(self.selected_stage, 0.0).x()
            painter.setPen(QPen(palette.color(QPalette.ColorRole.Mid), 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
        painter.setPen(QPen(palette.color(QPalette.ColorRole.Highlight), 2))
        painter.setBrush(palette.brush(QPalette.ColorRole.Highlight))
        for segment in self.segments:
            previous = None
            for index, value in segment:
                position = screen(index, value)
                if previous is not None:
                    painter.drawLine(previous, position)
                painter.drawEllipse(position, 3.5, 3.5)
                previous = position


class ContactHistoryDialog(QDialog):
    def __init__(self, result, tag, element, point, stage_index=0, parent=None):
        super().__init__(parent)
        self.result = result
        self.identity = (tag, element, point)
        self.history = ()
        self.setWindowTitle("Normal contact · selected point stage history")
        self.resize(1080, 700)
        layout = QVBoxLayout(self)
        self.identity_label = QLabel()
        self.identity_label.setTextFormat(Qt.TextFormat.PlainText)
        self.identity_label.setWordWrap(True)
        layout.addWidget(self.identity_label)
        note = QLabel(
            "Accepted stage snapshots only, not time or within-stage iterations. "
            "Lines join adjacent stored samples as a visual guide; missing/inactive stages "
            "break the line. Gap: positive opening, negative penalty penetration. "
            "Pressure: compression positive. CSV gap uses metres."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        plots = QHBoxLayout()
        self.gap_plot = ContactHistoryPlot("Stored gap (mm)")
        self.pressure_plot = ContactHistoryPlot("Contact pressure (kPa, compression +)")
        plots.addWidget(self.gap_plot)
        plots.addWidget(self.pressure_plot)
        layout.addLayout(plots, 1)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "Stage index", "Stage", "Accepted λ", "Gap (mm)", "Pressure (kPa)", "State", "Data",
        ])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.currentCellChanged.connect(self.select_stage)
        layout.addWidget(self.table, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.csv_button = QPushButton("Point history CSV…")
        self.csv_button.clicked.connect(self.export)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(self.csv_button)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.refresh(stage_index)

    def select_stage(self, row, *_):
        self.gap_plot.select_stage(row)
        self.pressure_plot.select_stage(row)

    def refresh(self, stage_index=0):
        self.history = ()
        self.table.setRowCount(0)
        self.csv_button.setEnabled(False)
        self.identity_label.clear()
        for plot, field in ((self.gap_plot, "contact_gap"),
                             (self.pressure_plot, "contact_pressure")):
            plot.set_history((), field)
        try:
            self.history = contact_point_history(self.result, *self.identity)
        except (ValueError, KeyError, TypeError) as exc:
            self.status.setText(f"Contact history rejected: {exc}")
            return
        p = self.history[0].contact
        self.identity_label.setText(
            f"{p.tag} · element {p.element} · point {p.point} · face nodes "
            f"{p.face1_node} / {p.face2_node} · original (x, y) = ({p.x_m:.8g}, {p.y_m:.8g}) m"
        )
        self.table.setRowCount(len(self.history))
        for row, sample in enumerate(self.history):
            p = sample.contact
            values = [str(sample.stage_index), sample.stage_name, f"{sample.load_factor:.8g}",
                      "—" if p.gap_m is None else f"{p.gap_m * 1000:.8g}",
                      "—" if p.pressure_kpa is None else f"{p.pressure_kpa:.8g}",
                      p.status, p.availability]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.gap_plot.set_history(self.history, "contact_gap")
        self.pressure_plot.set_history(self.history, "contact_pressure")
        self.table.setCurrentCell(max(0, min(stage_index, len(self.history) - 1)), 0)
        available = sum(s.contact.availability == "available" for s in self.history)
        self.status.setText(f"{available}/{len(self.history)} snapshots have measurements. "
                            "No remesh matching, averaging or inferred zero values.")
        self.csv_button.setEnabled(True)

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export contact point history",
                                             "contact-history.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            export_contact_history_csv(self.result, path, *self.identity)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.status.setText(f"Export rejected: {exc}")
            return
        self.status.setText(f"Exported contact point history: {path}")

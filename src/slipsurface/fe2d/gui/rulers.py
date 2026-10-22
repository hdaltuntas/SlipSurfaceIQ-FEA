"""Metric viewport rulers for the integrated modeler."""

import math

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QGridLayout, QWidget


class MetricRuler(QWidget):
    def __init__(self, canvas, vertical=False):
        super().__init__()
        self.canvas, self.vertical = canvas, vertical
        if vertical:
            self.setFixedWidth(34)
        else:
            self.setFixedHeight(26)
        canvas.viewport().installEventFilter(self)
        canvas.horizontalScrollBar().valueChanged.connect(self.update)
        canvas.verticalScrollBar().valueChanged.connect(self.update)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Paint, QEvent.Type.Resize):
            self.update()
        return False

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#eaf0f5"))
        p.setPen(QColor("#486174"))
        c = self.canvas
        scale = abs(c.transform().m11())
        raw = 75 / max(scale, 1e-12)
        power = 10 ** math.floor(math.log10(raw))
        step = next(v * power for v in (1, 2, 5, 10) if v * power >= raw)
        top = c.mapToScene(QPoint(0, 0))
        bottom = c.mapToScene(c.viewport().rect().bottomRight())
        lo, hi = (-bottom.y(), -top.y()) if self.vertical else (top.x(), bottom.x())
        for i in range(math.ceil(lo / step), math.floor(hi / step) + 1):
            value = i * step
            pos = c.mapFromScene(QPointF(0, -value) if self.vertical else QPointF(value, 0))
            if self.vertical:
                p.drawLine(27, pos.y(), 34, pos.y())
                p.save()
                p.translate(18, pos.y())
                p.rotate(-90)
                p.drawText(-22, -8, 44, 16, Qt.AlignmentFlag.AlignCenter, f"{value:g}")
                p.restore()
            else:
                p.drawLine(pos.x(), 0, pos.x(), 6)
                p.drawText(pos.x() - 30, 7, 60, 18, Qt.AlignmentFlag.AlignCenter, f"{value:g}")


def ruled_canvas(canvas):
    area = QWidget()
    layout = QGridLayout(area)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    layout.addWidget(MetricRuler(canvas, True), 0, 0)
    layout.addWidget(canvas, 0, 1)
    layout.addWidget(MetricRuler(canvas), 1, 1)
    return area

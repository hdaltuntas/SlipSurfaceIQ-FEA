"""Construction sequence view: discrete stages, not a physical time integration axis."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView


class StageTimeline(QGraphicsView):
    selected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setMaximumHeight(150)
        self.setMinimumHeight(130)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.cards = []

    def set_stages(self, stages, initial=None):
        self.scene().clear()
        self.cards = []
        labels = [("Başlangıç", initial.mode if initial else "initial")]
        labels += [
            (s.name, f"λ={s.load_split:g} · {', '.join(sorted(s.active_structures)) or 'yapı yok'}")
            for s in stages
        ]
        for i, (name, detail) in enumerate(labels):
            x = 12 + i * 240
            if i:
                self.scene().addLine(x - 18, 49, x - 3, 49, QPen(QColor("#59758a"), 2))
            rect = self.scene().addRect(x, 10, 220, 83, QPen(QColor("#91aebe")), QColor("#edf7fb"))
            rect.setData(0, i)
            title = self.scene().addText(f"{i}. {name}")
            title.setPos(x + 8, 14)
            title.setTextWidth(202)
            title.setData(0, i)
            text = self.scene().addText(detail)
            text.setPos(x + 8, 49)
            text.setTextWidth(202)
            text.setData(0, i)
            self.cards.append(rect)
        self.scene().setSceneRect(0, 0, 24 + len(labels) * 240, 108)

    def mousePressEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item is not None and item.data(0) is not None:
            self.selected.emit(int(item.data(0)))
        super().mousePressEvent(event)

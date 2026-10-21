"""Native CAD workspace: transactional drawing, conditions, DXF and mesh worker."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QThread, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPainterPath, QPen, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import api
from ..cad.dxf import read_dxf, write_dxf
from ..cad.geometry import BoundaryRule, Drawing, Entity, snap_point


class CadCanvas(QGraphicsView):
    point_added = Signal(object)
    finish_requested = Signal()
    cancelled = Signal()
    cursor_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QColor("#f4f8fb"))
        self.setMouseTracking(True)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.entities = ()
        self.pending = []
        self.drawing = False
        self.grid = 0.5
        self.snapping = True
        self.setSceneRect(-4, -12, 28, 18)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

    def set_drawing(self, enabled):
        self.drawing = enabled
        self.setDragMode(
            QGraphicsView.DragMode.NoDrag if enabled else QGraphicsView.DragMode.ScrollHandDrag
        )
        self.setCursor(Qt.CursorShape.CrossCursor if enabled else Qt.CursorShape.OpenHandCursor)

    def redraw(self, entities, pending=(), selected=None):
        self.entities, self.pending = entities, list(pending)
        self.scene().clear()
        for e in entities:
            path = QPainterPath(QPointF(e.points[0][0], -e.points[0][1]))
            for x, y in e.points[1:]:
                path.lineTo(x, -y)
            if e.kind != "line":
                path.closeSubpath()
            pen = QPen(QColor("#ed8c24" if e.name == selected else "#24718d"))
            pen.setWidthF(2 if e.name == selected else 1)
            pen.setCosmetic(True)
            brush = QColor("#ffffff" if e.kind == "hole" else "#65b4c8")
            brush.setAlpha(75 if e.kind == "region" else 255)
            item = self.scene().addPath(path, pen)
            if e.kind != "line":
                item.setBrush(brush)
            item.setZValue(-e.shape().area if e.kind != "line" else 1)
            for name, (a, b) in zip(e.edge_names(), e.segments()):
                mid = (np.asarray(a) + b) / 2
                label = self.scene().addSimpleText(name)
                label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
                label.setPos(float(mid[0]), float(-mid[1]))
                label.setBrush(QColor("#34566a"))
                label.setZValue(2)
        if pending:
            path = QPainterPath(QPointF(*[pending[0][0], -pending[0][1]]))
            for x, y in pending[1:]:
                path.lineTo(x, -y)
            pen = QPen(QColor("#e07b19"), 2, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            self.scene().addPath(path, pen).setZValue(3)
            for x, y in pending:
                dot = self.scene().addEllipse(-3, -3, 6, 6, pen, QColor("#e07b19"))
                dot.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
                dot.setPos(x, -y)
                dot.setZValue(4)
        # Expand, never auto-zoom on each click (keeps drafting coordinates stable).
        rect = self.scene().itemsBoundingRect()
        self.setSceneRect(self.sceneRect().united(rect.adjusted(-3, -3, 3, 3)))

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        step = self.grid
        # A visual drafting grid; suppress dense grids rather than freezing the view.
        if not self.snapping or step <= 0 or step * abs(self.transform().m11()) < 12:
            return
        if rect.width() / step + rect.height() / step > 1500:
            return
        painter.setPen(QPen(QColor("#dfe9ee"), 0))
        for x in np.arange(np.floor(rect.left() / step) * step, rect.right(), step):
            painter.drawLine(QPointF(float(x), rect.top()), QPointF(float(x), rect.bottom()))
        for y in np.arange(np.floor(rect.top() / step) * step, rect.bottom(), step):
            painter.drawLine(QPointF(rect.left(), float(y)), QPointF(rect.right(), float(y)))

    def fit_drawing(self):
        points = [p for e in self.entities for p in e.points]
        if points:
            p = np.asarray(points)
            x0, y0 = p.min(axis=0)
            x1, y1 = p.max(axis=0)
            margin = max(x1 - x0, y1 - y0, 1) * 0.12
            rect = QRectF(x0 - margin, -y1 - margin, x1 - x0 + 2 * margin, y1 - y0 + 2 * margin)
        else:
            rect = QRectF(-2, -8, 16, 10)
        self.setSceneRect(rect)
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def mapped_point(self, position):
        p = self.mapToScene(position)
        q = (p.x(), -p.y())
        if self.snapping:
            tolerance = 10 / max(abs(self.transform().m11()), 1e-12)
            q, mode = snap_point(q, self.entities, tolerance, self.grid)
            # Current draft endpoints also snap without creating a temporary polygon.
            if self.pending:
                d = np.linalg.norm(np.asarray(self.pending) - q, axis=1)
                if d.min() < tolerance:
                    q, mode = self.pending[int(d.argmin())], "Çizim noktası"
        else:
            mode = "Serbest"
        return q, mode

    def mouseMoveEvent(self, event):
        q, mode = self.mapped_point(event.position().toPoint())
        self.cursor_changed.emit(f"x={q[0]:.4f} m   y={q[1]:.4f} m   · {mode}")
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if self.drawing and event.button() == Qt.MouseButton.LeftButton:
            q, _ = self.mapped_point(event.position().toPoint())
            self.point_added.emit(q)
            event.accept()
        elif self.drawing and event.button() == Qt.MouseButton.RightButton:
            self.finish_requested.emit()
            event.accept()
        else:
            super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.drawing:
            self.finish_requested.emit()
        elif event.key() == Qt.Key.Key_Escape and self.drawing:
            self.cancelled.emit()
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        if 1e-4 < abs(self.transform().m11()) * factor < 1e6:
            self.scale(factor, factor)


class MeshWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, drawing, parent=None):
        super().__init__(parent)
        self.drawing = Drawing.from_dict(drawing.to_dict())

    def checkpoint(self):
        if self.isInterruptionRequested():
            raise api.SolveCancelled("Ağ üretimi iptal edildi.")

    def run(self):
        try:
            self.checkpoint()
            model = self.drawing.build_model(self.checkpoint)
            self.checkpoint()
        except api.SolveCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit(model)


class CadDialog(QDialog):
    def __init__(self, model=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SlipSurfaceIQ · Geometri ve ağ")
        self.resize(1320, 880)
        self.document = Drawing.from_dict(model.geometry) if model and model.geometry else Drawing()
        self.updated = None
        self.worker = None
        self.pending = []
        self.undo_stack, self.redo_stack = [], []
        self._closing = self._cancel_requested = False
        root = QVBoxLayout(self)
        note = QLabel(
            "Yeni ağ, aşağıdaki mesnet/yüklerle yeni bir elastik model oluşturur. "
            "Mevcut analiz aşamaları, yapıları ve sonuçları taşınmaz.\n"
            "Birimler: m, kPa · Ağırlıksız başlangıç · Boşluk = başlangıçtan itibaren boş; "
            "aşamalı kazı için bölge çizin."
        )
        note.setWordWrap(True)
        root.addWidget(note)
        self.editor = QWidget()
        editor_layout = QVBoxLayout(self.editor)
        toolbar = QHBoxLayout()
        for title, callback in [
            ("Boş çizim", lambda: self.replace_drawing(Drawing())),
            ("Örnek", lambda: self.replace_drawing(Drawing.example())),
            ("Çizim aç", self.open_drawing),
            ("Çizim kaydet", self.save_drawing),
            ("DXF al", self.import_dxf),
            ("DXF ver", self.export_dxf),
            ("Geri al", self.undo),
            ("Yinele", self.redo),
        ]:
            b = QPushButton(title)
            b.clicked.connect(callback)
            toolbar.addWidget(b)
        editor_layout.addLayout(toolbar)
        split = QSplitter()
        side = QWidget()
        form = QFormLayout(side)
        self.entities = QListWidget()
        self.entities.currentRowChanged.connect(self.select_entity)
        form.addRow(self.entities)
        self.name = QLineEdit("Bolge1")
        self.kind = QComboBox()
        for title, value in [
            ("Malzeme bölgesi", "region"),
            ("Boşluk", "hole"),
            ("Çizgi (ağ kısıtı)", "line"),
        ]:
            self.kind.addItem(title, value)
        self.region = QSpinBox()
        self.region.setRange(1, 1000000)
        self.coordinates = QPlainTextEdit()
        self.coordinates.setPlaceholderText("Her satır: x y\n0 0\n12 0\n12 6\n0 6")
        self.coordinates.setMaximumHeight(150)
        form.addRow("Ad", self.name)
        form.addRow("Tür", self.kind)
        form.addRow("Bölge no", self.region)
        form.addRow("Koordinatlar (m)", self.coordinates)
        for title, callback in [
            ("Fareyle yeni çiz", self.begin_drawing),
            ("Çizimi bitir (Enter / sağ tık)", self.finish_drawing),
            ("Koordinatlardan ekle", self.add_from_text),
            ("Seçileni güncelle", self.update_entity),
            ("Seçileni sil", self.delete_entity),
        ]:
            b = QPushButton(title)
            b.clicked.connect(callback)
            form.addRow(b)
        self.canvas = CadCanvas()
        self.canvas.point_added.connect(self.add_point)
        self.canvas.finish_requested.connect(self.finish_drawing)
        self.canvas.cancelled.connect(self.cancel_drawing)
        split.addWidget(side)
        split.addWidget(self.canvas)
        split.setSizes([310, 950])
        editor_layout.addWidget(split, 1)
        settings = QHBoxLayout()
        self.snap = QCheckBox("Nokta/orta nokta yakala")
        self.snap.setChecked(True)
        self.snap.toggled.connect(lambda v: setattr(self.canvas, "snapping", v))
        settings.addWidget(self.snap)
        self.values = {}
        for key, title, value, lo, hi in [
            ("grid", "Izgara (0=kapalı)", 0.5, 0, 10000),
            ("h", "Hedef h (m)", self.document.h, 0.001, 10000),
            ("E", "E (kPa)", self.document.E, 1, 1e10),
            ("nu", "ν", self.document.nu, 0, 0.4999),
        ]:
            w = QDoubleSpinBox()
            w.setDecimals(4)
            w.setRange(lo, hi)
            w.setValue(value)
            settings.addWidget(QLabel(title))
            settings.addWidget(w)
            self.values[key] = w
        self.values["grid"].valueChanged.connect(lambda v: setattr(self.canvas, "grid", v))
        fit = QPushButton("Sığdır")
        fit.clicked.connect(self.canvas.fit_drawing)
        settings.addWidget(fit)
        editor_layout.addLayout(settings)
        editor_layout.addWidget(
            QLabel(
                "Kenar koşulları · ux/uy = sabit · Basınç pozitif içeri (kPa). "
                "Çizgiler kendiliğinden liner/bolt olmaz."
            )
        )
        self.conditions = QTableWidget(0, 4)
        self.conditions.setHorizontalHeaderLabels(["Kenar", "ux sabit", "uy sabit", "Basınç"])
        self.conditions.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.conditions.setMaximumHeight(175)
        editor_layout.addWidget(self.conditions)
        root.addWidget(self.editor, 1)
        self.status = QLabel("Sol tık: nokta · Enter/sağ tık: bitir · Esc: çizimi iptal")
        self.status.setWordWrap(True)
        self.canvas.cursor_changed.connect(self.cursor_status)
        root.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.build_button = buttons.addButton(
            "Ağ üret ve yeni modele uygula", QDialogButtonBox.ButtonRole.ActionRole
        )
        self.build_button.clicked.connect(self.start_mesh)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.undo_shortcut = QShortcut(QKeySequence.StandardKey.Undo, self)
        self.undo_shortcut.activated.connect(self.undo)
        self.redo_shortcut = QShortcut(QKeySequence.StandardKey.Redo, self)
        self.redo_shortcut.activated.connect(self.redo)
        self.refresh(fit=True)

    def cursor_status(self, text):
        if self.pending:
            self.status.setText(text + f" · {len(self.pending)} nokta · Enter: bitir")

    def current_drawing(self):
        rules = []
        for i in range(self.conditions.rowCount()):
            edge = self.conditions.item(i, 0).text()
            ux = self.conditions.item(i, 1).checkState() == Qt.CheckState.Checked
            uy = self.conditions.item(i, 2).checkState() == Qt.CheckState.Checked
            p = self.conditions.cellWidget(i, 3).value()
            if ux or uy or p:
                rules.append(BoundaryRule(edge, ux, uy, p))
        return replace(
            self.document,
            rules=tuple(rules),
            **{k: self.values[k].value() for k in ("h", "E", "nu")},
        )

    def refresh(self, *, fit=False):
        self.entities.blockSignals(True)
        self.entities.clear()
        labels = {"region": "Bölge", "hole": "Boşluk", "line": "Çizgi"}
        self.entities.addItems(
            [f"{e.name} · {labels[e.kind]} · R{e.region}" for e in self.document.entities]
        )
        self.entities.blockSignals(False)
        rules = {r.edge: r for r in self.document.rules}
        names = [n for e in self.document.entities for n in e.edge_names()]
        self.conditions.setRowCount(len(names))
        for i, name in enumerate(names):
            r = rules.get(name, BoundaryRule(name))
            item = QTableWidgetItem(name)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.conditions.setItem(i, 0, item)
            for j, checked in [(1, r.ux), (2, r.uy)]:
                item = QTableWidgetItem()
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                self.conditions.setItem(i, j, item)
            pressure = QDoubleSpinBox()
            pressure.setRange(min(-1e12, r.pressure), max(1e12, r.pressure))
            pressure.setDecimals(12)
            pressure.setValue(r.pressure)
            self.conditions.setCellWidget(i, 3, pressure)
        for k in ("h", "E", "nu"):
            value = getattr(self.document, k)
            self.values[k].setRange(
                min(self.values[k].minimum(), value), max(self.values[k].maximum(), value)
            )
            self.values[k].setValue(value)
        self.canvas.redraw(self.document.entities, self.pending)
        if fit:
            self.canvas.fit_drawing()

    def commit(self, drawing):
        before = self.current_drawing()
        self.undo_stack.append(before)
        self.redo_stack.clear()
        self.document = drawing
        self.cancel_drawing()
        self.refresh()

    def replace_drawing(self, drawing):
        if self.worker:
            return
        if (
            self.document.entities
            and QMessageBox.question(
                self,
                "Çizimi değiştir",
                "Mevcut çizim değiştirilsin mi? Geri al ile dönebilirsiniz.",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.commit(drawing)
        self.canvas.fit_drawing()

    def undo(self):
        if self.worker or not self.undo_stack:
            return
        self.redo_stack.append(self.current_drawing())
        self.document = self.undo_stack.pop()
        self.cancel_drawing()
        self.refresh()

    def redo(self):
        if self.worker or not self.redo_stack:
            return
        self.undo_stack.append(self.current_drawing())
        self.document = self.redo_stack.pop()
        self.cancel_drawing()
        self.refresh()

    def select_entity(self, index):
        if not 0 <= index < len(self.document.entities):
            return
        e = self.document.entities[index]
        self.name.setText(e.name)
        self.kind.setCurrentIndex(self.kind.findData(e.kind))
        self.region.setValue(e.region)
        self.coordinates.setPlainText("\n".join(f"{x:.12g} {y:.12g}" for x, y in e.points))
        self.canvas.redraw(self.document.entities, self.pending, e.name)

    def begin_drawing(self):
        self.pending = []
        self.canvas.set_drawing(True)
        self.canvas.setFocus()
        self.status.setText("Sol tıkla noktaları girin; Enter/sağ tıkla bitirin. Esc: iptal.")

    def add_point(self, point):
        point = tuple(point)
        if self.pending and point == self.pending[0] and len(self.pending) >= 3:
            self.finish_drawing()
            return
        if not self.pending or point != self.pending[-1]:
            self.pending.append(point)
        self.canvas.redraw(self.document.entities, self.pending)

    def cancel_drawing(self):
        self.pending = []
        self.canvas.set_drawing(False)
        self.canvas.redraw(self.document.entities)

    def finish_drawing(self):
        if not self.pending:
            return
        try:
            self.add_entity(self.entity_from_points(self.pending))
        except Exception as exc:
            self.show_error(exc)

    def entity_from_points(self, points):
        return Entity(
            self.name.text().strip(), self.kind.currentData(), tuple(points), self.region.value()
        )

    def text_entity(self):
        points = [
            tuple(map(float, line.replace(",", " ").split()))
            for line in self.coordinates.toPlainText().splitlines()
            if line.strip()
        ]
        return self.entity_from_points(points)

    def add_entity(self, entity):
        current = self.current_drawing()
        if entity.name in {e.name for e in current.entities}:
            raise ValueError("Bu ad kullanılıyor; yeni geometriye farklı ad verin.")
        self.commit(replace(current, entities=(*current.entities, entity)))

    def add_from_text(self):
        try:
            self.add_entity(self.text_entity())
            self.canvas.fit_drawing()
        except Exception as exc:
            self.show_error(exc)

    def update_entity(self):
        index = self.entities.currentRow()
        if index < 0:
            return
        try:
            current = self.current_drawing()
            old, entity = current.entities[index], self.text_entity()
            if any(e.name == entity.name for j, e in enumerate(current.entities) if j != index):
                raise ValueError("Bu ad başka bir geometride kullanılıyor.")
            entities = list(current.entities)
            entities[index] = entity
            # Edited topology can reorder edges: never silently transfer old conditions.
            rules = tuple(r for r in current.rules if r.edge not in old.edge_names())
            self.commit(replace(current, entities=tuple(entities), rules=rules))
            self.status.setText("Geometri güncellendi; bu öğenin kenar koşullarını yeniden atayın.")
        except Exception as exc:
            self.show_error(exc)

    def delete_entity(self):
        index = self.entities.currentRow()
        if index < 0:
            return
        current = self.current_drawing()
        old = current.entities[index]
        self.commit(
            replace(
                current,
                entities=tuple(e for i, e in enumerate(current.entities) if i != index),
                rules=tuple(r for r in current.rules if r.edge not in old.edge_names()),
            )
        )

    def open_drawing(self):
        path, _ = QFileDialog.getOpenFileName(self, "Çizim aç", "", "CAD (*.sscad.json)")
        if path:
            try:
                self.replace_drawing(Drawing.from_dict(json.loads(Path(path).read_text("utf-8"))))
            except Exception as exc:
                self.show_error(exc)

    def save_drawing(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Çizim kaydet", "cizim.sscad.json", "CAD (*.sscad.json)"
        )
        if path:
            try:
                if not path.endswith(".sscad.json"):
                    path += ".sscad.json"
                Path(path).write_text(
                    json.dumps(self.current_drawing().to_dict(), indent=2, allow_nan=False),
                    encoding="utf-8",
                )
                self.status.setText("Çizim kaydedildi (ağ üretmeden de saklanabilir).")
            except Exception as exc:
                self.show_error(exc)

    def import_dxf(self):
        path, _ = QFileDialog.getOpenFileName(self, "DXF al", "", "DXF (*.dxf)")
        if not path:
            return
        scale, ok = QInputDialog.getDouble(
            self,
            "DXF ölçeği",
            "1 DXF birimi kaç metre? m=1; cm=0.01; mm=0.001\n"
            "Bu değer dosyadaki birim etiketinden bağımsız uygulanır.",
            1,
            1e-9,
            1e9,
            9,
        )
        if ok:
            try:
                self.replace_drawing(read_dxf(path, metres_per_unit=scale))
                self.status.setText("DXF alındı. Tür/bölge, mesnet ve yükleri kontrol edin.")
            except Exception as exc:
                self.show_error(exc)

    def export_dxf(self):
        path, _ = QFileDialog.getSaveFileName(self, "DXF ver", "cizim.dxf", "DXF (*.dxf)")
        if path:
            try:
                write_dxf(
                    self.current_drawing(), path if path.lower().endswith(".dxf") else path + ".dxf"
                )
                self.status.setText(
                    "DXF: yalnız geometri, metre. Koşullar için CAD/proje kaydedin."
                )
            except Exception as exc:
                self.show_error(exc)

    def start_mesh(self):
        if self.worker:
            return
        if self.pending:
            self.show_error("Önce devam eden çizimi bitirin veya Esc ile iptal edin.")
            return
        try:
            drawing = self.current_drawing()
            drawing.validate()
            self.worker = MeshWorker(drawing, self)
        except Exception as exc:
            self.show_error(exc)
            return
        self.updated = None
        self._cancel_requested = False
        self.editor.setEnabled(False)
        self.build_button.setEnabled(False)
        self.status.setText("T6 ağ üretiliyor… İptal, mevcut ağ turundan sonra uygulanır.")
        self.worker.succeeded.connect(self.mesh_success)
        self.worker.failed.connect(self.show_error)
        self.worker.cancelled.connect(lambda: self.status.setText("Ağ üretimi iptal edildi."))
        self.worker.finished.connect(self.mesh_finished)
        self.worker.start()

    def mesh_success(self, model):
        if not self._cancel_requested:
            self.updated = model

    def mesh_finished(self):
        worker, self.worker = self.worker, None
        worker.deleteLater()
        self.editor.setEnabled(True)
        self.build_button.setEnabled(True)
        if self._closing:
            super().reject()
        elif self.updated is not None:
            self.accept()

    def show_error(self, exc):
        self.status.setText(f"İşlem tamamlanamadı: {exc}")
        self.status.setStyleSheet("color:#a32d26")

    def reject(self):
        if self.worker:
            self._closing = self._cancel_requested = True
            self.updated = None
            self.worker.requestInterruption()
            self.status.setText("İptal isteniyor; ağ işçisi güvenle kapanıyor…")
        else:
            super().reject()

    def closeEvent(self, event):
        if self.worker:
            self.reject()
            event.ignore()
        else:
            event.accept()

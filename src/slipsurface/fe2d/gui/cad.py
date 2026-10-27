"""Native CAD workspace: transactional drawing, conditions, DXF and mesh worker."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QThread, QTimer, Signal
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
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import api
from ..cad.dxf import read_dxf, write_dxf
from ..cad.geometry import BoundaryRule, Drawing, Entity, snap_point
from ..cad.supports import SupportAssignment
from .drawing_supports import DrawingSupportPanel
from .rulers import ruled_canvas


class CadCanvas(QGraphicsView):
    point_added = Signal(object)
    finish_requested = Signal()
    cancelled = Signal()
    cursor_changed = Signal(str)
    mouse_world = Signal(float, float)
    entity_selected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QColor("#f4f8fb"))
        self.setMouseTracking(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.entities = ()
        self.pending = []
        self.drawing = False
        self.grid = 0.5
        self.snapping = True
        self.object_snapping = True
        self.ortho = False
        self.grid_visible = True
        self.edge_labels = False
        self.preview = None
        self._pan_position = None
        self.rectangle = False
        self.circle = False
        self.supports = {}
        self.setSceneRect(-4, -12, 28, 18)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)

    def set_drawing(self, enabled):
        self.drawing = enabled
        self.preview = None
        self.setCursor(Qt.CursorShape.CrossCursor if enabled else Qt.CursorShape.ArrowCursor)
        self.viewport().update()

    def set_grid_visible(self, visible):
        self.grid_visible = visible
        self.viewport().update()

    def redraw(self, entities, pending=(), selected=None):
        self.entities, self.pending = entities, list(pending)
        self.scene().clear()
        for e in entities:
            path = QPainterPath(QPointF(e.points[0][0], -e.points[0][1]))
            for x, y in e.points[1:]:
                path.lineTo(x, -y)
            if e.kind != "line":
                path.closeSubpath()
            support = self.supports.get(e.name)
            color = {"pile": "#8455b6", "liner": "#b56324", "bolt": "#218764"}.get(
                support, "#24718d"
            )
            pen = QPen(QColor("#ed8c24" if e.name == selected else color))
            pen.setWidthF(3 if support or e.name == selected else 1)
            pen.setCosmetic(True)
            brush = QColor("#ffffff" if e.kind == "hole" else "#65b4c8")
            brush.setAlpha(75 if e.kind == "region" else 255)
            item = self.scene().addPath(path, pen)
            if e.kind != "line":
                item.setBrush(brush)
            item.setZValue(-e.shape().area if e.kind != "line" else 1)
            for name, (a, b) in zip(e.edge_names(), e.segments()) if self.edge_labels else []:
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
        if not self.grid_visible or step <= 0:
            return
        while step * abs(self.transform().m11()) < 18:
            step *= 2
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
        self.setSceneRect(
            rect.adjusted(
                -rect.width() * 4, -rect.height() * 4, rect.width() * 4, rect.height() * 4
            )
        )

    def mapped_point(self, position):
        p = self.mapToScene(position)
        q = (p.x(), -p.y())
        if self.snapping or self.object_snapping:
            tolerance = 10 / max(abs(self.transform().m11()), 1e-12)
            q, mode = snap_point(
                q,
                self.entities if self.object_snapping else (),
                tolerance,
                self.grid if self.snapping else 0.0,
            )
            # Current draft endpoints also snap without creating a temporary polygon.
            if self.pending and self.object_snapping:
                d = np.linalg.norm(np.asarray(self.pending) - q, axis=1)
                if d.min() < tolerance:
                    q, mode = self.pending[int(d.argmin())], "Çizim noktası"
        else:
            mode = "Serbest"
        if self.ortho and self.pending:
            last = np.asarray(self.pending[-1])
            d = np.asarray(q) - last
            q = (last[0] + d[0], last[1]) if abs(d[0]) >= abs(d[1]) else (last[0], last[1] + d[1])
            mode = "ORTHO"
        return q, mode

    def command(self, text: str):
        """Coordinate entry from the command box; only while drawing."""
        if not self.drawing or not text.strip():
            return False
        from .tools import parse_coordinate

        last = tuple(self.pending[-1]) if self.pending else None
        try:
            q = parse_coordinate(text, last)
        except (ValueError, OverflowError):
            return False
        if q is None or not np.isfinite(q).all():
            return False
        self.point_added.emit(tuple(float(v) for v in q))
        return True

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        painter.save()
        painter.resetTransform()
        origin = QPointF(30, self.viewport().height() - 28)
        painter.setPen(QPen(QColor("#557287"), 1))
        painter.drawLine(origin, origin + QPointF(38, 0))
        painter.drawLine(origin, origin + QPointF(0, -38))
        painter.drawText(origin + QPointF(42, 4), "X")
        painter.drawText(origin + QPointF(-4, -44), "Y")
        painter.drawText(QPointF(14, 22), "XY · metre")
        painter.restore()
        if self.drawing and self.preview is not None:
            x, y = self.preview
            pen = QPen(QColor("#b65f00"), 1, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            if self.pending:
                a, b = self.pending[-1]
                if self.circle:
                    radius = float(np.hypot(x - a, y - b))
                    painter.drawEllipse(QPointF(a, -b), radius, radius)
                elif self.rectangle:
                    painter.drawRect(QRectF(QPointF(a, -b), QPointF(x, -y)).normalized())
                else:
                    painter.drawLine(QPointF(a, -b), QPointF(x, -y))
            radius = 5 / max(abs(self.transform().m11()), 1e-12)
            painter.drawRect(QRectF(x - radius, -y - radius, 2 * radius, 2 * radius))

    def mouseMoveEvent(self, event):
        position = event.position().toPoint()
        if self._pan_position is not None:
            delta = position - self._pan_position
            self._pan_position = position
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        q, mode = self.mapped_point(position)
        self.preview = q
        self.mouse_world.emit(*q)
        self.cursor_changed.emit(f"x={q[0]:.4f} m   y={q[1]:.4f} m   · {mode}")
        self.viewport().update()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_position = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        elif self.drawing and event.button() == Qt.MouseButton.LeftButton:
            q, _ = self.mapped_point(event.position().toPoint())
            self.point_added.emit(q)
            event.accept()
        elif self.drawing and event.button() == Qt.MouseButton.RightButton:
            self.finish_requested.emit()
            event.accept()
        elif event.button() == Qt.MouseButton.LeftButton:
            from shapely.geometry import Point

            p = self.mapToScene(event.position().toPoint())
            point = Point(p.x(), -p.y())
            tolerance = 8 / max(abs(self.transform().m11()), 1e-12)
            hits = []
            for index, entity in enumerate(self.entities):
                shape = entity.shape()
                boundary = shape if entity.kind == "line" else shape.boundary
                distance = boundary.distance(point)
                if distance <= tolerance:
                    hits.append((0, distance, index))
                elif entity.kind != "line" and shape.covers(point):
                    hits.append((1, shape.area, index))
            self.entity_selected.emit(min(hits)[2] if hits else -1)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_position = None
            self.setCursor(
                Qt.CursorShape.CrossCursor if self.drawing else Qt.CursorShape.ArrowCursor
            )
            event.accept()
        else:
            super().mouseReleaseEvent(event)

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
    model_ready = Signal(object)
    worker_stopped = Signal()
    drawing_changed = Signal()

    def __init__(self, model=None, parent=None, *, embedded=False):
        super().__init__(parent)
        from .preferences import apply_theme

        apply_theme()
        self.embedded = embedded
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
        self.circle_mode = False
        self.draw_support_kind = None
        self.rectangle_mode = False
        self.setWindowTitle("SlipSurfaceIQ · Geometri ve ağ")
        self.resize(1320, 880)
        self.document = Drawing.from_dict(model.geometry) if model and model.geometry else Drawing()
        self.saved_drawing = self.model_drawing = self.document
        self.updated = None
        self.worker = None
        self.pending = []
        self.undo_stack, self.redo_stack = [], []
        self._closing = self._cancel_requested = False
        root = QVBoxLayout(self)
        note = QLabel(
            "Yeni ağ, çizimdeki mesnet/yük ve destekleri uygular. Ana pencerede mevcut "
            "malzeme, aşama ve ara yüz tanımları yeni ağa aktarılır; sonuçlar silinir.\n"
            "Birimler: m, kPa · Ağırlıksız başlangıç · Boşluk = başlangıçtan itibaren boş; "
            "aşamalı kazı için bölge çizin."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#526677; padding:4px;")
        root.addWidget(note)
        self.rebuild_notice = note
        if embedded:
            note.hide()
            root.setContentsMargins(0, 0, 0, 0)
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
        if embedded:
            for i in range(toolbar.count()):
                toolbar.itemAt(i).widget().hide()
        split = QSplitter()
        self.splitter = split
        side = QWidget()
        form = QFormLayout(side)
        self.entities = QListWidget()
        self.entities.currentRowChanged.connect(self.select_entity)
        self.entities.setMinimumHeight(120)
        self.entities.setMaximumHeight(170)
        form.addRow("NESNELER", self.entities)
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
        self.canvas.entity_selected.connect(self.select_from_canvas)
        side.setMaximumWidth(350)
        side.setMinimumWidth(260)
        split.addWidget(side)
        split.addWidget(ruled_canvas(self.canvas))
        split.setSizes([310, 950])
        drawing_tools = QHBoxLayout()
        for title, callback in [
            ("Seç · Esc", self.cancel_drawing),
            ("Çokgen", lambda: self.start_tool("region")),
            ("Dikdörtgen", lambda: self.start_tool("region", rectangle=True)),
            ("Boşluk", lambda: self.start_tool("hole")),
            ("Çoklu çizgi", lambda: self.start_tool("line")),
            ("Tümünü sığdır", self.canvas.fit_drawing),
        ]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            drawing_tools.addWidget(button)
        self.geometry_tools = QWidget()
        self.geometry_tools.setLayout(drawing_tools)
        drawing_tools.setContentsMargins(0, 0, 0, 0)
        editor_layout.addWidget(self.geometry_tools)
        support_tools = QHBoxLayout()
        self.tool_buttons = {}
        for title, tool in [
            ("Kazık çiz", "pile"),
            ("Tünel çiz", "tunnel"),
            ("Kaplama çiz", "liner"),
            ("Ankraj / çivi çiz", "bolt"),
        ]:
            button = QPushButton(title)
            button.clicked.connect(lambda _=False, t=tool: self.start_engineering_tool(t))
            support_tools.addWidget(button)
            self.tool_buttons[tool] = button
        self.tunnel_lining = QCheckBox("Tünele kaplama ekle")
        self.tunnel_lining.setChecked(True)
        self.tunnel_lining.setToolTip("Merkez ve yarıçap ile 32 kenarlı dairesel boşluk oluşturur.")
        support_tools.addWidget(self.tunnel_lining)
        self.tunnel_excavation = QCheckBox("Aşamalı kazı bölgesi")
        self.tunnel_excavation.setToolTip(
            "Tüneli ayrı malzeme bölgesi olarak doldurur. Aşamalar bölümünde bu bölgeyi kazın."
        )
        support_tools.addWidget(self.tunnel_excavation)
        self.support_tools = QWidget()
        self.support_tools.setLayout(support_tools)
        support_tools.setContentsMargins(0, 0, 0, 0)
        editor_layout.addWidget(self.support_tools)
        if embedded:
            self.support_tools.hide()
        editor_layout.addWidget(split, 1)
        settings = QHBoxLayout()
        self.ortho = QCheckBox("Dik çizim · F8")
        self.ortho.toggled.connect(lambda v: setattr(self.canvas, "ortho", v))
        settings.addWidget(self.ortho)
        self.snap = QCheckBox("Izgaraya yakala · F9")
        self.snap.setChecked(True)
        self.snap.toggled.connect(lambda v: setattr(self.canvas, "snapping", v))
        settings.addWidget(self.snap)
        self.osnap = QCheckBox("Nesne yakala · F3")
        self.osnap.setChecked(True)
        self.osnap.toggled.connect(lambda on: setattr(self.canvas, "object_snapping", on))
        settings.addWidget(self.osnap)
        self.grid_toggle = QCheckBox("Izgara · F7")
        self.grid_toggle.setChecked(True)
        self.grid_toggle.toggled.connect(self.canvas.set_grid_visible)
        settings.addWidget(self.grid_toggle)
        self.labels_toggle = QCheckBox("Kenar adları")
        self.labels_toggle.toggled.connect(self.toggle_labels)
        settings.addWidget(self.labels_toggle)
        for key, widget in [
            ("F7", self.grid_toggle),
            ("F8", self.ortho),
            ("F9", self.snap),
            ("F3", self.osnap),
        ]:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(widget.toggle)
        self.values = {}
        for key, title, value, lo, hi in [
            ("grid", "Adım (m)", 0.5, 0, 10000),
            ("h", "Hedef h (m)", self.document.h, 0.001, 10000),
            ("E", "E (kPa)", self.document.E, 1, 1e10),
            ("nu", "ν", self.document.nu, 0, 0.4999),
        ]:
            w = QDoubleSpinBox()
            w.setDecimals(4)
            w.setRange(lo, hi)
            w.setValue(value)
            if key == "grid":
                settings.addWidget(QLabel(title))
                settings.addWidget(w)
            else:
                form.addRow(title, w)
            self.values[key] = w
        self.values["grid"].valueChanged.connect(self.set_grid_spacing)
        settings.addStretch()
        self.values["grid"].setMaximumWidth(110)
        editor_layout.addLayout(settings)
        entry = QHBoxLayout()
        entry.addWidget(QLabel("Koordinat:"))
        self.cmd = QLineEdit()
        self.cmd.setPlaceholderText("x,y  |  @dx,dy  |  @L<açı  ·  Enter = bitir")
        self.cmd.setToolTip(
            "Çizim sırasında klavyeden koordinat: mutlak x,y, göreli @dx,dy, "
            "kutupsal @uzunluk<açı. Boş Enter = bitir."
        )
        self.cmd.returnPressed.connect(self._command)
        entry.addWidget(self.cmd, 1)
        editor_layout.addLayout(entry)
        boundary_page = QWidget()
        boundary_layout = QVBoxLayout(boundary_page)
        boundary_hint = QLabel(
            "ux/uy = sabit · Basınç pozitif içeri (kPa). Çizgiler kendiliğinden liner/bolt olmaz."
        )
        boundary_hint.setWordWrap(True)
        boundary_layout.addWidget(boundary_hint)
        self.conditions = QTableWidget(0, 4)
        self.conditions.setHorizontalHeaderLabels(["Kenar", "ux sabit", "uy sabit", "Basınç"])
        self.conditions.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.conditions.verticalHeader().hide()
        self.conditions.itemChanged.connect(lambda _item: self.drawing_changed.emit())
        boundary_layout.addWidget(self.conditions)
        inspector = QTabWidget()
        inspector.setMinimumWidth(300)
        inspector.setMaximumWidth(390)
        properties_scroll = QScrollArea()
        properties_scroll.setWidgetResizable(True)
        properties_scroll.setWidget(side)
        inspector.addTab(properties_scroll, "Nesne özellikleri")
        inspector.addTab(boundary_page, "Mesnet / yük")
        self.support_panel = DrawingSupportPanel()
        self.support_panel.apply_requested.connect(self.apply_support)
        inspector.addTab(self.support_panel, "Destek")
        self.inspector = inspector
        split.insertWidget(0, inspector)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([330, 950])
        root.addWidget(self.editor, 1)
        self.status = QLabel(
            "Hazır · Sol tık: nesne seç · Orta tuş: kaydır · Tekerlek: yakınlaştır"
        )
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(22)
        self.status.setMaximumHeight(22) if embedded else None
        self.canvas.cursor_changed.connect(self.cursor_status)
        root.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.build_button = buttons.addButton(
            "Ağ üret ve yeni modele uygula", QDialogButtonBox.ButtonRole.ActionRole
        )
        self.build_button.clicked.connect(self.start_mesh)
        self.cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        self.cancel_button.setText("Çizimi iptal" if embedded else "İptal")
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        if embedded:
            self.build_button.setText("Ağı üret")
            self.build_button.setToolTip(note.text())
            buttons.removeButton(self.build_button)
            buttons.removeButton(self.cancel_button)
            self.build_button.setParent(self.editor)
            self.cancel_button.setParent(self.editor)
            entry.addWidget(self.build_button)
            entry.addWidget(self.cancel_button)
            self.cancel_button.clicked.connect(self.reject)
            buttons.hide()
            for widget in (self.snap, self.osnap, self.grid_toggle, self.ortho):
                widget.hide()
        self.undo_shortcut = QShortcut(QKeySequence.StandardKey.Undo, self)
        self.undo_shortcut.activated.connect(self.undo)
        self.redo_shortcut = QShortcut(QKeySequence.StandardKey.Redo, self)
        self.redo_shortcut.activated.connect(self.redo)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setDefault(False)
        self.refresh(fit=True)
        self.fit_timer = QTimer(self)
        self.fit_timer.setSingleShot(True)
        self.fit_timer.timeout.connect(self.canvas.fit_drawing)
        self.fit_timer.start(0)
        if embedded:
            for shortcut in (self.undo_shortcut, self.redo_shortcut):
                shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

    @property
    def unsaved(self):
        return bool(self.pending) or self.current_drawing() != self.saved_drawing

    @property
    def mesh_outdated(self):
        return bool(self.pending) or self.current_drawing() != self.model_drawing

    def load_model(self, model):
        if self.embedded:
            self.rebuild_notice.setVisible(model is not None)
        self.document = Drawing.from_dict(model.geometry) if model and model.geometry else Drawing()
        self.saved_drawing = self.model_drawing = self.document
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.cancel_drawing()
        self.refresh(fit=True)

    def start_engineering_tool(self, tool):
        kind = "line"
        if tool == "tunnel":
            kind = "region" if self.tunnel_excavation.isChecked() else "hole"
        self.start_tool(kind)
        if tool == "tunnel" and kind == "region":
            self.region.setValue(max((e.region for e in self.document.entities), default=0) + 1)
        prefix = {"pile": "Kazik", "tunnel": "Tunel", "liner": "Kaplama", "bolt": "Ankraj"}[tool]
        names = {e.name for e in self.document.entities}
        n = 1
        while f"{prefix}{n}" in names:
            n += 1
        self.name.setText(f"{prefix}{n}")
        self.circle_mode = self.canvas.circle = tool == "tunnel"
        self.draw_support_kind = (
            "liner"
            if tool == "tunnel" and self.tunnel_lining.isChecked()
            else None
            if tool == "tunnel"
            else tool
        )
        if self.embedded:
            self.set_tool_group(True)
        self.status.setStyleSheet("")
        self.status.setText(
            "Tünel: merkez, ardından çember üzerinde bir nokta seçin."
            if tool == "tunnel"
            else "Destek: noktaları seçin; Enter ile bitirin."
        )

    def set_tool_group(self, supports=False):
        self.geometry_tools.setVisible(not supports)
        self.support_tools.setVisible(supports)

    def apply_support(self):
        index = self.entities.currentRow()
        if index < 0:
            self.show_error("Önce çizimden bir nesne seçin.")
            return
        try:
            entity = self.document.entities[index]
            assignment = self.support_panel.assignment(entity)
            if assignment and assignment.kind in {"pile", "bolt"} and entity.kind != "line":
                raise ValueError("Kazık/ankraj için çizgi seçin; tünel sınırına kaplama atayın.")
            current = self.current_drawing()
            supports = tuple(s for s in current.supports if s.entity != entity.name)
            self.commit(replace(current, supports=supports + ((assignment,) if assignment else ())))
            self.entities.setCurrentRow(index)
        except Exception as exc:
            self.show_error(exc)

    def toggle_labels(self, enabled):
        self.canvas.edge_labels = enabled
        index = self.entities.currentRow()
        selected = self.document.entities[index].name if index >= 0 else None
        self.canvas.redraw(self.document.entities, self.pending, selected)

    def set_grid_spacing(self, value):
        self.canvas.grid = value
        self.canvas.viewport().update()

    def start_tool(self, kind, rectangle=False):
        self.kind.setCurrentIndex(self.kind.findData(kind))
        prefix = {"region": "Bolge", "hole": "Bosluk", "line": "Cizgi"}[kind]
        names = {entity.name for entity in self.document.entities}
        number = 1
        while f"{prefix}{number}" in names:
            number += 1
        self.name.setText(f"{prefix}{number}")
        self.begin_drawing()
        self.rectangle_mode = self.canvas.rectangle = rectangle
        if rectangle:
            self.status.setText("Dikdörtgen: karşılıklı iki köşeyi seçin. Esc: iptal.")

    def _command(self):
        text = self.cmd.text().strip()
        if not text:
            if self.pending:
                self.finish_drawing()
            self.cmd.clear()
            return
        if not self.canvas.drawing:
            self.begin_drawing()
        if self.canvas.command(text):
            self.cmd.clear()
        else:
            self.status.setText("Anlaşılmadı: x,y | @dx,dy | @L<açı")

    def cursor_status(self, text):
        hint = (
            f" · {len(self.pending)} nokta · Enter: bitir"
            if self.canvas.drawing
            else " · Sol tık: seç · Orta tuş: kaydır · Tekerlek: yakınlaştır"
        )
        self.status.setText(text + hint)

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
        self.canvas.supports = {s.entity: s.kind for s in self.document.supports}
        self.entities.blockSignals(True)
        self.entities.clear()
        labels = {
            "region": "Bölge",
            "hole": "Boşluk",
            "line": "Çizgi",
            "pile": "Kazık",
            "liner": "Kaplama",
            "bolt": "Ankraj/çivi",
        }
        self.entities.addItems(
            [
                f"{e.name} · {labels[self.canvas.supports.get(e.name, e.kind)]}"
                for e in self.document.entities
            ]
        )
        self.entities.blockSignals(False)
        rules = {r.edge: r for r in self.document.rules}
        names = [n for e in self.document.entities for n in e.edge_names()]
        self.conditions.blockSignals(True)  # rows are incomplete until the loop ends
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
            pressure.valueChanged.connect(lambda _v: self.drawing_changed.emit())
            self.conditions.setCellWidget(i, 3, pressure)
        self.conditions.blockSignals(False)
        for k in ("h", "E", "nu"):
            value = getattr(self.document, k)
            self.values[k].setRange(
                min(self.values[k].minimum(), value), max(self.values[k].maximum(), value)
            )
            self.values[k].setValue(value)
        self.canvas.redraw(self.document.entities, self.pending)
        if fit:
            self.canvas.fit_drawing()
        self.drawing_changed.emit()

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

    def select_from_canvas(self, index):
        if self.entities.currentRow() == index:
            self.select_entity(index)
        else:
            self.entities.setCurrentRow(index)

    def select_entity(self, index):
        if not 0 <= index < len(self.document.entities):
            self.support_panel.load(None, None)
            self.canvas.redraw(self.document.entities, self.pending)
            return
        e = self.document.entities[index]
        assignment = next((s for s in self.document.supports if s.entity == e.name), None)
        self.support_panel.load(e, assignment)
        self.name.setText(e.name)
        self.kind.setCurrentIndex(self.kind.findData(e.kind))
        self.region.setValue(e.region)
        self.coordinates.setPlainText("\n".join(f"{x:.12g} {y:.12g}" for x, y in e.points))
        self.canvas.redraw(self.document.entities, self.pending, e.name)

    def begin_drawing(self):
        self.circle_mode = self.canvas.circle = False
        self.draw_support_kind = None
        self.rectangle_mode = self.canvas.rectangle = False
        self.pending = []
        self.canvas.redraw(self.document.entities)
        self.canvas.set_drawing(True)
        self.canvas.setFocus()
        self.status.setText("Sol tıkla noktaları girin; Enter/sağ tıkla bitirin. Esc: iptal.")

    def add_point(self, point):
        point = tuple(point)
        if self.circle_mode and len(self.pending) == 1:
            center = np.asarray(self.pending[0])
            radius = float(np.linalg.norm(np.asarray(point) - center))
            if radius <= 1e-6:
                self.show_error("Tünel yarıçapı sıfırdan büyük olmalı.")
                return
            angles = np.linspace(0, 2 * np.pi, 32, endpoint=False)
            self.pending = [
                tuple(center + radius * np.array([np.cos(a), np.sin(a)])) for a in angles
            ]
            self.finish_drawing()
            return
        if self.rectangle_mode and len(self.pending) == 1:
            x, y = self.pending[0]
            u, v = point
            if x == u or y == v:
                self.status.setText("Dikdörtgenin genişliği ve yüksekliği sıfırdan büyük olmalı.")
                return
            self.pending = [(x, y), (u, y), (u, v), (x, v)]
            self.finish_drawing()
            return
        if (
            self.kind.currentData() != "line"
            and self.pending
            and point == self.pending[0]
            and len(self.pending) >= 3
        ):
            self.finish_drawing()
            return
        if not self.pending or point != self.pending[-1]:
            self.pending.append(point)
        self.canvas.redraw(self.document.entities, self.pending)
        if self.draw_support_kind in {"pile", "bolt"} and len(self.pending) == 2:
            self.finish_drawing()

    def cancel_drawing(self):
        self.circle_mode = self.canvas.circle = False
        self.draw_support_kind = None
        self.rectangle_mode = self.canvas.rectangle = False
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
        supports = current.supports
        if self.draw_support_kind:
            supports = (*supports, SupportAssignment(entity.name, self.draw_support_kind))
        self.commit(replace(current, entities=(*current.entities, entity), supports=supports))
        self.entities.setCurrentRow(len(self.document.entities) - 1)
        self.status.setText(f"{entity.name} eklendi · Özelliklerini soldan düzenleyebilirsiniz.")

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
            supports = tuple(
                replace(s, entity=entity.name) if s.entity == old.name else s
                for s in current.supports
            )
            if (
                any(s.entity == entity.name and s.kind in {"pile", "bolt"} for s in supports)
                and entity.kind != "line"
            ):
                raise ValueError("Önce kazık/ankraj desteğini kaldırın; çizgi türü gerekli.")
            self.commit(replace(current, entities=tuple(entities), rules=rules, supports=supports))
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
                supports=tuple(s for s in current.supports if s.entity != old.name),
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
        if self.pending:
            self.show_error("Önce devam eden çizimi bitirin veya iptal edin.")
            return
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
                self.saved_drawing = self.current_drawing()
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
        if self.embedded:
            if self.updated is not None:
                self.model_drawing = worker.drawing
                self.model_ready.emit(self.updated)
            self.worker_stopped.emit()
        elif self._closing:
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
        elif self.embedded:
            self.cancel_drawing()
        else:
            super().reject()

    def closeEvent(self, event):
        if self.worker:
            self.reject()
            event.ignore()
        else:
            event.accept()

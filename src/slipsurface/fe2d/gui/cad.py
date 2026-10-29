"""Native CAD workspace: transactional drawing, conditions, DXF and mesh worker."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QShortcut,
)
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
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import api
from ..cad.dxf import read_dxf, write_dxf
from ..cad.geometry import BoundaryRule, Drawing, Entity, snap_point
from ..cad.supports import SupportAssignment
from .drawing_supports import DrawingSupportPanel
from .icons import icon
from .rulers import ruled_canvas

IDLE_HINT = (
    "Hazır · Sol tık: seç · Sürükle: kaydır · Köşe sürükle: taşı · "
    "Çift tık: özellikler · Sağ tık: menü · Tekerlek: yakınlaştır"
)


class CadCanvas(QGraphicsView):
    point_added = Signal(object)
    finish_requested = Signal()
    cancelled = Signal()
    cursor_changed = Signal(str)
    mouse_world = Signal(float, float)
    entity_selected = Signal(int)
    entity_activated = Signal(int)
    context_requested = Signal(int, str, object)
    vertex_moved = Signal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QColor("#f4f8fb"))
        self.setMouseTracking(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        # Keep the drawing centred when the workspace resizes (dock/notice/panels toggling).
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
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
        self._press_position = None
        self._drag_vertex = None
        self._auto_fit = False
        self.placement = None  # outline (relative) of a tunnel being placed by a click
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
        region_palette = ("#65b4c8", "#e2b878", "#82c39b", "#b39ddb", "#e5989b", "#80cbc4")
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
            fill_hex = (
                "#ffffff"
                if e.kind == "hole"
                else region_palette[(max(int(e.region), 1) - 1) % len(region_palette)]
            )
            brush = QColor(fill_hex)
            brush.setAlpha(85 if e.kind == "region" else 255)
            item = self.scene().addPath(path, pen)
            if e.kind != "line":
                item.setBrush(brush)
            item.setZValue(-e.shape().area if e.kind != "line" else 1)
            if e.kind == "region":
                rep = e.shape().representative_point()
                tag_lbl = self.scene().addSimpleText(f"{e.name} (B{e.region})")
                tag_lbl.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
                tag_lbl.setPos(float(rep.x), float(-rep.y))
                tag_lbl.setBrush(QColor("#1e3a4c"))
                tag_lbl.setZValue(1.5)
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
        size = max(rect.width(), rect.height(), 10.0)
        self.setSceneRect(self.sceneRect().united(rect.adjusted(-size, -size, size, size)))

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
        # Stay fitted through layout changes (stale size of a hidden page, docks, panels)
        # until the user zooms or pans.
        self._auto_fit = True
        if self.isVisible() and self.viewport().width() > 1:
            self._apply_fit()

    def _apply_fit(self):
        points = [p for e in self.entities for p in e.points]
        if points:
            p = np.asarray(points)
            x0, y0 = p.min(axis=0)
            x1, y1 = p.max(axis=0)
            margin = max(x1 - x0, y1 - y0, 1) * 0.12
            rect = QRectF(x0 - margin, -y1 - margin, x1 - x0 + 2 * margin, y1 - y0 + 2 * margin)
        else:
            rect = QRectF(-2, -8, 16, 10)
        # Generous, square panning room so any point can be brought to the view centre.
        room = max(rect.width(), rect.height()) * 20
        self.setSceneRect(rect.adjusted(-room, -room, room, room))
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        self.centerOn(rect.center())

    def showEvent(self, event):
        super().showEvent(event)
        if self._auto_fit:
            QTimer.singleShot(0, lambda: self._auto_fit and self._apply_fit())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._auto_fit and self.isVisible():
            self._apply_fit()

    def _tolerance(self, pixels):
        return pixels / max(abs(self.transform().m11()), 1e-12)

    def hit_entity(self, position):
        """Index of the entity under ``position`` (edges before interiors), or -1."""
        from shapely.geometry import Point

        p = self.mapToScene(position)
        point = Point(p.x(), -p.y())
        tolerance = self._tolerance(8)
        hits = []
        for index, entity in enumerate(self.entities):
            shape = entity.shape()
            boundary = shape if entity.kind == "line" else shape.boundary
            distance = boundary.distance(point)
            if distance <= tolerance:
                hits.append((0, distance, index))
            elif entity.kind != "line" and shape.covers(point):
                hits.append((1, shape.area, index))
        return min(hits)[2] if hits else -1

    def hit_edge(self, position, index):
        """Name of the edge of entity ``index`` nearest to ``position`` within 8 px."""
        if not 0 <= index < len(self.entities):
            return ""
        p = self.mapToScene(position)
        q = np.array([p.x(), -p.y()])
        best, name = self._tolerance(8), ""
        entity = self.entities[index]
        for edge, (a, b) in zip(entity.edge_names(), entity.segments()):
            a, b = np.asarray(a, float), np.asarray(b, float)
            d = b - a
            t = np.clip(np.dot(q - a, d) / max(np.dot(d, d), 1e-30), 0, 1)
            dist = float(np.linalg.norm(a + t * d - q))
            if dist <= best:
                best, name = dist, edge
        return name

    def hit_vertex(self, position):
        p = self.mapToScene(position)
        q = np.array([p.x(), -p.y()])
        best, found = self._tolerance(7), None
        for entity in self.entities:
            for vertex in entity.points:
                dist = float(np.linalg.norm(np.asarray(vertex) - q))
                if dist <= best:
                    best, found = dist, tuple(vertex)
        return found

    def _vertex_neighbours(self, vertex):
        pairs = []
        for entity in self.entities:
            pts = list(entity.points)
            for i, v in enumerate(pts):
                if tuple(v) != vertex:
                    continue
                closed = entity.kind != "line"
                if i > 0 or closed:
                    pairs.append(pts[i - 1])
                if i + 1 < len(pts) or closed:
                    pairs.append(pts[(i + 1) % len(pts)])
        return pairs

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
        if self._drag_vertex is not None:
            old, new, neighbours = self._drag_vertex
            pen = QPen(QColor("#ed8c24"), 2, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            for x, y in neighbours:
                painter.drawLine(QPointF(x, -y), QPointF(new[0], -new[1]))
            radius = self._tolerance(5)
            painter.drawRect(QRectF(new[0] - radius, -new[1] - radius, 2 * radius, 2 * radius))
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
            if self.placement is not None:
                pen = QPen(QColor("#b56324"), 2, Qt.PenStyle.DashLine)
                pen.setCosmetic(True)
                painter.setPen(pen)
                painter.drawPolygon(
                    QPolygonF([QPointF(x + u, -(y + v)) for u, v in self.placement])
                )

    def mouseMoveEvent(self, event):
        position = event.position().toPoint()
        if self._pan_position is not None:
            delta = position - self._pan_position
            self._pan_position = position
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        if (
            self._press_position is not None
            and (position - self._press_position).manhattanLength() > 4
        ):
            # Left-drag on empty space or an object pans, like the middle button.
            self._pan_position = self._press_position
            self._press_position = None
            self._auto_fit = False
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.mouseMoveEvent(event)
            return
        q, mode = self.mapped_point(position)
        if self._drag_vertex is not None:
            self._drag_vertex = (self._drag_vertex[0], q, self._drag_vertex[2])
        self.preview = q
        self.mouse_world.emit(*q)
        self.cursor_changed.emit(f"x={q[0]:.4f} m   y={q[1]:.4f} m   · {mode}")
        self.viewport().update()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_position = event.position().toPoint()
            self._auto_fit = False
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
            position = event.position().toPoint()
            vertex = self.hit_vertex(position)
            if vertex is not None:
                self._drag_vertex = (vertex, vertex, self._vertex_neighbours(vertex))
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self._press_position = position
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        button = event.button()
        if button in (Qt.MouseButton.MiddleButton, Qt.MouseButton.LeftButton) and (
            self._pan_position is not None
        ):
            self._pan_position = None
            self.setCursor(
                Qt.CursorShape.CrossCursor if self.drawing else Qt.CursorShape.ArrowCursor
            )
            event.accept()
        elif button == Qt.MouseButton.LeftButton and self._drag_vertex is not None:
            old, new, _ = self._drag_vertex
            self._drag_vertex = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            if tuple(new) != tuple(old):
                self.vertex_moved.emit(tuple(old), tuple(new))
            else:
                self.entity_selected.emit(self.hit_entity(event.position().toPoint()))
            self.viewport().update()
            event.accept()
        elif button == Qt.MouseButton.LeftButton and self._press_position is not None:
            self._press_position = None
            self.entity_selected.emit(self.hit_entity(event.position().toPoint()))
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseDoubleClickEvent(event)
        elif self.drawing:
            self.finish_requested.emit()
        else:
            self._press_position = None
            self.entity_activated.emit(self.hit_entity(event.position().toPoint()))
        event.accept()

    def contextMenuEvent(self, event):
        if self.drawing:
            event.accept()
            return
        index = self.hit_entity(event.pos())
        self.context_requested.emit(index, self.hit_edge(event.pos(), index), event.globalPos())
        event.accept()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.drawing:
            self.finish_requested.emit()
        elif event.key() == Qt.Key.Key_Escape and self.drawing:
            self.cancelled.emit()
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self._auto_fit = False
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
    structure_requested = Signal(str)

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
        self.split_mode = False
        self.placing = None  # TunnelDesign waiting for its centre click
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
            ("Uygula", self.update_entity),
            ("Sil", self.delete_entity),
        ]:
            b = QPushButton(title)
            b.clicked.connect(callback)
            form.addRow(b)
        self.canvas = CadCanvas()
        self.canvas.point_added.connect(self.add_point)
        self.canvas.finish_requested.connect(self.finish_drawing)
        self.canvas.cancelled.connect(self.cancel_drawing)
        self.canvas.entity_selected.connect(self.select_from_canvas)
        self.canvas.entity_activated.connect(self.activate_entity)
        self.canvas.context_requested.connect(self.canvas_menu)
        self.canvas.vertex_moved.connect(self.move_vertex)
        self.tunnel_lining = QAction("Tünele kaplama ekle", self)
        self.tunnel_lining.setCheckable(True)
        self.tunnel_lining.setChecked(True)
        self.tunnel_excavation = QAction("Tünel içini aşamalı kazı bölgesi yap", self)
        self.tunnel_excavation.setCheckable(True)
        self.tool_strip = self._build_tool_strip()
        drafting = QHBoxLayout()
        drafting.setContentsMargins(0, 0, 0, 0)
        drafting.setSpacing(0)
        drafting.addWidget(self.tool_strip)
        drafting.addWidget(ruled_canvas(self.canvas), 1)
        editor_layout.addLayout(drafting, 1)
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
        properties_scroll = QScrollArea()
        properties_scroll.setWidgetResizable(True)
        properties_scroll.setWidget(side)
        inspector.addTab(properties_scroll, "Nesne özellikleri")
        inspector.addTab(boundary_page, "Mesnet / yük")
        self.support_panel = DrawingSupportPanel()
        self.support_panel.apply_requested.connect(self.apply_support)
        inspector.addTab(self.support_panel, "Destek")
        self.inspector = inspector
        # Properties open on demand (double-click / right-click) instead of a fixed side panel.
        self.inspector_window = QDialog(self, Qt.WindowType.Tool)
        self.inspector_window.setWindowTitle("Özellikler")
        self.inspector_window.resize(380, 620)
        QVBoxLayout(self.inspector_window).addWidget(inspector)
        root.addWidget(self.editor, 1)
        self.status = QLabel(IDLE_HINT)
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
        self._mark_tool(tool)
        self.status.setStyleSheet("")
        self.status.setText(
            "Tünel: merkez, ardından çember üzerinde bir nokta seçin."
            if tool == "tunnel"
            else "Destek: noktaları seçin; Enter ile bitirin."
        )

    def _build_tool_strip(self):
        """Plaxis-style vertical icon strip: pick a tool, then draw on the canvas."""
        strip = QToolBar("Çizim araçları")
        strip.setOrientation(Qt.Orientation.Vertical)
        strip.setIconSize(QSize(20, 20))
        strip.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        strip.setStyleSheet("QToolButton { padding: 3px; margin: 1px; }")
        self.tool_group = QActionGroup(self)
        self.tool_group.setExclusive(True)
        self.tool_actions = {}

        def tool(key, title, ic, slot, shortcut=None):
            a = QAction(icon(ic), title, strip)
            a.setCheckable(True)
            a.setToolTip(f"{title} ({shortcut})" if shortcut else title)
            if shortcut:
                # A QShortcut, not a dialog action: actions owned by the dialog would be
                # removed from it while it is half-destroyed.
                key_shortcut = QShortcut(QKeySequence(shortcut), self)
                key_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
                key_shortcut.activated.connect(a.trigger)
            a.triggered.connect(slot)
            self.tool_group.addAction(a)
            self.tool_actions[key] = a
            strip.addAction(a)
            return a

        tool("select", "Seç / düzenle", "select", self.cancel_drawing, "Esc")
        strip.addSeparator()
        tool("region", "Çokgen bölge", "cad_polygon", lambda: self.start_tool("region"), "P")
        tool(
            "rect",
            "Dikdörtgen bölge",
            "cad_rect",
            lambda: self.start_tool("region", rectangle=True),
            "R",
        )
        tool("split", "Kazı / bölme çizgisi", "cad_split", lambda: self.start_tool("split"), "B")
        tool("hole", "Boşluk", "cad_hole", lambda: self.start_tool("hole"), "H")
        tool("line", "Ağ kısıt çizgisi", "cad_polyline", lambda: self.start_tool("line"), "L")
        strip.addSeparator()
        for key, title, ic, shortcut in [
            ("pile", "Kazık", "cad_pile", "K"),
            ("tunnel", "Tünel (merkez + yarıçap)", "cad_tunnel", "T"),
            ("liner", "Kaplama / kiriş", "cad_liner", "C"),
            ("bolt", "Tek bulon / ankraj / zemin çivisi", "bolt", "A"),
        ]:
            tool(key, title, ic, lambda _=False, k=key: self.start_engineering_tool(k), shortcut)
        tool("natm", "NATM tünel tasarımcısı", "cad_natm", self.open_tunnel_designer, "N")
        pattern = strip.addAction(icon("bolt_pattern"), "Bulon paterni (seçili çizgi boyunca)")
        pattern.triggered.connect(self.bolt_pattern)
        tunnel_button = strip.widgetForAction(self.tool_actions["tunnel"])
        if isinstance(tunnel_button, QToolButton):
            options = QMenu(tunnel_button)
            options.addAction("NATM tünel tasarımcısı…", self.open_tunnel_designer)
            options.addSeparator()
            options.addAction(self.tunnel_lining)
            options.addAction(self.tunnel_excavation)
            tunnel_button.setMenu(options)
            tunnel_button.setPopupMode(QToolButton.ToolButtonPopupMode.DelayedPopup)
            self.tool_actions["tunnel"].setToolTip(
                "Tünel (merkez + yarıçap) · T · Basılı tutun: kaplama / kazı seçenekleri"
            )
        strip.addSeparator()
        for title, ic, slot in [
            ("Tümünü sığdır (F2)", "zoom_all", self.canvas.fit_drawing),
            ("Seçileni sil (Del)", "delete", self.delete_entity),
            ("Özellikler / mesnet / destek", "settings", lambda: self.show_inspector()),
            ("Kaplama / iksa tasarımcısı", "facing_props", self.open_lining_designer),
        ]:
            a = strip.addAction(icon(ic), title)
            a.triggered.connect(slot)
        self.delete_shortcut = QShortcut(QKeySequence.StandardKey.Delete, self)
        self.delete_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.delete_shortcut.activated.connect(self.delete_entity)
        self.tool_actions["select"].setChecked(True)
        return strip

    def _mark_tool(self, key):
        action = self.tool_actions.get(key)
        if action is not None and not action.isChecked():
            action.setChecked(True)

    def show_inspector(self, tab=None):
        """Open the floating properties window, optionally on a given tab."""
        if tab is not None:
            self.inspector.setCurrentIndex(tab)
        self.inspector_window.show()
        self.inspector_window.raise_()

    def activate_entity(self, index):
        """Double-click: a meshed support opens its N–V–M diagram, anything else its properties."""
        if not 0 <= index < len(self.document.entities):
            return
        self.select_from_canvas(index)
        entity = self.document.entities[index]
        support = next((s for s in self.document.supports if s.entity == entity.name), None)
        if support is not None and not self.mesh_outdated:
            self.structure_requested.emit(f"cad_{entity.name}")
            return
        self.show_inspector(2 if support is not None else 0)

    def canvas_menu(self, index, edge, global_pos):
        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        if 0 <= index < len(self.document.entities):
            self.select_from_canvas(index)
            entity = self.document.entities[index]
            support = next((s for s in self.document.supports if s.entity == entity.name), None)
            header = menu.addAction(entity.name)
            header.setEnabled(False)
            menu.addAction("Özellikler…", lambda: self.show_inspector(0))
            menu.addAction("Destek ata / düzenle…", lambda: self.show_inspector(2))
            if entity.kind == "line":
                menu.addAction(icon("bolt_pattern"), "Bulon paterni…", self.bolt_pattern)
            if support is not None:
                diagram = menu.addAction(
                    "Kesit tesirleri (N–V–M)…",
                    lambda: self.structure_requested.emit(f"cad_{entity.name}"),
                )
                diagram.setEnabled(not self.mesh_outdated)
            if edge:
                menu.addSeparator()
                rule = next(
                    (r for r in self.current_drawing().rules if r.edge == edge),
                    BoundaryRule(edge),
                )
                title = menu.addAction(f"Kenar {edge}")
                title.setEnabled(False)
                for label, field in [("ux sabit", "ux"), ("uy sabit", "uy")]:
                    a = menu.addAction(label)
                    a.setCheckable(True)
                    a.setChecked(getattr(rule, field))
                    a.triggered.connect(
                        lambda on, f=field, e=edge: self.set_edge_rule(e, **{f: on})
                    )
                menu.addAction(
                    f"Basınç… ({rule.pressure:g} kPa)", lambda e=edge: self.ask_pressure(e)
                )
                menu.addAction("Mesnet / yük tablosu…", lambda: self.show_inspector(1))
            menu.addSeparator()
            menu.addAction(icon("delete"), "Sil", self.delete_entity)
        else:
            for key in (
                "region",
                "rect",
                "split",
                "hole",
                "line",
                "pile",
                "natm",
                "tunnel",
                "bolt",
            ):
                tool = self.tool_actions[key]
                menu.addAction(tool.icon(), tool.text(), tool.trigger)
            menu.addSeparator()
            menu.addAction("Tümünü sığdır", self.canvas.fit_drawing)
            menu.addAction("Mesnet / yük tablosu…", lambda: self.show_inspector(1))
            menu.addAction("Ağ ayarları (h, E, ν)…", lambda: self.show_inspector(0))
        menu.exec(global_pos)

    def set_edge_rule(self, edge, **changes):
        current = self.current_drawing()
        rule = next((r for r in current.rules if r.edge == edge), BoundaryRule(edge))
        rule = replace(rule, **changes)
        rules = tuple(r for r in current.rules if r.edge != edge)
        if rule.ux or rule.uy or rule.pressure:
            rules += (rule,)
        self.commit(replace(current, rules=rules))
        self.status.setText(
            f"{edge}: ux={'sabit' if rule.ux else 'serbest'}, "
            f"uy={'sabit' if rule.uy else 'serbest'}, p={rule.pressure:g} kPa"
        )

    def ask_pressure(self, edge):
        rule = next((r for r in self.current_drawing().rules if r.edge == edge), BoundaryRule(edge))
        value, ok = QInputDialog.getDouble(
            self,
            "Kenar basıncı",
            f"{edge} · basınç (kPa, içeri pozitif)",
            rule.pressure,
            -1e12,
            1e12,
            3,
        )
        if ok:
            self.set_edge_rule(edge, pressure=value)

    def move_vertex(self, old, new):
        """Move every coincident copy of a vertex so neighbouring regions stay conforming."""
        current = self.current_drawing()
        old = np.asarray(old, float)

        def moved(points):
            return tuple(
                tuple(new) if np.allclose(point, old, rtol=0, atol=1e-9) else tuple(point)
                for point in points
            )

        entities = tuple(replace(e, points=moved(e.points)) for e in current.entities)
        index = self.entities.currentRow()
        self.commit(replace(current, entities=entities))
        if index >= 0:
            self.entities.setCurrentRow(index)
        self.status.setText(f"Köşe taşındı → x={new[0]:.4g}, y={new[1]:.4g} m · Ctrl+Z: geri al")

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
        if kind == "split":
            self.kind.setCurrentIndex(self.kind.findData("line"))
            self.begin_drawing()
            self._mark_tool("split")
            self.split_mode = True
            self.status.setText(
                "Kazı / bölme çizgisi: bölge sınırları veya kazık arasında noktaları seçin "
                "(Enter/sağ tık: bölgeyi böl)."
            )
            return
        self.kind.setCurrentIndex(self.kind.findData(kind))
        if kind == "region":
            next_r = (
                max((e.region for e in self.document.entities if e.kind == "region"), default=0) + 1
            )
            self.region.setValue(next_r)
        self._mark_tool("rect" if rectangle else kind)
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
            f" · {len(self.pending)} nokta · Çift tık / Enter / sağ tık: bitir · Esc: iptal"
            if self.canvas.drawing
            else " · Sürükle: kaydır · Köşe sürükle: taşı · Çift tık: özellikler · Sağ tık: menü"
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
        self.placing = self.canvas.placement = None
        self.circle_mode = self.canvas.circle = False
        self.draw_support_kind = None
        self.rectangle_mode = self.canvas.rectangle = False
        self.split_mode = False
        self.pending = []
        self.canvas.redraw(self.document.entities)
        self.canvas.set_drawing(True)
        self.canvas.setFocus()
        self.status.setText("Sol tıkla noktaları girin; Enter/sağ tıkla bitirin. Esc: iptal.")

    def add_point(self, point):
        point = tuple(point)
        if self.placing is not None:
            self.insert_tunnel(self.placing, point)
            return
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
        self.placing = self.canvas.placement = None
        self.circle_mode = self.canvas.circle = False
        self.draw_support_kind = None
        self.rectangle_mode = self.canvas.rectangle = False
        self.split_mode = False
        self.pending = []
        self.canvas.set_drawing(False)
        self.canvas.redraw(self.document.entities)
        if hasattr(self, "tool_actions"):
            self._mark_tool("select")

    def finish_drawing(self):
        if not self.pending:
            return
        try:
            if self.split_mode:
                updated = self.current_drawing().split_with_line(self.pending)
                self.commit(updated)
                self.entities.setCurrentRow(len(self.document.entities) - 1)
                new_ent = self.document.entities[-1]
                self.status.setText(
                    f"{new_ent.name} (Bölge {new_ent.region}) oluşturuldu · "
                    "Aşamalar sekmesinde bu bölgeyi kazabilirsiniz."
                )
            else:
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
            updated = replace(current, entities=tuple(entities), rules=rules, supports=supports)
            self.commit(updated.renamed(old.name, entity.name))
            self.status.setText("Geometri güncellendi; bu öğenin kenar koşullarını yeniden atayın.")
        except Exception as exc:
            self.show_error(exc)

    def delete_entity(self):
        index = self.entities.currentRow()
        if index < 0:
            return
        current = self.current_drawing()
        self.commit(current.without_entity(current.entities[index].name))

    # ------------------------------------------------------------ NATM / bolts / lining
    def open_tunnel_designer(self):
        from .tunnel_designer import TunnelDesignerDialog

        self.cancel_drawing()
        dialog = TunnelDesignerDialog(getattr(self, "last_tunnel", None), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        design = self.last_tunnel = dialog.design()
        if dialog.placement == dialog.PLACE_COORDS:
            self.insert_tunnel(design, dialog.center())
            return
        self.begin_drawing()
        self._mark_tool("natm")
        self.placing = design
        self.canvas.placement = [tuple(p) for p in design.section.outline()]
        self.status.setText(
            "NATM tünel: tepe yayı merkezini (üzengi seviyesi) tıklayın. Esc: iptal."
        )

    def insert_tunnel(self, design, center):
        from ..cad.tunnel import place_tunnel

        try:
            updated = place_tunnel(self.current_drawing(), design, center)
        except Exception as exc:
            self.cancel_drawing()
            self.show_error(exc)
            return
        added = len(updated.sequence) - len(self.document.sequence)
        self.commit(updated)
        self.status.setStyleSheet("")
        self.status.setText(
            f"Tünel yerleştirildi ({center[0]:.3g}, {center[1]:.3g}) · {added} yapım aşaması; "
            "ağ üretilince aşamalara eklenir."
        )

    def bolt_pattern(self):
        from ..cad.tunnel import bolt_pattern_along
        from .tunnel_designer import BoltPatternDialog

        index = self.entities.currentRow()
        if not 0 <= index < len(self.document.entities) or (
            self.document.entities[index].kind != "line"
        ):
            self.show_error(
                "Bulon paterni için önce bir çizgi (duvar, kaplama, şev çizgisi) seçin."
            )
            return
        host = self.document.entities[index].name
        dialog = BoltPatternDialog(host, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.commit(
                bolt_pattern_along(
                    self.current_drawing(),
                    host,
                    dialog.count.value(),
                    dialog.length.value(),
                    dialog.angle.value(),
                    dialog.pattern(),
                    margin=dialog.margin.value(),
                )
            )
            self.status.setStyleSheet("")
            self.status.setText(f"{dialog.count.value()} bulon eklendi · {host}")
        except Exception as exc:
            self.show_error(exc)

    def open_lining_designer(self):
        """Edit the composite lining library; with a liner selected, apply it to that liner."""
        from .tunnel_designer import LiningDesignerDialog

        dialog = LiningDesignerDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        index = self.entities.currentRow()
        if not 0 <= index < len(self.document.entities):
            return
        entity = self.document.entities[index]
        support = next((s for s in self.document.supports if s.entity == entity.name), None)
        if support is None or support.kind != "liner":
            return
        current = self.current_drawing()
        lined = replace(support, properties=dialog.lining().liner_properties())
        self.commit(
            replace(
                current,
                supports=tuple(lined if s is support else s for s in current.supports),
            )
        )
        self.entities.setCurrentRow(index)
        self.status.setText(f"{entity.name}: kompozit kaplama özellikleri uygulandı.")

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

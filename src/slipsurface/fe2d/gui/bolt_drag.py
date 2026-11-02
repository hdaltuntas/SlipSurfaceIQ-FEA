"""Mouse-selected bolt intervals and a reversible, exact placement preview."""

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPen

from ..cad.bolt_path import boundary_path, project_boundary, selected_path
from ..cad.tunnel import BoltPattern, bolt_layout


class BoltDrag:
    def __init__(self, canvas):
        self.canvas = canvas
        self.reset()

    def reset(self):
        self.enabled = False
        self.host = None
        self.start = self.end = self.previous = None
        self.path = []
        self.layout = []
        self.angle = 90.0
        self.valid_endpoint = False

    def arm(self):
        self.reset()
        self.enabled = True
        self.canvas.setCursor(Qt.CursorShape.CrossCursor)

    def _world(self, position):
        point = self.canvas.mapToScene(position)
        return np.array([point.x(), -point.y()])

    def press(self, position):
        point = self._world(position)
        candidates = []
        for index, entity in enumerate(self.canvas.entities):
            support = self.canvas.supports.get(entity.name)
            if support == "bolt":
                continue
            station, distance = project_boundary(entity, point)
            if distance <= self.canvas._tolerance(8):
                # Prefer a coincident lining to the region: it excludes internal cuts.
                priority = 0 if support == "liner" else 1
                candidates.append((round(distance, 7), priority, index, station))
        if not candidates:
            self.canvas.cursor_changed.emit("Start on a boundary or lining; drag along its edge.")
            return
        _, _, index, station = min(candidates)
        self.host = self.canvas.entities[index]
        self.start = self.end = self.previous = station
        self.angle = self._outward_angle(point)
        self.path, self.layout = [], []
        self.valid_endpoint = True

    def _outward_angle(self, point):
        """Choose the exterior of the smallest adjacent region, including open liners."""
        from shapely.geometry import Point

        pts, stations = boundary_path(self.host)
        k = min(int(np.searchsorted(stations, self.start, side="right")) - 1, len(pts) - 2)
        tangent = pts[k + 1] - pts[k]
        normal = np.array([-tangent[1], tangent[0]]) / max(np.linalg.norm(tangent), 1e-30)
        regions = [e.shape() for e in self.canvas.entities if e.kind in {"region", "hole"}]
        regions = [r for r in regions
                   if r.boundary.distance(Point(point)) < self.canvas._tolerance(9)]
        if regions:
            region = min(regions, key=lambda r: r.area)
            mid = (pts[k] + pts[k + 1]) / 2
            if region.covers(Point(mid + normal * min(np.linalg.norm(tangent) / 10, 0.01))):
                return -90.0
        return 90.0

    def move(self, position):
        if self.host is None:
            return
        station, distance = project_boundary(self.host, self._world(position))
        self.valid_endpoint = distance <= self.canvas._tolerance(18)
        if not self.valid_endpoint:
            self.canvas.cursor_changed.emit("Follow the highlighted boundary to set the end point.")
            return
        pts, stations = boundary_path(self.host)
        delta = station - self.previous
        if np.allclose(pts[0], pts[-1]):
            total = stations[-1]
            delta = (delta + total / 2) % total - total / 2
        self.end += delta
        self.previous = station
        self.preview(BoltPattern(), self.angle, 0.0)
        self.canvas.cursor_changed.emit(
            f"{self.host.name} · Selected length {abs(self.end - self.start):.2f} m · "
            f"{len(self.layout)} bolts · Release to adjust spacing, length and direction. "
            "Esc: cancel."
        )

    def release(self, position):
        self.move(position)
        if self.host is None:
            return
        if not self.valid_endpoint or abs(self.end - self.start) < self.canvas._tolerance(4):
            self.host = None
            self.path, self.layout = [], []
            self.canvas.viewport().update()
            return
        if not self.layout:
            return
        self.enabled = False
        self.canvas.bolt_range_selected.emit(self.host.name, (self.start, self.end))

    def preview(self, pattern, angle, margin):
        if self.host is None:
            return
        try:
            selected = (self.start, self.end)
            self.path = selected_path(self.host, selected)
            self.layout = bolt_layout(self.host, pattern, angle, margin, selected_range=selected)
        except ValueError:
            self.path, self.layout = [], []
        self.canvas.viewport().update()

    def paint(self, painter):
        pen = QPen(QColor("#1686c7"), 4)
        pen.setCosmetic(True)
        painter.setPen(pen)
        for a, b in zip(self.path, self.path[1:]):
            painter.drawLine(QPointF(a[0], -a[1]), QPointF(b[0], -b[1]))
        pen = QPen(QColor("#15835f"), 2, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        for _, _, head, tail in self.layout:
            painter.drawLine(QPointF(head[0], -head[1]), QPointF(tail[0], -tail[1]))

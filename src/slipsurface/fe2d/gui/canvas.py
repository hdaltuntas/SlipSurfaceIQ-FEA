"""Native QGraphicsView mesh/result canvas and convergence plot."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView, QWidget

from ..core.enums import ElemType
from ..post.recovery import principal_stresses

_ORDERS = {
    ElemType.T3: [0, 1, 2],
    ElemType.T6: [0, 3, 1, 4, 2, 5],
    ElemType.Q4: [0, 1, 2, 3],
    ElemType.Q8: [0, 4, 1, 5, 2, 6, 3, 7],
}


class MeshCanvas(QGraphicsView):
    queried = Signal(str)
    mouse_world = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setBackgroundBrush(QColor("#f5f8fa"))
        self.model = self.stage = None
        self.cell_count = 0
        self.legend = "Geometri · m"

    def show_model(
        self,
        model,
        stage=None,
        field="|u|",
        deform=0.0,
        *,
        result=None,
        principal=False,
        plastic_points=False,
    ):
        self.model, self.stage = model, stage
        self.scene().clear()
        self.cell_count = 0
        self.principal_count = self.plastic_count = 0
        self.overlay_note = ""
        mesh = model.mesh
        coords = mesh.coords.copy()
        if stage is not None:
            coords += deform * np.nan_to_num(stage.u)
        self.display_coords = coords
        cells, values = [], []
        for block in mesh.continuum_blocks():
            active = (
                np.ones(block.ne, bool)
                if stage is None
                else stage.active.get(block.tag, np.ones(block.ne, bool))
            )
            for e in np.flatnonzero(active):
                conn = block.conn[e]
                if stage is None:
                    value = float(block.region[e])
                elif field in ("|u|", "ux", "uy"):
                    v = stage.u[conn]
                    value = (
                        np.linalg.norm(v, axis=1).mean()
                        if field == "|u|"
                        else v[:, 0 if field == "ux" else 1].mean()
                    )
                elif field == "plastic":
                    value = (stage.plastic[block.tag][e] > 0).mean()
                elif field in ("pore", "excess_pore"):
                    data = getattr(stage, field).get(block.tag)
                    value = float(data[e].mean()) if data is not None else 0.0
                else:
                    sig = stage.sig[block.tag][e]
                    value = (
                        sig[:, ("sxx", "syy", "szz", "txy").index(field)].mean()
                        if field in ("sxx", "syy", "szz", "txy")
                        else principal_stresses(sig)[field].mean()
                    )
                cells.append((block, e, coords[conn[_ORDERS[block.etype]]]))
                values.append(float(value))
        finite = np.asarray(values)[np.isfinite(values)]
        lo, hi = (float(finite.min()), float(finite.max())) if finite.size else (0.0, 0.0)
        span = hi - lo
        constant = span <= 1e-10 * max(abs(lo), abs(hi), 1.0)
        self.field_range = (lo, hi)
        self.constant_field = constant
        pen = QPen(QColor("#42657b"), 0)
        for (block, e, xy), value in zip(cells, values):
            t = (value - lo) / (hi - lo) if not constant and np.isfinite(value) else 0.5
            color = QColor.fromHsvF(0.62 * (1 - np.clip(t, 0, 1)), 0.65, 0.9)
            poly = QPolygonF([QPointF(float(x), float(-y)) for x, y in xy])
            item = self.scene().addPolygon(poly, pen, color)
            item.setToolTip(f"{block.tag} · {e} · {field if stage else 'Bölge'}: {value:.8g}")
            self.cell_count += 1
        for block in mesh.blocks:
            if block.etype not in (ElemType.BEAM2, ElemType.BAR2):
                continue
            active = (
                np.ones(block.ne, bool)
                if stage is None
                else stage.active.get(block.tag, np.ones(block.ne, bool))
            )
            p = QPen(QColor("#e57326" if block.etype is ElemType.BEAM2 else "#166534"), 2)
            p.setCosmetic(True)
            for conn in block.conn[active]:
                a, b = coords[conn]
                self.scene().addLine(a[0], -a[1], b[0], -b[1], p)
        unit = "m" if field in ("|u|", "ux", "uy") else "oran" if field == "plastic" else "kPa"
        self.legend = (
            "Geometri · m"
            if stage is None
            else f"{field} · {unit} · eleman ortalaması · {lo:.5g} … {hi:.5g}"
            f" · deformasyon ×{deform:g}"
        )
        if stage is not None and result is not None:
            self.draw_overlays(result, stage, coords, principal, plastic_points)
            self.legend += self.overlay_note
        self.fit_model()

    def draw_overlays(self, result, stage, coords, principal, plastic):
        extent = max(float(np.ptp(coords, axis=0).max()), 1e-9)
        records = []
        for block in result.model.mesh.continuum_blocks():
            active = stage.active.get(block.tag, np.ones(block.ne, bool))
            g = result.geom[block.tag]
            xy = np.einsum("gn,enj->egj", g.N, coords[block.conn[active]])
            sig = stage.sig[block.tag][active]
            flags = stage.plastic[block.tag][active]
            records.extend(zip(xy.reshape(-1, 2), sig.reshape(-1, 4), flags.ravel()))
        if not records:
            return
        if plastic:
            selected = [(xy, flag) for xy, _, flag in records if flag > 0]
            stride = max(1, int(np.ceil(len(selected) / 20000)))
            radius = extent * 0.0015
            for xy, flag in selected[::stride]:
                item = self.scene().addEllipse(
                    float(xy[0] - radius),
                    float(-xy[1] - radius),
                    2 * radius,
                    2 * radius,
                    QPen(QColor("#850f23"), 0),
                    QColor("#ef4444"),
                )
                item.setToolTip(f"Plastik Gauss noktası · bayrak {int(flag)}")
                self.plastic_count += 1
            self.overlay_note += f" · plastik GP {self.plastic_count}/{len(selected)}"
        if principal:
            stride = max(1, int(np.ceil(len(records) / 1200)))
            points = records[::stride]
            tensors = np.array([[[sig[0], sig[3]], [sig[3], sig[1]]] for _, sig, _ in points])
            values, vectors = np.linalg.eigh(tensors)
            maximum = max(float(np.abs(values).max()), 1e-12)
            for (xy, _, _), stresses, axes in zip(points, values, vectors):
                for k in range(2):
                    stress, direction = stresses[k], axes[:, k]
                    if abs(stress) < maximum * 1e-10:
                        continue
                    half = extent * 0.012 * abs(stress) / maximum
                    pen = QPen(QColor("#b42331" if stress > 0 else "#174ea6"), 1.2)
                    pen.setCosmetic(True)
                    for sign in [-1, 1]:
                        outer = xy + sign * half * direction
                        tip, tail = (outer, xy) if stress > 0 else (xy, outer)
                        self.scene().addLine(
                            float(tail[0]), float(-tail[1]), float(tip[0]), float(-tip[1]), pen
                        )
                        v = (tip - tail) * 0.28
                        normal = np.array([-v[1], v[0]]) * 0.5
                        for end in [tip - v + normal, tip - v - normal]:
                            item = self.scene().addLine(
                                float(end[0]), float(-end[1]), float(tip[0]), float(-tip[1]), pen
                            )
                            item.setToolTip(f"Düzlem içi asal gerilme {stress:.8g} kPa")
                    self.principal_count += 1
            self.overlay_note += " · düzlem içi asal: mavi basınç / kırmızı çekme"
            if stride > 1:
                self.overlay_note += f" (her {stride}. GP)"

    def show_query_line(self, endpoints):
        if getattr(self, "query_item", None) is not None:
            try:
                self.scene().removeItem(self.query_item)
            except RuntimeError:
                pass
        a, b = endpoints
        pen = QPen(QColor("#111827"), 2, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        self.query_item = self.scene().addLine(a[0], -a[1], b[0], -b[1], pen)

    def fit_model(self):
        box = self.scene().itemsBoundingRect()
        if not box.isEmpty():
            margin = 0.05 * max(box.width(), box.height())
            self.setSceneRect(box.adjusted(-margin, -margin, margin, margin))
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def mouseMoveEvent(self, event):
        p = self.mapToScene(event.position().toPoint())
        self.mouse_world.emit(float(p.x()), float(-p.y()))
        super().mouseMoveEvent(event)

    def wheelEvent(self, event):
        self.scale(
            1.2 if event.angleDelta().y() > 0 else 1 / 1.2,
            1.2 if event.angleDelta().y() > 0 else 1 / 1.2,
        )

    def mouseDoubleClickEvent(self, event):
        if self.model is not None:
            point = self.mapToScene(event.position().toPoint())
            xy = np.array([point.x(), -point.y()])
            coords = self.model.mesh.coords
            valid = (
                np.ones(len(coords), bool)
                if self.stage is None
                else np.isfinite(self.stage.u).all(axis=1)
            )
            ids = np.flatnonzero(valid)
            if ids.size:
                node = ids[np.argmin(np.linalg.norm(self.display_coords[ids] - xy, axis=1))]
                msg = f"Düğüm {node} · x={coords[node, 0]:.6g} m, y={coords[node, 1]:.6g} m"
                if self.stage is not None:
                    msg += f" · ux={self.stage.u[node, 0]:.8g}, uy={self.stage.u[node, 1]:.8g} m"
                self.queried.emit(msg)
        super().mouseDoubleClickEvent(event)


class ConvergencePlot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.values = []
        self.setMinimumHeight(135)

    def reset(self):
        self.values.clear()
        self.update()

    def add_progress(self, progress):
        if progress.residual is not None and not progress.accepted:
            self.values.append(float(progress.residual))
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#fff"))
        p.setPen(QColor("#526677"))
        p.drawText(12, 20, "Yakınsama · log₁₀ bağıl kuvvet kalıntısı")
        box = QRectF(55, 32, max(self.width() - 75, 1), max(self.height() - 55, 1))
        p.drawRect(box)
        if not self.values:
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, "Çözüm bekleniyor")
            return
        v = np.log10(np.clip(self.values, 1e-16, 1e16))
        lo, hi = min(float(np.nanmin(v)), -3.0), max(float(np.nanmax(v)), 0.0)
        path = QPainterPath()
        for i, value in enumerate(v):
            x = box.left() + i / max(len(v) - 1, 1) * box.width()
            y = box.bottom() - (value - lo) / max(hi - lo, 1) * box.height()
            path.moveTo(x, y) if i == 0 else path.lineTo(x, y)
        p.setPen(QPen(QColor("#0e7490"), 2))
        p.drawPath(path)
        p.drawText(4, int(box.top()) + 5, f"{hi:.0f}")
        p.drawText(4, int(box.bottom()), f"{lo:.0f}")

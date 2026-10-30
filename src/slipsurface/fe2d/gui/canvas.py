"""Native QGraphicsView mesh/result canvas."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsView

from ..core.enums import ElemType
from ..post.recovery import principal_stresses
from .editing import (
    region_label,
    stage_active_regions,
    stage_active_structures,
    stage_region_material,
    structure_label,
)

_ORDERS = {
    ElemType.T3: [0, 1, 2],
    ElemType.T6: [0, 3, 1, 4, 2, 5],
    ElemType.Q4: [0, 1, 2, 3],
    ElemType.Q8: [0, 4, 1, 5, 2, 6, 3, 7],
}


class MeshCanvas(QGraphicsView):
    queried = Signal(str)
    mouse_world = Signal(float, float)
    region_clicked = Signal(int)
    structure_clicked = Signal(str)
    context_menu_requested = Signal(int, str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        # Keep the mesh centred while docks/panels resize the view.
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._auto_fit = False
        self.setBackgroundBrush(QColor("#f5f8fa"))
        self.model = self.stage = None
        self.stage_index = 0
        self.cell_count = 0
        self.legend = "Geometri · m"
        self.struct_labels = False
        self.force_overlay = None  # (result, stage, component_key) or None
        self.node_labels = False
        self.show_legend_bar = False
        self._press_pos = None

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
        stage_index=0,
        struct_labels=False,
        force_overlay=None,
        node_labels=False,
        show_legend_bar=False,
    ):
        changed_model = self.model is not model
        self.model, self.stage, self.stage_index = model, stage, stage_index
        self.struct_labels = struct_labels
        self.force_overlay = force_overlay
        self.node_labels = node_labels
        self.show_legend_bar = show_legend_bar
        self.scene().clear()
        self.cell_count = 0
        self.principal_count = self.plastic_count = 0
        self.overlay_note = ""
        mesh = model.mesh
        coords = mesh.coords.copy()
        if stage is not None:
            coords += deform * np.nan_to_num(stage.u)
        self.display_coords = coords
        active_regs = stage_active_regions(model, stage_index)
        active_structs = stage_active_structures(model, stage_index)
        cells, values = [], []
        excavated_cells = []
        region_centers: dict[int, list[np.ndarray]] = {}
        for block in mesh.continuum_blocks():
            if stage is None:
                active = np.isin(block.region, list(active_regs))
            else:
                active = stage.active.get(block.tag, np.ones(block.ne, bool))
            for e in range(block.ne):
                conn = block.conn[e]
                order = _ORDERS[block.etype]
                reg_id = int(block.region[e])
                if not active[e]:
                    # Passive (e.g. excavated) cells keep their undeformed shape: their
                    # nodes are NaN in stage.u, so deforming them would collapse/fold them.
                    xy = mesh.coords[conn[order]]
                    excavated_cells.append((block, e, reg_id, xy))
                    region_centers.setdefault(reg_id, []).append(xy.mean(axis=0))
                    continue
                xy = coords[conn[order]]
                region_centers.setdefault(reg_id, []).append(xy.mean(axis=0))
                if stage is None:
                    value = float(reg_id)
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
                cells.append((block, e, reg_id, xy))
                values.append(float(value))
        finite = np.asarray(values)[np.isfinite(values)]
        lo, hi = (float(finite.min()), float(finite.max())) if finite.size else (0.0, 0.0)
        span = hi - lo
        constant = span <= 1e-10 * max(abs(lo), abs(hi), 1.0)
        self.field_range = (lo, hi)
        self.constant_field = constant
        ghost_pen = QPen(QColor("#94a3b8"), 0, Qt.PenStyle.DashLine)
        ghost_brush = QColor(226, 232, 240, 60)
        for _block, _e, reg_id, xy in excavated_cells:
            poly = QPolygonF([QPointF(float(x), float(-y)) for x, y in xy])
            item = self.scene().addPolygon(poly, ghost_pen, ghost_brush)
            item.setData(0, ("region", reg_id))
            item.setToolTip(
                f"{region_label(model, reg_id)} · Kazıldı (boş) — sağ tık veya araçla geri doldurun"
            )
        pen = QPen(QColor("#42657b"), 0)
        region_colors = ("#c5dfe8", "#dfd4b8", "#cbdcc4", "#d7cce5", "#f2d0c4", "#bfe3dc")
        for (block, e, reg_id, xy), value in zip(cells, values):
            t = (value - lo) / (hi - lo) if not constant and np.isfinite(value) else 0.5
            if stage is None:
                color = QColor(region_colors[(reg_id - 1) % len(region_colors)])
            else:
                color = QColor.fromHsvF(0.62 * (1 - np.clip(t, 0, 1)), 0.65, 0.9)
            poly = QPolygonF([QPointF(float(x), float(-y)) for x, y in xy])
            item = self.scene().addPolygon(poly, pen, color)
            item.setData(0, ("region", reg_id))
            if stage is None:
                mat = stage_region_material(model, stage_index, reg_id) or "Kazıldı"
                item.setToolTip(f"{region_label(model, reg_id)} · Malzeme: {mat} · Eleman {e}")
            else:
                item.setToolTip(f"{block.tag} · {e} · {field}: {value:.8g}")
            self.cell_count += 1
        if stage is None:
            for reg_id, pts in sorted(region_centers.items()):
                center = np.mean(pts, axis=0)
                mat = stage_region_material(model, stage_index, reg_id)
                r_lbl = region_label(model, reg_id)
                badge = self.scene().addSimpleText(
                    f"⛏ KAZILDI · {r_lbl}" if mat is None else f"{r_lbl} · {mat}"
                )
                badge.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
                badge.setPos(float(center[0]), float(-center[1]))
                badge.setBrush(QColor("#b42331" if mat is None else "#123f5b"))
                badge.setZValue(3)
        for block in mesh.blocks:
            if block.etype not in (ElemType.BEAM2, ElemType.BAR2):
                continue
            if stage is None:
                is_active = block.tag in active_structs
                p = QPen(
                    QColor(
                        ("#e57326" if block.etype is ElemType.BEAM2 else "#166534")
                        if is_active
                        else "#94a3b8"
                    ),
                    2.6 if is_active else 1.5,
                    Qt.PenStyle.SolidLine if is_active else Qt.PenStyle.DashLine,
                )
                p.setCosmetic(True)
                s_lbl = structure_label(model, block.tag)
                state_txt = "Aktif" if is_active else "Pasif (tıklayarak etkinleştirin)"
                for conn in block.conn:
                    a, b = coords[conn]
                    line_item = self.scene().addLine(a[0], -a[1], b[0], -b[1], p)
                    line_item.setZValue(2.5 if is_active else 1.8)
                    line_item.setData(0, ("structure", block.tag))
                    line_item.setToolTip(f"{s_lbl} · {state_txt}")
            else:
                active = stage.active.get(block.tag, np.ones(block.ne, bool))
                p = QPen(QColor("#e57326" if block.etype is ElemType.BEAM2 else "#166534"), 2)
                p.setCosmetic(True)
                for conn in block.conn[active]:
                    a, b = coords[conn]
                    line_item = self.scene().addLine(a[0], -a[1], b[0], -b[1], p)
                    line_item.setZValue(2.5)
                    line_item.setData(0, ("structure", block.tag))
        if stage is not None and self.struct_labels:
            self.draw_structure_labels(coords, stage)
        if stage is not None and self.force_overlay is not None and result is not None:
            self.draw_force_overlay(result, stage, coords)
        if stage is not None and self.node_labels:
            self.draw_node_labels(coords, stage, field)
        if stage is not None and self.show_legend_bar and field in ("|u|", "ux", "uy"):
            self.draw_color_legend(coords, stage, field)
        unit = "m" if field in ("|u|", "ux", "uy") else "oran" if field == "plastic" else "kPa"
        if stage is None:
            st_name = (
                "Başlangıç"
                if stage_index <= 0 or not model.stages
                else model.stages[min(stage_index - 1, len(model.stages) - 1)].name
            )
            exc_count = len(mesh.regions() - active_regs)
            self.legend = (
                f"Aşama önizleme: {st_name} · "
                f"{len(active_regs)}/{len(mesh.regions())} bölge aktif"
                + (f" ({exc_count} kazıldı)" if exc_count else "")
                + f" · {len(active_structs)}/{len(model.structure_tags())} destek aktif"
                + " · Bölgeye/desteğe tıklayarak veya sağ tıkla düzenleyin"
            )
        else:
            self.legend = (
                f"{field} · {unit} · eleman ortalaması · {lo:.5g} … {hi:.5g}"
                f" · deformasyon ×{deform:g}"
            )
        if stage is not None and result is not None:
            self.draw_overlays(result, stage, coords, principal, plastic_points)
            self.legend += self.overlay_note
        if changed_model:
            self.fit_model()

    def draw_force_overlay(self, result, stage, coords):
        """Draw the selected section-force component of every active structure on the model.

        ``self.force_overlay`` is ``(component_index,)``; component 0 = N, 1 = V, 2 = M
        for beams, 0 = N for bars. Amplitude is scaled to 12 % of the model extent.
        """
        from .result_tools import structure_segments

        comp = self.force_overlay[0]
        mesh = self.model.mesh
        extent = max(float(np.ptp(coords, axis=0).max()), 1e-9)
        peak = 1e-30
        segments = []
        for tag in self.model.structure_tags():
            try:
                kind, segs = structure_segments(result, stage, tag)
            except Exception:
                continue
            for a, b, _s, f in segs:
                f = np.asarray(f, float)
                if f.ndim != 2 or f.shape[1] <= comp:
                    continue
                peak = max(peak, float(np.nanmax(np.abs(f[:, comp]))))
                segments.append((a, b, f[:, comp]))
        if not segments:
            return
        amplitude = 0.12 * extent / peak
        pen = QPen(QColor("#8a1c2c"), 1.4)
        pen.setCosmetic(True)
        for a, b, vals in segments:
            a, b = np.asarray(a, float), np.asarray(b, float)
            t = (b - a) / max(float(np.linalg.norm(b - a)), 1e-30)
            normal = np.array([-t[1], t[0]])
            fa, fb = vals[0], vals[1]
            poly = QPolygonF(
                [
                    QPointF(float(a[0]), float(-a[1])),
                    QPointF(float(a[0] + amplitude * fa * normal[0]),
                            float(-(a[1] + amplitude * fa * normal[1]))),
                    QPointF(float(b[0] + amplitude * fb * normal[0]),
                            float(-(b[1] + amplitude * fb * normal[1]))),
                    QPointF(float(b[0]), float(-b[1])),
                ]
            )
            fill = QColor("#d9485f" if fa + fb > 0 else "#2f6fd6")
            fill.setAlpha(90)
            item = self.scene().addPolygon(poly, pen, fill)
            item.setData(0, ("structure", ""))
            item.setZValue(3.5)

    def draw_node_labels(self, coords, stage, field):
        """Write the nodal value of the current field at used nodes (deformed position)."""
        font = QFont()
        font.setPointSize(7)
        if field in ("|u|", "ux", "uy"):
            v = stage.u
            vals = (
                np.linalg.norm(v, axis=1)
                if field == "|u|"
                else v[:, 0 if field == "ux" else 1]
            )
            fmt, unit = "{:.4g}", "m"
        elif field == "plastic":
            return  # plastic fraction is a cell field, not nodal
        else:
            from ..post.recovery import nodal_average

            from ..post.result_fields import active_mesh, active_values

            mesh = self.model.mesh
            view = active_mesh(mesh, stage)
            sig = active_values(mesh, stage, stage.sig)
            nodal = nodal_average(view, sig)
            if field in ("sxx", "syy", "szz", "txy"):
                vals = nodal[:, ("sxx", "syy", "szz", "txy").index(field)]
            elif field in ("pore", "excess_pore"):
                data = getattr(stage, field)
                merged = {}
                for tag, arr in data.items():
                    merged[tag] = arr[..., None] if arr.ndim == 2 else arr
                vals = nodal_average(view, active_values(mesh, stage, merged))[:, 0]
            else:
                from ..post.recovery import principal_stresses

                vals = principal_stresses(nodal)[field]
            fmt, unit = "{:.4g}", "kPa"
        used = np.isfinite(vals)
        stride = max(1, int(np.ceil(int(used.sum()) / 400)))  # keep the view readable
        for n in np.flatnonzero(used)[::stride]:
            item = self.scene().addSimpleText(fmt.format(float(vals[n])) + " " + unit, font)
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            item.setPos(float(coords[n, 0]), float(-coords[n, 1]))
            item.setBrush(QColor("#0f172a"))
            item.setZValue(4.5)

    def draw_color_legend(self, coords, stage, field):
        """Vertical colour bar for the displacement field, drawn in scene coordinates."""
        finite = np.asarray(
            [
                (np.linalg.norm(stage.u[conn], axis=1).mean() if field == "|u|"
                 else stage.u[conn][:, 0 if field == "ux" else 1].mean())
                for block in self.model.mesh.continuum_blocks()
                for e, conn in enumerate(block.conn)
                if stage.active.get(block.tag, np.ones(block.ne, bool))[e]
            ]
        )
        finite = finite[np.isfinite(finite)]
        if not finite.size:
            return
        lo, hi = float(finite.min()), float(finite.max())
        span = hi - lo if hi - lo > 1e-12 * max(abs(lo), abs(hi), 1.0) else max(abs(hi), 1.0)
        lo, hi = lo - 0.05 * span, hi + 0.05 * span
        x0, y0 = float(coords[:, 0].min()), float(coords[:, 1].min())
        x1, y1 = float(coords[:, 0].max()), float(coords[:, 1].max())
        w = 0.02 * (x1 - x0) + 0.15
        h = 0.25 * (y1 - y0) + 0.5
        bx, by = x1 + 0.03 * (x1 - x0) + 0.3, y1 - h
        steps = 24
        font = QFont()
        font.setPointSize(7)
        for i in range(steps):
            t0, t1 = i / steps, (i + 1) / steps
            t = 0.5 * (t0 + t1)
            color = QColor.fromHsvF(0.62 * (1 - min(max(t, 0.0), 1.0)), 0.65, 0.9)
            rect = QRectF(bx, -(by + h * t1), w, h / steps + 0.02)
            self.scene().addRect(rect, QPen(QColor("#42657b"), 0), color)
        for i in range(5):
            t = i / 4
            value = lo + (hi - lo) * t
            item = self.scene().addSimpleText(f"{value:.4g} m", font)
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            item.setPos(bx + w + 0.1, -(by + h * (1 - t)))
            item.setBrush(QColor("#213547"))
            item.setZValue(5)
        title = self.scene().addSimpleText(f"{field} (m)", font)
        title.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        title.setPos(bx, -(by + h + 0.25))
        title.setBrush(QColor("#213547"))
        title.setZValue(5)

    def draw_structure_labels(self, coords, stage):
        """N (and M/V for beams) at each active structure element's midpoint."""
        mesh = self.model.mesh
        font = QFont()
        font.setPointSize(8)
        for block in mesh.blocks:
            if block.etype not in (ElemType.BEAM2, ElemType.BAR2):
                continue
            active = stage.active.get(block.tag, np.ones(block.ne, bool))
            forces = stage.beams.get(block.tag) if block.etype is ElemType.BEAM2 else stage.bars.get(block.tag)
            if forces is None:
                continue
            for e in np.flatnonzero(active):
                a, b = coords[block.conn[e]]
                mid = 0.5 * (a + b)
                if block.etype is ElemType.BEAM2:
                    f = np.nanmean(forces[e], axis=0)
                    text = f"N={f[0]:.4g} kN/m\nV={f[1]:.4g} kN/m\nM={f[2]:.4g} kNm/m"
                else:
                    text = f"N={float(np.nanmean(forces[e])):.4g} kN"
                item = self.scene().addSimpleText(text, font)
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
                item.setPos(float(mid[0]), float(-mid[1]))
                item.setBrush(QColor("#173b52"))
                item.setZValue(4)

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
        # Stay fitted through layout changes (stale size of a hidden page, docks, panels)
        # until the user zooms or pans.
        self._auto_fit = True
        if self.isVisible() and self.viewport().width() > 1:
            self._apply_fit()

    def _apply_fit(self):
        # Fit the mesh nodes, not itemsBoundingRect(): transform-ignoring labels would count
        # their pixel size as metres and shrink/shift the mesh off-centre.
        coords = getattr(self, "display_coords", None)
        if coords is None or not len(coords):
            return
        finite = coords[np.isfinite(coords).all(axis=1)]
        if not len(finite):
            return
        (x0, y0), (x1, y1) = finite.min(axis=0), finite.max(axis=0)
        box = QRectF(float(x0), float(-y1), float(x1 - x0), float(y1 - y0))
        if box.width() > 0 or box.height() > 0:
            margin = 0.05 * max(box.width(), box.height())
            view = box.adjusted(-margin, -margin, margin, margin)
            room = max(box.width(), box.height()) * 20
            self.setSceneRect(box.adjusted(-room, -room, room, room))
            self.fitInView(view, Qt.AspectRatioMode.KeepAspectRatio)
            self.centerOn(view.center())

    def showEvent(self, event):
        super().showEvent(event)
        if self._auto_fit:
            QTimer.singleShot(0, lambda: self._auto_fit and self._apply_fit())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._auto_fit and self.isVisible():
            self._apply_fit()

    def hit_test(self, viewport_pos) -> tuple[int, str]:
        """Return ``(region_id, structure_tag)`` at ``viewport_pos`` (0 / '' if none)."""
        if self.model is None:
            return 0, ""
        rect = self.viewport().rect().adjusted(-6, -6, 6, 6)
        from PySide6.QtCore import QRect

        pick_rect = QRect(viewport_pos.x() - 6, viewport_pos.y() - 6, 12, 12)
        items = self.items(pick_rect) if rect.contains(viewport_pos) else []
        region_id = 0
        struct_tag = ""
        for item in items:
            data = item.data(0)
            if isinstance(data, tuple) and len(data) == 2:
                kind, val = data
                if kind == "structure" and not struct_tag:
                    struct_tag = str(val)
                elif kind == "region" and not region_id:
                    region_id = int(val)
        return region_id, struct_tag

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and self._press_pos is not None:
            pos = event.position().toPoint()
            if (pos - self._press_pos).manhattanLength() > 5:
                self._auto_fit = False  # the user panned
            else:
                reg, struct = self.hit_test(pos)
                if struct:
                    self.structure_clicked.emit(struct)
                elif reg:
                    self.region_clicked.emit(reg)
            self._press_pos = None

    def contextMenuEvent(self, event):
        if self.model is not None:
            reg, struct = self.hit_test(event.pos())
            self.context_menu_requested.emit(reg, struct, event.globalPos())
            event.accept()
            return
        super().contextMenuEvent(event)

    def mouseMoveEvent(self, event):
        p = self.mapToScene(event.position().toPoint())
        self.mouse_world.emit(float(p.x()), float(-p.y()))
        super().mouseMoveEvent(event)

    def wheelEvent(self, event):
        self._auto_fit = False
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

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


DISPLACEMENT_FIELDS = ("|u|", "ux", "uy")
SECTION_FIELDS = {"N": 0, "V": 1, "M": 2}


def field_color(t):
    return QColor.fromHsvF(0.62 * (1 - float(np.clip(t, 0, 1))), 0.65, 0.9)


def field_unit(field):
    if field in DISPLACEMENT_FIELDS:
        return "m"
    if field == "plastic":
        return "oran"
    if field == "M":
        return "kNm/m"
    if field in SECTION_FIELDS:
        return "kN/m"
    return "kPa"


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
        self.nvm_count = self.disp_label_count = 0
        self.colorbar_visible = False
        self.field_name = "|u|"
        self.field_unit = "m"
        self.field_range = (0.0, 0.0)
        self.constant_field = True
        self.legend = "Geometri · m"
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
    ):
        changed_model = self.model is not model
        self.model, self.stage, self.stage_index = model, stage, stage_index
        self.field_name = field
        self.scene().clear()
        self.cell_count = 0
        self.principal_count = self.plastic_count = 0
        self.nvm_count = self.disp_label_count = 0
        section = field in SECTION_FIELDS
        self.colorbar_visible = stage is not None and not section
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
                if stage is None or field in SECTION_FIELDS:
                    value = float(reg_id)
                elif field in DISPLACEMENT_FIELDS:
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
        if section:
            pen = QPen(Qt.PenStyle.NoPen)  # N-V-M view: mesh edges off, filled diagrams only
        region_colors = ("#c5dfe8", "#dfd4b8", "#cbdcc4", "#d7cce5", "#f2d0c4", "#bfe3dc")
        for (block, e, reg_id, xy), value in zip(cells, values):
            t = (value - lo) / (hi - lo) if not constant and np.isfinite(value) else 0.5
            if stage is None or field in SECTION_FIELDS:
                color = QColor(region_colors[(reg_id - 1) % len(region_colors)])
            else:
                color = field_color(t)
            poly = QPolygonF([QPointF(float(x), float(-y)) for x, y in xy])
            item = self.scene().addPolygon(poly, pen, color)
            item.setData(0, ("region", reg_id))
            if stage is None or field in SECTION_FIELDS:
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
                s_lbl = structure_label(model, block.tag)
                for conn in block.conn[active]:
                    a, b = coords[conn]
                    if field in DISPLACEMENT_FIELDS:
                        v = stage.u[conn]
                        value = (
                            np.linalg.norm(v, axis=1).mean()
                            if field == "|u|"
                            else v[:, 0 if field == "ux" else 1].mean()
                        )
                        t = (
                            (value - lo) / (hi - lo)
                            if not constant and np.isfinite(value)
                            else 0.5
                        )
                        p = QPen(field_color(t), 3.2)
                    else:
                        p = QPen(
                            QColor("#e57326" if block.etype is ElemType.BEAM2 else "#166534"),
                            2.6,
                        )
                    p.setCosmetic(True)
                    line_item = self.scene().addLine(a[0], -a[1], b[0], -b[1], p)
                    line_item.setZValue(2.5)
                    line_item.setData(0, ("structure", block.tag))
                    ua, ub = stage.u[conn]
                    line_item.setToolTip(
                        f"{s_lbl} · |u|={np.linalg.norm(ua):.4g} … {np.linalg.norm(ub):.4g} m"
                    )
        unit = field_unit(field)
        self.field_unit = unit
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
        elif field in SECTION_FIELDS:
            self.legend = (
                f"{field} · {unit} · kaplama / kazık / ankraj · deformasyon ×{deform:g}"
            )
        else:
            self.legend = (
                f"{field} · {unit} · eleman ortalaması · {lo:.5g} … {hi:.5g}"
                f" · deformasyon ×{deform:g}"
            )
        if stage is not None and result is not None:
            if field not in SECTION_FIELDS:
                self.draw_overlays(result, stage, coords, principal, plastic_points)
            self.draw_structure_results(result, stage, coords, field)
            self.legend += self.overlay_note
        if changed_model:
            self.fit_model()
        self.viewport().update()

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

    @staticmethod
    def _seg_normal(mapped, seg_idx):
        a, b = np.asarray(mapped[seg_idx][0], float), np.asarray(mapped[seg_idx][1], float)
        t = (b - a) / max(float(np.linalg.norm(b - a)), 1e-30)
        return np.array([-t[1], t[0]])

    def draw_structure_results(self, result, stage, coords, field):
        """N–V–M as an offset polyline on the member. Displacement stays a heatmap."""
        show_nvm = field in SECTION_FIELDS
        component = SECTION_FIELDS.get(field, 0)
        if not show_nvm:
            return
        from .result_tools import (
            FORCE_COMPONENTS,
            diagram_amplitude,
            force_diagram_line,
            structure_segments,
        )

        mesh = result.model.mesh
        X0 = mesh.coords
        finite = coords[np.isfinite(coords).all(1)]
        extent = max(float(np.ptp(finite, axis=0).max()) if len(finite) else 1.0, 1e-9)
        offset = 0.02 * extent
        notes = []
        for block in mesh.blocks:
            if block.etype not in (ElemType.BEAM2, ElemType.BAR2):
                continue
            try:
                kind, segments = structure_segments(result, stage, block.tag)
            except Exception:
                continue
            if not segments:
                continue
            if kind == "bar" and field != "N":
                continue
            mapped, normals = [], {}
            for a, b, station, f in segments:
                ia = int(np.argmin(np.sum((X0 - a) ** 2, axis=1)))
                ib = int(np.argmin(np.sum((X0 - b) ** 2, axis=1)))
                pa, pb = coords[ia], coords[ib]
                mapped.append((pa, pb, station, f))
                tangent = (pb - pa) / max(float(np.linalg.norm(pb - pa)), 1e-30)
                normal = np.array([-tangent[1], tangent[0]])
                normals.setdefault(ia, []).append(normal)
                normals.setdefault(ib, []).append(normal)
            comp = 0 if kind == "bar" else max(0, min(int(component), 2))
            key, title, unit = FORCE_COMPONENTS[kind][comp]
            s_lbl = structure_label(result.model, block.tag)
            amplitude = diagram_amplitude(mapped, comp, extent, fraction=0.08)
            line = force_diagram_line(mapped, comp, amplitude)
            pen = QPen(QColor("#156798"), 0)
            pen.setCosmetic(True)
            # Filled, unbroken diagram band: close each element's offset pair back
            # along the member itself, so the whole structure reads as one ribbon.
            fill_pen = QPen(Qt.PenStyle.NoPen)
            for seg_idx in range(0, len(line) - 1, 2):
                (p0, v0), (p1, v1) = line[seg_idx], line[seg_idx + 1]
                normal = self._seg_normal(mapped, seg_idx // 2)
                base_a = p0 - amplitude * v0 * normal
                base_b = p1 - amplitude * v1 * normal
                sign = 1.0 if (v0 + v1) >= 0 else -1.0
                fill = QColor("#d9485f" if sign > 0 else "#2f6fd6")
                fill.setAlpha(110)
                poly = QPolygonF(
                    [
                        QPointF(float(base_a[0]), float(-base_a[1])),
                        QPointF(float(p0[0]), float(-p0[1])),
                        QPointF(float(p1[0]), float(-p1[1])),
                        QPointF(float(base_b[0]), float(-base_b[1])),
                    ]
                )
                item = self.scene().addPolygon(poly, fill_pen, fill)
                item.setZValue(2.1)
                item.setData(0, ("structure", block.tag))
                item.setToolTip(f"{s_lbl} · {title} {unit}")
            for (xy0, _v0), (xy1, _v1) in zip(line, line[1:]):
                item = self.scene().addLine(
                    float(xy0[0]), float(-xy0[1]), float(xy1[0]), float(-xy1[1]), pen
                )
                item.setZValue(2.2)
                item.setData(0, ("structure", block.tag))
                item.setToolTip(f"{s_lbl} · {title} {unit}")
                self.nvm_count += 1
            ext = [
                (float(f[k, comp]), np.asarray(pt if k == 0 else other, float))
                for pt, other, _, f in mapped
                for k in (0, 1)
                if np.isfinite(f[k, comp])
            ]
            if ext:
                (vmin, pmin), (vmax, pmax) = min(ext, key=lambda v: v[0]), max(
                    ext, key=lambda v: v[0]
                )
                for value, where, label in (
                    (vmin, pmin, "min"),
                    (vmax, pmax, "maks"),
                ):
                    node = min(normals, key=lambda n: float(np.linalg.norm(coords[n] - where)))
                    mean_n = np.mean(normals[node], axis=0)
                    mean_n = mean_n / max(float(np.linalg.norm(mean_n)), 1e-30)
                    self._add_overlay_label(
                        where + offset * mean_n,
                        f"{key} {label} {value:.3g} {unit}",
                        "#8a1c2c",
                    )
            notes.append(f"{s_lbl} {key}")
        if notes:
            self.overlay_note += " · " + ", ".join(notes)

    def _add_overlay_label(self, xy, text, color):
        item = self.scene().addSimpleText(text)
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        font = QFont("Source Sans 3", 8)
        item.setFont(font)
        item.setPos(float(xy[0]), float(-xy[1]))
        item.setBrush(QColor(color))
        item.setZValue(4)
        return item

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.colorbar_visible:
            return
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._paint_colorbar(painter)
        painter.end()

    def _paint_colorbar(self, painter):
        lo, hi = self.field_range
        vp = self.viewport().rect()
        bar_h = min(220, max(120, int(vp.height() * 0.42)))
        bar_w = 16
        x = vp.width() - bar_w - 64
        y = 18
        panel = QRectF(x - 10, y - 14, bar_w + 68, bar_h + 42)
        painter.setPen(QPen(QColor("#94a3b8"), 1))
        painter.setBrush(QColor(255, 255, 255, 230))
        painter.drawRoundedRect(panel, 4, 4)
        title = f"{self.field_name} · {self.field_unit}"
        painter.setPen(QColor("#123f5b"))
        painter.setFont(QFont("Source Sans 3", 8, QFont.Bold))
        painter.drawText(QRectF(x - 6, y - 12, bar_w + 60, 14), Qt.AlignmentFlag.AlignLeft, title)
        for i in range(bar_h):
            t = 1.0 - i / max(bar_h - 1, 1)
            painter.setPen(field_color(0.5 if self.constant_field else t))
            painter.drawLine(x, y + 6 + i, x + bar_w, y + 6 + i)
        painter.setPen(QPen(QColor("#42657b"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(x, y + 6, bar_w, bar_h)
        painter.setPen(QColor("#123f5b"))
        painter.setFont(QFont("Source Sans 3", 8))
        ticks = (
            [(0.5, lo)]
            if self.constant_field
            else [(0.0, hi), (0.5, 0.5 * (lo + hi)), (1.0, lo)]
        )
        for frac, value in ticks:
            yy = y + 6 + frac * bar_h
            painter.drawText(
                QRectF(x + bar_w + 4, yy - 7, 44, 14),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"{value:.3g}",
            )

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
            pad = 0.12 if self.nvm_count or self.disp_label_count else 0.05
            margin = pad * max(box.width(), box.height())
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

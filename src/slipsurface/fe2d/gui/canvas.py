"""Native QGraphicsView mesh/result canvas."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsView

from ..core.enums import ElemType
from ..post.contact_results import CONTACT_FIELDS, contact_points
from ..post.recovery import element_nodal_values, principal_stresses
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


def _block_nodal(stage, block, field):
    """(ne, nen) scalar at the element nodes. Jumps between elements are kept."""
    if field in DISPLACEMENT_FIELDS:
        u = stage.u[block.conn]
        if field == "|u|":
            return np.linalg.norm(u, axis=2)
        return u[:, :, 0 if field == "ux" else 1]
    if field == "plastic":
        gp = stage.plastic.get(block.tag)
        if gp is None:
            return None
        # Flags are categories (elastic/shear/tension/apex), not scalar nodal data.
        # Keep the fraction of yielding Gauss points constant within each element.
        fraction = (gp > 0).mean(axis=1)
        return np.broadcast_to(fraction[:, None], (block.ne, block.etype.nen))
    if field in ("pore", "excess_pore"):
        data = getattr(stage, field).get(block.tag)
        if data is None:
            return None
        raw = data[..., None] if data.ndim == 2 else data
        return element_nodal_values(block, raw)[..., 0]
    sig = stage.sig.get(block.tag)
    if sig is None:
        return None
    nodal = element_nodal_values(block, sig)
    if field in ("sxx", "syy", "szz", "txy"):
        return nodal[..., ("sxx", "syy", "szz", "txy").index(field)]
    flat = principal_stresses(nodal.reshape(-1, nodal.shape[-1]))[field]
    return np.asarray(flat).reshape(nodal.shape[:2])


def field_unit(field):
    if field in CONTACT_FIELDS:
        return {"contact_gap": "mm", "contact_pressure": "kPa",
                "contact_status": "category"}[field]
    if field in DISPLACEMENT_FIELDS:
        return "m"
    if field == "plastic":
        return "ratio"
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
        self.diagram_tags = []
        self.contact_point_count = 0
        self.contact_points = ()
        self.colorbar_visible = False
        self.field_name = "|u|"
        self.field_unit = "m"
        self.selection = None
        self.diagram_scale = 1.0
        self.field_range = (0.0, 0.0)
        self.constant_field = True
        self.legend = "Geometry · m"
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
        selection=None,
        diagram_scale=1.0,
    ):
        changed_model = self.model is not model
        changed_selection = self.selection != selection
        self.selection, self.diagram_scale = selection, diagram_scale
        self.model, self.stage, self.stage_index = model, stage, stage_index
        self.field_name = field
        self.scene().clear()
        self.cell_count = 0
        self.diagram_tags = []
        self.contact_point_count = 0
        self.contact_points = ()
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
        self.focus_coords = None
        if selection is not None:
            kind, selected = selection
            blocks = mesh.continuum_blocks() if kind == "region" else [mesh.block(selected)]
            nodes = [
                b.conn[b.region == selected].ravel() if kind == "region" else b.conn.ravel()
                for b in blocks
            ]
            if nodes and any(len(n) for n in nodes):
                self.focus_coords = coords[np.unique(np.concatenate(nodes))]
        active_regs = stage_active_regions(model, stage_index)
        active_structs = stage_active_structures(model, stage_index)
        cells = []
        samples = []
        excavated_cells = []
        region_centers: dict[int, list[np.ndarray]] = {}
        for block in mesh.continuum_blocks():
            if stage is None:
                active = np.isin(block.region, list(active_regs))
            else:
                active = stage.active.get(block.tag, np.ones(block.ne, bool))
            nodal = (
                None
                if stage is None or field in SECTION_FIELDS or field in CONTACT_FIELDS
                else _block_nodal(stage, block, field)
            )
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
                target = selection is None or selection == ("region", reg_id)
                outline = None if nodal is None or not target else nodal[e][order]
                if outline is not None:
                    samples.extend(float(v) for v in outline if np.isfinite(v))
                cells.append((block, e, reg_id, xy, outline))
        if selection is not None and selection[0] == "structure" and stage is not None:
            if field in DISPLACEMENT_FIELDS:
                u = stage.u[np.unique(mesh.block(selection[1]).conn)]
                values = (
                    np.linalg.norm(u, axis=1) if field == "|u|" else u[:, 0 if field == "ux" else 1]
                )
                samples = values[np.isfinite(values)].tolist()
        finite = np.asarray(samples, float)
        lo, hi = (float(finite.min()), float(finite.max())) if finite.size else (0.0, 0.0)
        span = hi - lo
        constant = span <= 1e-10 * max(abs(lo), abs(hi), 1.0)
        self.field_range = (lo, hi)
        self.constant_field = constant
        ghost_pen = QPen(QColor("#94a3b8"), 0, Qt.PenStyle.DashLine)
        if section or (selection is not None and selection[0] == "structure"):
            ghost_pen = QPen(Qt.PenStyle.NoPen)
        ghost_brush = QColor(226, 232, 240, 60)
        for _block, _e, reg_id, xy in excavated_cells:
            poly = QPolygonF([QPointF(float(x), float(-y)) for x, y in xy])
            item = self.scene().addPolygon(poly, ghost_pen, ghost_brush)
            item.setData(0, ("region", reg_id))
            item.setToolTip(
                f"{region_label(model, reg_id)} · Excavated (void) — "
                "right-click or use a tool to restore"
            )
        pen = QPen(QColor("#42657b"), 0)
        if section:
            pen = QPen(Qt.PenStyle.NoPen)  # N-V-M view: mesh edges off, filled diagrams only
        region_colors = ("#c5dfe8", "#dfd4b8", "#cbdcc4", "#d7cce5", "#f2d0c4", "#bfe3dc")
        material_colors = {
            name: region_colors[i % len(region_colors)] for i, name in enumerate(model.materials)
        }
        for block, e, reg_id, xy, outline in cells:
            context = selection is not None and selection != ("region", reg_id)
            if outline is None:
                value = float(reg_id)
                tip_mat = stage_region_material(model, stage_index, reg_id) or "Excavated"
                color = QColor(material_colors.get(tip_mat, "#ffffff"))
                tip = f"{region_label(model, reg_id)} · Material: {tip_mat} · Element {e}"
            else:
                finite_n = outline[np.isfinite(outline)]
                value = float(np.mean(finite_n)) if finite_n.size else np.nan
                t = (value - lo) / (hi - lo) if not constant and np.isfinite(value) else 0.5
                color = field_color(t)
                lo_e = float(np.min(finite_n)) if finite_n.size else np.nan
                hi_e = float(np.max(finite_n)) if finite_n.size else np.nan
                tip = f"{block.tag} · {e} · {field}: {lo_e:.6g} … {hi_e:.6g}"
            poly = QPolygonF([QPointF(float(x), float(-y)) for x, y in xy])
            item = self.scene().addPolygon(
                poly,
                QPen(Qt.PenStyle.NoPen) if context else pen,
                QColor("#edf1f4") if context else color,
            )
            item.setData(0, ("region", reg_id))
            item.setToolTip(tip)
            self.cell_count += 1
        if stage is None:
            for reg_id, pts in sorted(region_centers.items()):
                if selection is not None and selection != ("region", reg_id):
                    continue
                center = np.mean(pts, axis=0)
                mat = stage_region_material(model, stage_index, reg_id)
                r_lbl = region_label(model, reg_id)
                badge = self.scene().addSimpleText(
                    f"⛏ EXCAVATED · {r_lbl}" if mat is None else f"{r_lbl} · {mat}"
                )
                badge.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
                badge.setPos(float(center[0]), float(-center[1]))
                badge.setBrush(QColor("#b42331" if mat is None else "#123f5b"))
                badge.setZValue(3)
        for block in mesh.blocks:
            if block.etype in (ElemType.IFACE4, ElemType.IFACE6) and selection == (
                "structure",
                block.tag,
            ):
                half = block.conn.shape[1] // 2
                active = (
                    stage.active.get(block.tag, np.ones(block.ne, bool))
                    if stage is not None
                    else np.ones(block.ne, bool)
                )
                for conn in block.conn[active]:
                    for pair in (conn[:2], conn[half : half + 2]):
                        a, b = coords[pair]
                        if not np.isfinite([a, b]).all():
                            continue
                        color = QColor("#8455b6")
                        if stage is not None and field in DISPLACEMENT_FIELDS:
                            u = stage.u[pair]
                            value = (
                                np.linalg.norm(u, axis=1).mean()
                                if field == "|u|"
                                else u[:, 0 if field == "ux" else 1].mean()
                            )
                            color = field_color((value - lo) / span if not constant else 0.5)
                        line = self.scene().addLine(a[0], -a[1], b[0], -b[1], QPen(color, 0))
                        line.setData(0, ("structure", block.tag))
                        line.setZValue(2.5)
            if block.etype not in (ElemType.BEAM2, ElemType.BAR2):
                continue
            context = selection is not None and selection != ("structure", block.tag)
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
                if context:
                    p.setColor(QColor("#b7c2cc"))
                    p.setWidthF(1.0)
                s_lbl = structure_label(model, block.tag)
                state_txt = "Active" if is_active else "Inactive (click to activate)"
                for conn in block.conn:
                    a, b = coords[conn]
                    line_item = self.scene().addLine(a[0], -a[1], b[0], -b[1], p)
                    line_item.setZValue(2.5 if is_active else 1.8)
                    line_item.setData(0, ("structure", block.tag))
                    line_item.setToolTip(f"{s_lbl} · {state_txt}")
            else:
                active = stage.active.get(block.tag, np.ones(block.ne, bool))
                s_lbl = structure_label(model, block.tag)
                if block.etype is ElemType.BAR2 or selection == ("structure", block.tag):
                    pen = QPen(QColor("#64748b"), 1.8, Qt.PenStyle.DashLine)
                    pen.setCosmetic(True)
                    for conn in block.conn[~active]:
                        a, b = mesh.coords[conn]
                        item = self.scene().addLine(a[0], -a[1], b[0], -b[1], pen)
                        item.setData(0, ("structure", block.tag))
                        item.setToolTip(f"{s_lbl} · Inactive in this stage")
                        item.setZValue(2.5)
                for conn in block.conn[active]:
                    a, b = coords[conn]
                    if field in DISPLACEMENT_FIELDS and block.etype is not ElemType.BAR2:
                        v = stage.u[conn]
                        value = (
                            np.linalg.norm(v, axis=1).mean()
                            if field == "|u|"
                            else v[:, 0 if field == "ux" else 1].mean()
                        )
                        t = (value - lo) / (hi - lo) if not constant and np.isfinite(value) else 0.5
                        p = QPen(field_color(t), 3.2)
                    else:
                        p = QPen(
                            QColor("#e57326" if block.etype is ElemType.BEAM2 else "#166534"),
                            2.6,
                        )
                    p.setCosmetic(True)
                    if context:
                        p.setColor(QColor("#b7c2cc"))
                        p.setWidthF(1.0)
                    line_item = self.scene().addLine(a[0], -a[1], b[0], -b[1], p)
                    line_item.setZValue(5 if block.etype is ElemType.BAR2 else 2.5)
                    line_item.setData(0, ("structure", block.tag))
                    ua, ub = stage.u[conn]
                    line_item.setToolTip(
                        f"{s_lbl} · |u|={np.linalg.norm(ua):.4g} … {np.linalg.norm(ub):.4g} m"
                    )
        unit = field_unit(field)
        if (
            selection is not None
            and selection[0] == "structure"
            and field == "N"
            and model.structure_tags().get(selection[1]) == "bar"
        ):
            unit = "kN"
        self.field_unit = unit
        if stage is None:
            st_name = (
                "Initial"
                if stage_index <= 0 or not model.stages
                else model.stages[min(stage_index - 1, len(model.stages) - 1)].name
            )
            exc_count = len(mesh.regions() - active_regs)
            self.legend = (
                f"Stage preview: {st_name} · "
                f"{len(active_regs)}/{len(mesh.regions())} regions active"
                + (f" ({exc_count} excavated)" if exc_count else "")
                + f" · {len(active_structs)}/{len(model.structure_tags())} supports active"
                + " · Click a region/support or right-click to edit"
            )
        elif field in SECTION_FIELDS:
            self.legend = f"{field} · {unit} · lining / pile / anchor · deformation ×{deform:g}"
        else:
            sampling = "yielding Gauss-point fraction" if field == "plastic" else "nodal"
            self.legend = (
                f"{field} · {unit} · {sampling} · {lo:.5g} … {hi:.5g} · deformation ×{deform:g}"
            )
        if stage is not None and result is not None:
            if field not in SECTION_FIELDS and field not in CONTACT_FIELDS:
                self.draw_overlays(result, stage, coords, principal, plastic_points)
            self.draw_structure_results(result, stage, coords, field)
            self.legend += self.overlay_note
            if field in CONTACT_FIELDS:
                self.draw_contact_results(result, stage, coords, field, deform)
        if changed_model or changed_selection:
            self.fit_model()
        self.viewport().update()

    def draw_overlays(self, result, stage, coords, principal, plastic):
        if not principal and not plastic:
            return
        extent = max(float(np.ptp(coords, axis=0).max()), 1e-9)
        records = []
        for block in result.model.mesh.continuum_blocks():
            active = stage.active.get(block.tag, np.ones(block.ne, bool))
            if self.selection is not None and self.selection[0] == "region":
                active = active & (block.region == self.selection[1])
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
                item.setToolTip(f"Plastic Gauss point · flag {int(flag)}")
                self.plastic_count += 1
            self.overlay_note += f" · plastic GP {self.plastic_count}/{len(selected)}"
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
                            item.setToolTip(f"In-plane principal stress {stress:.8g} kPa")
                    self.principal_count += 1
            self.overlay_note += " · in-plane principals: blue compression / red tension"
            if stride > 1:
                self.overlay_note += f" (every {stride}th GP)"

    def draw_contact_results(self, result, stage, coords, field, deform):
        """Point markers only: categorical states are never interpolated/averaged."""
        tag = (self.selection[1] if self.selection and self.selection[0] == "structure"
               else None)
        self.colorbar_visible = False
        try:
            points = contact_points(result, stage, tag)
        except (ValueError, KeyError, TypeError) as exc:
            self.legend = f"Contact data rejected: {exc}"
            return
        self.contact_points = points
        values = [p.display_value(field) for p in points if p.availability == "available"]
        lo, hi = (min(values), max(values)) if values else (0.0, 0.0)
        self.field_range = (lo, hi)
        self.constant_field = hi == lo
        self.colorbar_visible = bool(values) and field != "contact_status"
        colors = {"OPEN": "#3b82f6", "TOUCHING": "#eab308", "COMPRESSED": "#e05a47",
                  "INACTIVE": "#64748b", "UNAVAILABLE": "#a855f7"}
        for point in points:
            value = point.display_value(field)
            color = (QColor(colors[point.status]) if field == "contact_status" or value is None
                     else field_color((value - lo) / (hi - lo) if hi != lo else 0.5))
            pen = QPen(color, 1.5)
            pen.setCosmetic(True)
            brush = QBrush(color) if value is not None else QBrush(Qt.BrushStyle.NoBrush)
            item = self.scene().addEllipse(-4, -4, 8, 8, pen, brush)
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            nodes = [point.face1_node, point.face2_node]
            # Position markers on the displayed pair midpoint; values remain stored gap.
            xy = (coords[nodes].mean(axis=0) if point.active else
                  result.model.mesh.coords[nodes].mean(axis=0))
            item.setPos(float(xy[0]), float(-xy[1]))
            item.setZValue(8)
            item.setData(0, ("structure", point.tag))
            item.setData(1, (point.tag, point.element, point.point))
            measurement = (f"gap={point.gap_m * 1000:.8g} mm; "
                           f"pressure={point.pressure_kpa:.8g} kPa"
                           if point.availability == "available" else "No measurement")
            item.setToolTip(f"{point.tag} · element {point.element}, point {point.point} · "
                            f"{point.status} · {measurement}")
            self.contact_point_count += 1
        counts = {key: sum(p.status == key for p in points) for key in colors}
        detail = " · ".join(f"{key}={count}" for key, count in counts.items() if count)
        interval = (f"{lo:.6g} … {hi:.6g} {field_unit(field)} · "
                    if values and field != "contact_status" else "")
        self.legend = (f"{field} · stored interface points · {interval}{detail} · "
                       f"deformation ×{deform:g} (display only)")
        if not values:
            self.legend += " · No active available contact measurements"
        if field == "contact_status":
            self.legend += (" · blue: OPEN; yellow: TOUCHING; red: COMPRESSED; "
                            "grey: INACTIVE; purple: UNAVAILABLE")
        elif field == "contact_gap":
            self.legend += " · positive opening / negative penalty penetration"
        else:
            self.legend += " · compression-positive pressure"

    def draw_structure_results(self, result, stage, coords, field):
        """Draw each connected member separately, scaled to its own dimensions."""
        if field not in SECTION_FIELDS:
            return
        from .result_tools import (
            FORCE_COMPONENTS,
            diagram_amplitude,
            force_diagram_line,
            structure_chains,
            structure_segments,
        )

        notes = []
        self.diagram_tags = []
        self.contact_point_count = 0
        self.contact_points = ()
        for block in result.model.mesh.blocks:
            if block.etype not in (ElemType.BEAM2, ElemType.BAR2):
                continue
            if self.selection is not None and self.selection != ("structure", block.tag):
                continue
            kind, segments = structure_segments(result, stage, block.tag)
            if kind == "bar" and field != "N":
                continue
            comp = 0 if kind == "bar" else SECTION_FIELDS[field]
            mapped = [
                replace(seg, a=coords[seg.nodes[0]], b=coords[seg.nodes[1]])
                for seg in segments
                if np.isfinite(coords[list(seg.nodes)]).all()
                and np.isfinite(seg.forces[:, comp]).all()
            ]
            if not mapped:
                continue
            self.diagram_tags.append(block.tag)
            points = np.array([p for seg in mapped for p in (seg.a, seg.b)])
            extent = max(float(np.ptp(points, axis=0).max()), 1e-9)
            amplitude = diagram_amplitude(mapped, comp, extent, fraction=0.10) * self.diagram_scale
            key, title, unit = FORCE_COMPONENTS[kind][comp]
            label = structure_label(result.model, block.tag)
            pen = QPen(QColor("#156798"), 0)
            pen.setCosmetic(True)
            drawn_points = []
            for chain in structure_chains(mapped):
                line = force_diagram_line(chain, comp, amplitude)
                drawn_points.extend(xy for xy, _ in line)
                for i, seg in enumerate(chain):
                    (p0, v0), (p1, v1) = line[2 * i : 2 * i + 2]
                    bands = [(seg.a, p0, p1, seg.b, v0 + v1)]
                    if v0 * v1 < 0:
                        t = abs(v0) / (abs(v0) + abs(v1))
                        zero = seg.a + t * (seg.b - seg.a)
                        bands = [(seg.a, p0, zero, zero, v0), (zero, zero, p1, seg.b, v1)]
                    for a, pa, pb, b, sign in bands:
                        fill = QColor("#d9485f" if sign >= 0 else "#2f6fd6")
                        fill.setAlpha(105)
                        poly = QPolygonF(
                            [QPointF(float(p[0]), float(-p[1])) for p in (a, pa, pb, b)]
                        )
                        item = self.scene().addPolygon(poly, QPen(Qt.PenStyle.NoPen), fill)
                        item.setZValue(2.1)
                        item.setData(0, ("structure", block.tag))
                        item.setToolTip(f"{label} · {key}: {v0:.4g} → {v1:.4g} {unit}")
                # Never bridge disconnected chains, inactive gaps or branches.
                for (p0, v0), (p1, v1) in zip(line, line[1:]):
                    item = self.scene().addLine(
                        float(p0[0]), float(-p0[1]), float(p1[0]), float(-p1[1]), pen
                    )
                    item.setZValue(2.2)
                    item.setData(0, ("structure", block.tag))
                    item.setToolTip(f"{label} · {title}: {v0:.4g} → {v1:.4g} {unit}")
                    self.nvm_count += 1
            values = np.array([seg.forces[:, comp] for seg in mapped])
            notes.append(f"{label}: min {values.min():.4g}, max {values.max():.4g} {unit}")
            if self.selection == ("structure", block.tag):
                self.focus_coords = np.vstack((points, drawn_points))
        if notes:
            self.overlay_note += " · " + "; ".join(notes)
        elif self.selection is not None:
            self.overlay_note += " · No active section-force result in this stage"

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
        title = {"contact_gap": "Gap · mm", "contact_pressure": "p · kPa"}.get(
            self.field_name, f"{self.field_name} · {self.field_unit}")
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
            [(0.5, lo)] if self.constant_field else [(0.0, hi), (0.5, 0.5 * (lo + hi)), (1.0, lo)]
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
        pts = np.asarray(endpoints, float)
        if pts.ndim != 2 or pts.shape[1] != 2 or len(pts) < 2:
            return
        pen = QPen(QColor("#111827"), 2, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        path = QPainterPath()
        started = False
        for point in pts:
            if not np.isfinite(point).all():
                started = False
                continue
            if started:
                path.lineTo(float(point[0]), float(-point[1]))
            else:
                path.moveTo(float(point[0]), float(-point[1]))
                started = True
        self.query_item = self.scene().addPath(path, pen)

    def fit_model(self):
        # Stay fitted through layout changes (stale size of a hidden page, docks, panels)
        # until the user zooms or pans.
        self._auto_fit = True
        if self.isVisible() and self.viewport().width() > 1:
            self._apply_fit()

    def _apply_fit(self):
        # Fit the mesh nodes, not itemsBoundingRect(): transform-ignoring labels would count
        # their pixel size as metres and shrink/shift the mesh off-centre.
        coords = getattr(self, "focus_coords", None)
        if coords is None:
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
                msg = f"Node {node} · x={coords[node, 0]:.6g} m, y={coords[node, 1]:.6g} m"
                if self.stage is not None:
                    msg += f" · ux={self.stage.u[node, 0]:.8g}, uy={self.stage.u[node, 1]:.8g} m"
                self.queried.emit(msg)
        super().mouseDoubleClickEvent(event)

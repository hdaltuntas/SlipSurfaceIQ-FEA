"""NATM tunnel designer, shotcrete/steel-set lining designer and bolt-pattern dialogs.

Sections and linings are kept in a user library (QSettings, shared by all projects), so a
section drawn once can be placed again in later projects.
"""

from __future__ import annotations

import json

import numpy as np
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..cad.tunnel import (
    PART_LABELS,
    STEEL_RIBS,
    WIRE_MESH,
    BlastDisturbance,
    BoltPattern,
    LiningSystem,
    SteelSet,
    TunnelDesign,
    TunnelSection,
    _lining_chains,
    _part_bolt_heads,
    _rounded,
)


# --------------------------------------------------------------------------- library
def library(kind):
    """``{name: dict}`` saved under ``kind`` ("tunnels" or "linings")."""
    from .preferences import settings

    try:
        data = json.loads(settings().value(f"library/{kind}", "{}") or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def library_store(kind, name, data):
    from .preferences import settings

    items = library(kind)
    items[name] = data
    settings().setValue(f"library/{kind}", json.dumps(items, ensure_ascii=False))


def library_remove(kind, name):
    from .preferences import settings

    items = library(kind)
    items.pop(name, None)
    settings().setValue(f"library/{kind}", json.dumps(items, ensure_ascii=False))


class LibraryBar(QWidget):
    """Combo + load / save / delete for one library kind."""

    def __init__(self, kind, getter, setter, parent=None):
        super().__init__(parent)
        self.kind, self.getter, self.setter = kind, getter, setter
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("Library"))
        self.combo = QComboBox()
        self.combo.setMinimumWidth(180)
        row.addWidget(self.combo, 1)
        for title, slot in [("Load", self.load), ("Save…", self.save), ("Delete", self.remove)]:
            button = QPushButton(title)
            button.setAutoDefault(False)
            button.clicked.connect(slot)
            row.addWidget(button)
        self.refresh()

    def refresh(self, select=None):
        self.combo.clear()
        self.combo.addItems(sorted(library(self.kind)))
        if select:
            self.combo.setCurrentText(select)

    def load(self):
        data = library(self.kind).get(self.combo.currentText())
        if data is not None:
            self.setter(data)

    def save(self):
        data = self.getter()
        if data is None:
            return
        name, ok = QInputDialog.getText(
            self, "Save to library", "Name:", text=data.get("name") or self.combo.currentText()
        )
        if ok and name.strip():
            library_store(self.kind, name.strip(), data)
            self.refresh(name.strip())

    def remove(self):
        if self.combo.currentText():
            library_remove(self.kind, self.combo.currentText())
            self.refresh()


def _spin(value, lo, hi, decimals=3, suffix=""):
    w = QDoubleSpinBox()
    w.setDecimals(decimals)
    w.setRange(lo, hi)
    w.setValue(value)
    if suffix:
        w.setSuffix(f" {suffix}")
    return w


def _catalog_label(name: str) -> str:
    """UI name for a lining catalogue entry. Legacy Yok/Özel display as None/Custom."""
    return {"Yok": "None", "Özel": "Custom"}.get(name, name)


def _catalog_key(label: str) -> str:
    """Catalogue key. Legacy Yok/Özel files are read as None/Custom; new files stay English."""
    return {"Yok": "None", "Özel": "Custom"}.get(label, label)


def _is_custom_rib(name: str) -> bool:
    return name in {"Custom", "Özel"}


_PART_EN = {
    "heading": "Top heading",
    "bench": "Bench",
    "invert": "Invert",
    "full": "Full face",
}


# --------------------------------------------------------------------------- lining
class LiningDesignerDialog(QDialog):
    """Shotcrete + wire mesh + steel sets → one equivalent liner per metre of tunnel."""

    def __init__(self, lining=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Shotcrete / wire mesh / steel-set design")
        lining = lining or LiningSystem()
        layout = QVBoxLayout(self)
        self.library_bar = LibraryBar("linings", self._data, self._load)
        layout.addWidget(self.library_bar)
        form = QFormLayout()
        self.thickness = _spin(lining.thickness * 100, 1, 200, 1, "cm")
        self.E = _spin(lining.E_shotcrete / 1e6, 0.1, 100, 2, "GPa")
        self.E.setToolTip("Enter 28-day reference modulus (100%).")
        self.capacity = _spin(lining.initial_capacity_percent, 1, 100, 1, "%")
        self.fc28 = _spin(lining.fc28 / 1000, 0.01, 200, 2, "MPa")
        self.ft28 = _spin(lining.ft28 / 1000, 0.01, 30, 2, "MPa")
        self.capacity.setToolTip(
            "First active stage: percentage of shotcrete 28-day reference values. "
            "The next construction stage uses 100%; steel mesh and steel ribs stay unchanged."
        )
        self.nu = _spin(lining.nu, 0, 0.49, 3)
        self.gamma = _spin(lining.unit_weight, 0, 100, 2, "kN/m³")
        self.mesh = QComboBox()
        self.mesh.addItems([_catalog_label(name) for name in WIRE_MESH])
        self.mesh.setCurrentText(_catalog_label(lining.mesh))
        self.layers = QSpinBox()
        self.layers.setRange(1, 2)
        self.layers.setValue(lining.mesh_layers)
        self.cover = _spin(lining.cover * 100, 0, 50, 1, "cm")
        self.rib = QComboBox()
        self.rib.addItems([*(_catalog_label(name) for name in STEEL_RIBS), "Custom"])
        self.rib.setCurrentText(_catalog_label(lining.rib))
        self.rib_area = _spin(lining.rib_area, 0, 1e4, 2, "cm²")
        self.rib_inertia = _spin(lining.rib_inertia, 0, 1e7, 1, "cm⁴")
        self.rib_spacing = _spin(lining.rib_spacing, 0.1, 10, 2, "m")
        self.Es = _spin(lining.E_steel / 1e6, 1, 300, 1, "GPa")
        concrete = QGroupBox("Shotcrete")
        f = QFormLayout(concrete)
        f.addRow("Thickness", self.thickness)
        f.addRow("28-day E", self.E)
        f.addRow("28-day compression strength", self.fc28)
        f.addRow("28-day tensile strength", self.ft28)
        f.addRow("First active stage / 28-day (%)", self.capacity)
        f.addRow("ν", self.nu)
        f.addRow("γ", self.gamma)
        mesh = QGroupBox("Wire mesh")
        f = QFormLayout(mesh)
        f.addRow("Type", self.mesh)
        f.addRow("Layers", self.layers)
        f.addRow("Cover", self.cover)
        rib = QGroupBox("Steel set")
        f = QFormLayout(rib)
        f.addRow("Profile", self.rib)
        f.addRow("A (custom)", self.rib_area)
        f.addRow("I (custom)", self.rib_inertia)
        f.addRow("Spacing (tunnel axis)", self.rib_spacing)
        f.addRow("Steel E", self.Es)
        self.name = QComboBox()
        self.name.setEditable(True)
        self.name.setCurrentText(lining.name)
        form.addRow("Name", self.name)
        layout.addLayout(form)
        groups = QHBoxLayout()
        for group in (concrete, mesh, rib):
            groups.addWidget(group)
        layout.addLayout(groups)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("padding:6px;background:#eef4f8;color:#173b52")
        layout.addWidget(self.summary)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for w in (self.thickness, self.E, self.nu, self.gamma, self.cover, self.rib_area,
                  self.rib_inertia, self.rib_spacing, self.Es, self.capacity,
                  self.fc28, self.ft28):  # fmt: skip
            w.valueChanged.connect(self.update_summary)
        for w in (self.mesh, self.rib):
            w.currentTextChanged.connect(self.update_summary)
        self.layers.valueChanged.connect(self.update_summary)
        self.update_summary()

    def lining(self):
        return LiningSystem(
            name=self.name.currentText().strip() or "Lining",
            thickness=self.thickness.value() / 100,
            E_shotcrete=self.E.value() * 1e6,
            initial_capacity_percent=self.capacity.value(),
            fc28=self.fc28.value() * 1000,
            ft28=self.ft28.value() * 1000,
            nu=self.nu.value(),
            unit_weight=self.gamma.value(),
            mesh=_catalog_key(self.mesh.currentText()),
            mesh_layers=self.layers.value(),
            cover=self.cover.value() / 100,
            rib=_catalog_key(self.rib.currentText()),
            rib_area=self.rib_area.value(),
            rib_inertia=self.rib_inertia.value(),
            rib_spacing=self.rib_spacing.value(),
            E_steel=self.Es.value() * 1e6,
        )

    def _data(self):
        try:
            return self.lining().to_dict()
        except ValueError as exc:
            self.summary.setText(str(exc))
            return None

    def _load(self, data):
        lining = LiningSystem(**data)
        self.name.setCurrentText(lining.name)
        self.thickness.setValue(lining.thickness * 100)
        self.E.setValue(lining.E_shotcrete / 1e6)
        self.capacity.setValue(lining.initial_capacity_percent)
        self.fc28.setValue(lining.fc28 / 1000)
        self.ft28.setValue(lining.ft28 / 1000)
        self.nu.setValue(lining.nu)
        self.gamma.setValue(lining.unit_weight)
        self.mesh.setCurrentText(_catalog_label(lining.mesh))
        self.layers.setValue(lining.mesh_layers)
        self.cover.setValue(lining.cover * 100)
        self.rib.setCurrentText(_catalog_label(lining.rib))
        self.rib_area.setValue(lining.rib_area)
        self.rib_inertia.setValue(lining.rib_inertia)
        self.rib_spacing.setValue(lining.rib_spacing)
        self.Es.setValue(lining.E_steel / 1e6)

    def update_summary(self, *_):
        custom = _is_custom_rib(self.rib.currentText())
        self.rib_area.setEnabled(custom)
        self.rib_inertia.setEnabled(custom)
        try:
            lining = self.lining()
        except ValueError as exc:
            self.summary.setText(str(exc))
            return
        EA, EI = lining.stiffness()
        early_ea, early_ei = lining.stiffness_at_capacity(lining.initial_capacity_percent)
        fc, ft = lining.strengths_at_capacity(lining.initial_capacity_percent)
        p = lining.liner_properties()
        d_eq = np.sqrt(12 * p["I"] / p["A"])
        self.summary.setText(
            f"At 28d: EA = {EA:,.0f} kN/m · EI = {EI:,.1f} kNm²/m\n"
            f"First installed stage ({lining.initial_capacity_percent:g}% shotcrete): "
            f"EA = {early_ea:,.0f} kN/m · EI = {early_ei:,.1f} kNm²/m\n"
            f"Concrete reference strengths: fc={fc / 1000:.2f} MPa, "
            f"ft={ft / 1000:.2f} MPa (next stage: 100%; not an elastic-beam failure check)\n"
            f"Beam: E = {p['E'] / 1e6:.2f} GPa · A = {p['A']:.4f} m²/m · I = {p['I']:.3e} m⁴/m"
            f" · equivalent thickness d = {d_eq * 100:.1f} cm"
        )


# --------------------------------------------------------------------------- tunnel
class SectionPreview(QWidget):
    COLORS = {"heading": "#e2b878", "bench": "#82c39b", "invert": "#b39ddb", "full": "#65b4c8"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.design = None
        self.error = ""
        self.setMinimumSize(360, 320)

    def set_design(self, design, error=""):
        self.design, self.error = design, error
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#f7fafc"))
        if self.design is None:
            p.setPen(QColor("#a32d26"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.error or "Invalid section")
            return
        design, section = self.design, self.design.section
        parts = section.parts_at((0.0, 0.0))
        ring = _rounded(section.outline())
        bolt_len = max(
            (pat.length for pat in (design.bolts, design.bench_bolts, design.invert_bolts) if pat),
            default=0.0,
        )
        halo = design.disturbance.thickness if design.disturbance else 0.0
        lo, hi = section.bounds_y()
        reach = section.radius + max(bolt_len, halo)
        span = max(2 * reach, hi - lo + 2 * max(bolt_len, halo)) * 1.1
        scale = min(self.width(), self.height() - 30) / span
        origin = QPointF(self.width() / 2, (self.height() - 30) / 2 + 10)

        def at(xy):
            return QPointF(origin.x() + xy[0] * scale, origin.y() - xy[1] * scale)

        cuts = [section.heading_level, section.invert_level][: section.parts - 1]
        if design.disturbance is not None:
            p.setPen(QPen(QColor("#c47b2b"), 1, Qt.PenStyle.DashLine))
            p.setBrush(QColor(196, 123, 43, 40))
            from shapely.geometry import Polygon

            outer = Polygon(ring).buffer(design.disturbance.thickness)
            p.drawPolygon(QPolygonF([at(xy) for xy in outer.exterior.coords]))
        for key, pts in parts.items():
            color = QColor(self.COLORS[key])
            color.setAlpha(150)
            p.setPen(QPen(QColor("#4c6a7d"), 1))
            p.setBrush(color)
            p.drawPolygon(QPolygonF([at(xy) for xy in pts]))
            c = np.mean(pts, axis=0)
            p.setPen(QColor("#173b52"))
            p.drawText(at(c) + QPointF(-30, 4), PART_LABELS[key])
            if design.liner_properties() is not None:
                width = 5 if design.steel is not None else 3
                p.setPen(QPen(QColor("#8a3b16" if design.steel else "#b56324"), width))
                for chain in _lining_chains(pts, cuts):
                    for a, b in zip(chain[:-1], chain[1:]):
                        p.drawLine(at(a), at(b))
            pattern = design.pattern_for(key)
            if pattern is not None:
                p.setPen(QPen(QColor("#218764"), 2))
                for head, direction in _part_bolt_heads(
                    pattern, pts, cuts, (0.0, 0.0), ring, section.radius
                ):
                    p.drawLine(at(head), at(head + direction * pattern.length))
        p.setPen(QColor("#526677"))
        p.drawText(
            8,
            self.height() - 10,
            f"Width {np.ptp(ring[:, 0]):.2f} m · Height {np.ptp(ring[:, 1]):.2f} m · "
            f"Area {_area(ring):.1f} m² · Centre: crown-arc centre (springline)",
        )


def _area(ring):
    x, y = ring[:, 0], ring[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


class TunnelDesignerDialog(QDialog):
    """Section and lining design. Bolts and stages are assigned in the model workspace."""

    PLACE_CLICK, PLACE_COORDS = 1, 2

    def __init__(self, design=None, center=(0.0, 0.0), parent=None):
        super().__init__(parent)
        self.setWindowTitle("Equivalent-section tunnel")
        self.resize(900, 640)
        design = design or TunnelDesign()
        self.lining_value = design.lining or LiningSystem()
        self.placement = 0
        root = QVBoxLayout(self)
        note = QLabel(
            "Shotcrete, wire mesh and steel sets are smeared into one Timoshenko beam. "
            "The check is beam theory and the closed form of pile skin friction. "
            "Add bolts in the model with Support > Bolt pattern: "
            "drag the required boundary interval."
        )
        note.setWordWrap(True)
        root.addWidget(note)
        self.library_bar = LibraryBar("tunnels", self._data, self._load)
        root.addWidget(self.library_bar)
        body = QHBoxLayout()
        root.addLayout(body, 1)
        tabs = QTabWidget()
        body.addWidget(tabs, 0)
        self.preview = SectionPreview()
        body.addWidget(self.preview, 1)

        # Section
        sec = design.section
        page = QWidget()
        f = QFormLayout(page)
        self.name = QComboBox()
        self.name.setEditable(True)
        self.name.setCurrentText(sec.name)
        self.shape = QComboBox()
        self.shape.addItem("NATM (horseshoe)", "natm")
        self.shape.addItem("Circular", "circle")
        self.shape.setCurrentIndex(self.shape.findData(sec.shape))
        self.radius = _spin(sec.radius, 0.5, 50, 3, "m")
        self.wall_radius = _spin(sec.wall_radius, 0.5, 500, 3, "m")
        self.wall_height = _spin(sec.wall_height, 0, 50, 3, "m")
        self.invert_depth = _spin(sec.invert_depth, 0, 50, 3, "m")
        self.parts = QComboBox()
        self.parts.addItem("Full face", 1)
        self.parts.addItem("Top heading + bench", 2)
        self.parts.addItem("Top heading + bench + invert", 3)
        self.parts.setCurrentIndex(self.parts.findData(sec.parts))
        self.heading_level = _spin(sec.heading_level, -50, 50, 3, "m")
        self.invert_level = _spin(sec.invert_level, -50, 50, 3, "m")
        self.segments = QSpinBox()
        self.segments.setRange(12, 400)
        self.segments.setValue(sec.segments)
        for label, w in [
            ("Name", self.name),
            ("Section type", self.shape),
            ("Crown radius R", self.radius),
            ("Side-wall radius", self.wall_radius),
            ("Side-wall height", self.wall_height),
            ("Invert depth", self.invert_depth),
            ("Excavation parts", self.parts),
            ("Top-heading base (from springline)", self.heading_level),
            ("Invert top (from springline)", self.invert_level),
            ("Perimeter segment count", self.segments),
        ]:
            f.addRow(label, w)
        tabs.addTab(page, "Section")

        # Lining
        page = QWidget()
        v = QVBoxLayout(page)
        self.use_lining = QCheckBox("Add a shotcrete lining to every part")
        self.use_lining.setChecked(design.lining is not None)
        v.addWidget(self.use_lining)
        self.lining_label = QLabel()
        self.lining_label.setWordWrap(True)
        v.addWidget(self.lining_label)
        edit = QPushButton("Design shotcrete / wire mesh…")
        edit.setAutoDefault(False)
        edit.clicked.connect(self.edit_lining)
        v.addWidget(edit)
        v.addStretch(1)
        tabs.addTab(page, "Lining")

        # Steel sets
        steel = design.steel
        page = QWidget()
        f = QFormLayout(page)
        self.use_steel = QCheckBox("Add steel sets (spacing along the tunnel axis)")
        self.use_steel.setChecked(steel is not None)
        steel = steel or SteelSet()
        self.rib = QComboBox()
        self.rib.addItems([k for k in STEEL_RIBS if k != "None"] + ["Custom"])
        self.rib.setCurrentText(steel.rib if steel.rib not in {"Yok", "None"} else "HEB 140")
        self.rib_area = _spin(steel.rib_area, 0, 1e4, 2, "cm²")
        self.rib_inertia = _spin(steel.rib_inertia, 0, 1e7, 1, "cm⁴")
        self.rib_spacing = _spin(steel.spacing, 0.1, 10, 2, "m")
        self.rib_E = _spin(steel.E_steel / 1e6, 1, 300, 1, "GPa")
        self.steel_summary = QLabel()
        self.steel_summary.setWordWrap(True)
        f.addRow(self.use_steel)
        f.addRow("Profil", self.rib)
        f.addRow("A (custom)", self.rib_area)
        f.addRow("I (custom)", self.rib_inertia)
        f.addRow("Spacing (tunnel axis)", self.rib_spacing)
        f.addRow("Steel E", self.rib_E)
        f.addRow(self.steel_summary)
        tabs.addTab(page, "Steel sets")

        # Disturbance geometry; construction stages are authored in the main window.
        page = QWidget()
        f = QFormLayout(page)
        self._load_split = design.load_split
        self._separate_support_stage = design.separate_support_stage
        dist = design.disturbance
        self.use_disturbance = QCheckBox("Blast-disturbance zone")
        self.use_disturbance.setChecked(dist is not None)
        dist = dist or BlastDisturbance()
        self.disturb_D = _spin(dist.D, 0.0, 1.0, 2)
        self.disturb_thickness = _spin(dist.thickness, 0.1, 50, 2, "m")
        f.addRow(self.use_disturbance)
        f.addRow("Disturbance factor D", self.disturb_D)
        f.addRow("Zone thickness", self.disturb_thickness)
        note = QLabel(
            "Placing a tunnel adds geometry and inactive supports; it does not add stages. "
            "Define your schedule under Model > Project properties / Stages. After meshing, "
            "create a disturbed rock copy in Materials and assign it to this zone by "
            "right-clicking in the stage you choose."
        )
        note.setWordWrap(True)
        f.addRow(note)
        tabs.addTab(page, "Disturbance")

        # Placement
        place = QHBoxLayout()
        place.addWidget(QLabel("Centre x, y (m)"))
        self.cx = _spin(center[0], -1e6, 1e6, 3)
        self.cy = _spin(center[1], -1e6, 1e6, 3)
        place.addWidget(self.cx)
        place.addWidget(self.cy)
        place.addStretch(1)
        click = QPushButton("Place by clicking the canvas")
        click.clicked.connect(lambda: self._finish(self.PLACE_CLICK))
        coords = QPushButton("Place at coordinates")
        coords.clicked.connect(lambda: self._finish(self.PLACE_COORDS))
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        for b in (click, coords, cancel):
            b.setAutoDefault(False)
            place.addWidget(b)
        root.addLayout(place)

        for w in self.findChildren(QDoubleSpinBox) + self.findChildren(QSpinBox):
            w.valueChanged.connect(self.refresh)
        for w in (self.shape, self.parts, self.rib):
            w.currentIndexChanged.connect(self.refresh)
        for w in (
            self.use_lining,
            self.use_steel,
            self.use_disturbance,
        ):
            w.toggled.connect(self.refresh)
        self.refresh()

    def edit_lining(self):
        dialog = LiningDesignerDialog(self.lining_value, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.lining_value = dialog.lining()
            self.use_lining.setChecked(True)
            self.refresh()

    def section(self):
        return TunnelSection(
            name=self.name.currentText().strip() or "NATM",
            shape=self.shape.currentData(),
            radius=self.radius.value(),
            wall_radius=self.wall_radius.value(),
            wall_height=self.wall_height.value(),
            invert_depth=self.invert_depth.value(),
            heading_level=self.heading_level.value(),
            invert_level=self.invert_level.value(),
            parts=self.parts.currentData(),
            segments=self.segments.value(),
        )

    def steel(self):
        if not self.use_steel.isChecked():
            return None
        return SteelSet(
            rib=self.rib.currentText(),
            spacing=self.rib_spacing.value(),
            rib_area=self.rib_area.value(),
            rib_inertia=self.rib_inertia.value(),
            E_steel=self.rib_E.value() * 1e6,
        )

    def design(self):
        disturbance = None
        if self.use_disturbance.isChecked():
            disturbance = BlastDisturbance(self.disturb_D.value(), self.disturb_thickness.value())
        return TunnelDesign(
            self.section(),
            self.lining_value if self.use_lining.isChecked() else None,
            None,
            self._load_split,
            self._separate_support_stage,
            None,
            None,
            self.steel(),
            disturbance,
        )

    def center(self):
        return self.cx.value(), self.cy.value()

    def refresh(self, *_):
        natm = self.shape.currentData() == "natm"
        for w in (self.wall_radius, self.wall_height, self.invert_depth):
            w.setEnabled(natm)
        parts = self.parts.currentData()
        self.heading_level.setEnabled(parts >= 2)
        self.invert_level.setEnabled(parts == 3)
        custom = self.rib.currentText() == "Custom"
        self.rib_area.setEnabled(self.use_steel.isChecked() and custom)
        self.rib_inertia.setEnabled(self.use_steel.isChecked() and custom)
        for w in (self.rib, self.rib_spacing, self.rib_E, self.steel_summary):
            w.setEnabled(self.use_steel.isChecked())
        self.disturb_D.setEnabled(self.use_disturbance.isChecked())
        self.disturb_thickness.setEnabled(self.use_disturbance.isChecked())
        p = self.lining_value.liner_properties()
        EA, EI = self.lining_value.stiffness()
        self.lining_label.setText(
            f"<b>{self.lining_value.name}</b><br>t = {self.lining_value.thickness * 100:.0f} cm"
            f" · mesh {self.lining_value.mesh}"
            f"<br>EA = {EA:,.0f} kN/m · EI = {EI:,.1f} kNm²/m · A = {p['A']:.4f} m²/m"
        )
        try:
            steel = self.steel()
            if steel is not None:
                props = steel.liner_properties()
                self.steel_summary.setText(
                    f"1 m of tunnel: A = {props['A']:.4f} m²/m · I = {props['I']:.3e} m⁴/m · "
                    f"EA = {props['E'] * props['A']:,.0f} kN/m"
                )
            else:
                self.steel_summary.setText("")
            design = self.design()
            self.preview.set_design(design)
        except ValueError as exc:
            self.preview.set_design(None, str(exc))

    def _finish(self, mode):
        try:
            self.design()
        except ValueError as exc:
            self.preview.set_design(None, str(exc))
            return
        self.placement = mode
        self.accept()

    def _data(self):
        try:
            data = self.design().to_dict()
        except ValueError:
            return None
        data["name"] = self.name.currentText().strip()
        return data

    def _load(self, data):
        design = TunnelDesign.from_dict(data)
        sec = design.section
        self.name.setCurrentText(sec.name)
        self.shape.setCurrentIndex(self.shape.findData(sec.shape))
        self.parts.setCurrentIndex(self.parts.findData(sec.parts))
        for w, value in [
            (self.radius, sec.radius),
            (self.wall_radius, sec.wall_radius),
            (self.wall_height, sec.wall_height),
            (self.invert_depth, sec.invert_depth),
            (self.heading_level, sec.heading_level),
            (self.invert_level, sec.invert_level),
        ]:
            w.setValue(value)
        self.segments.setValue(sec.segments)
        self.use_lining.setChecked(design.lining is not None)
        if design.lining is not None:
            self.lining_value = design.lining
        self.use_steel.setChecked(design.steel is not None)
        steel = design.steel
        if steel is not None:
            self.rib.setCurrentText(steel.rib)
            self.rib_area.setValue(steel.rib_area)
            self.rib_inertia.setValue(steel.rib_inertia)
            self.rib_spacing.setValue(steel.spacing)
            self.rib_E.setValue(steel.E_steel / 1e6)
        self._load_split = design.load_split
        self._separate_support_stage = design.separate_support_stage
        self.use_disturbance.setChecked(design.disturbance is not None)
        if design.disturbance is not None:
            self.disturb_D.setValue(design.disturbance.D)
            self.disturb_thickness.setValue(design.disturbance.thickness)
        self.refresh()

# --------------------------------------------------------------------------- bolts
class BoltPatternDialog(QDialog):
    """Bolt pattern along a selected line: spacing, length, angle to the line and margins."""

    preview_changed = Signal()

    def __init__(self, host, parent=None, chain_length=None, *, closed=False,
                 default_angle=90.0, selected_interval=False):
        super().__init__(parent)
        self.setWindowTitle(f"Bolt pattern · {host}")
        self.chain_length = chain_length
        self.closed = closed
        form = QFormLayout(self)
        default = BoltPattern()
        self.spacing_along = _spin(default.spacing, 0.2, 50, 2, "m")
        self.count = QLabel()
        self.length = _spin(default.length, 0.1, 100, 2, "m")
        self.angle = _spin(default_angle, -180, 180, 1, "°")
        self.angle.setToolTip("Angle counter-clockwise from the line direction (90° = left normal)")
        margin = 0.0 if closed or selected_interval else min(0.5, (chain_length or 2) / 4)
        self.margin = _spin(margin, 0, 1e4, 2, "m")
        self.active = QCheckBox("Activate immediately in all stages")
        self.EA = _spin(default.EA, 1, 1e9, 0, "kN")
        self.T = _spin(default.T_yield, 1, 1e6, 1, "kN")
        self.spacing = _spin(default.spacing_out_of_plane, 0.1, 20, 2, "m")
        self.pre = _spin(0.0, 0, 1e5, 1, "kN")
        for label, w in [
            ("Spacing (along the line / boundary)", self.spacing_along),
            ("Count", self.count),
            ("Length", self.length),
            ("Angle to the line", self.angle),
            ("End margin", self.margin),
            ("EA (tek bulon)", self.EA),
            ("Akma kuvveti", self.T),
            ("Out-of-plane spacing", self.spacing),
            ("Pretension", self.pre),
        ]:
            form.addRow(label, w)
        form.addRow(self.active)
        note = QLabel(
            "Only the highlighted interval receives bolts. Check the preview and set the angle "
            "to choose the side. Spacing is exact; leftover distance is shared at the ends. "
            "Leave activation off to install them in stages you define."
        )
        note.setWordWrap(True)
        form.addRow(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons = buttons
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        for spin in self.findChildren(QDoubleSpinBox):
            spin.valueChanged.connect(lambda _v: self.preview_changed.emit())
        self.spacing_along.valueChanged.connect(self._update_count)
        self.margin.valueChanged.connect(self._update_count)
        self._update_count()

    def _update_count(self, *_):
        from ..cad.tunnel import bolt_stations

        if self.chain_length is None:
            self.count.setText("from spacing")
            return
        try:
            n = len(
                bolt_stations(
                    self.chain_length,
                    self.spacing_along.value(),
                    margin=self.margin.value(),
                    closed=self.closed,
                )
            )
            self.count.setText(f"{n} (from spacing)")
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
        except ValueError as exc:
            self.count.setText(str(exc))
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)

    def pattern(self):
        return BoltPattern(
            0,
            self.length.value(),
            EA=self.EA.value(),
            T_yield=self.T.value(),
            spacing_out_of_plane=self.spacing.value(),
            pretension=self.pre.value(),
            spacing=self.spacing_along.value(),
        )


__all__ = [
    "BoltPatternDialog",
    "LiningDesignerDialog",
    "TunnelDesignerDialog",
    "library",
    "library_remove",
    "library_store",
]

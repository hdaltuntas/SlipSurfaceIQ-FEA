"""NATM tunnel designer, shotcrete/steel-set lining designer and bolt-pattern dialogs.

Sections and linings are kept in a user library (QSettings, shared by all projects), so a
section drawn once can be placed again in later projects.
"""

from __future__ import annotations

import json

import numpy as np
from PySide6.QtCore import QPointF, Qt
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
    BoltPattern,
    LiningSystem,
    TunnelDesign,
    TunnelSection,
    _bolt_heads,
    _lining_chains,
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
        row.addWidget(QLabel("Kütüphane"))
        self.combo = QComboBox()
        self.combo.setMinimumWidth(180)
        row.addWidget(self.combo, 1)
        for title, slot in [("Yükle", self.load), ("Kaydet…", self.save), ("Sil", self.remove)]:
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
            self, "Kütüphaneye kaydet", "Ad:", text=data.get("name") or self.combo.currentText()
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


# --------------------------------------------------------------------------- lining
class LiningDesignerDialog(QDialog):
    """Shotcrete + wire mesh + steel sets → one equivalent liner per metre of tunnel."""

    def __init__(self, lining=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Püskürtme beton / hasır çelik / çelik iksa tasarımı")
        lining = lining or LiningSystem()
        layout = QVBoxLayout(self)
        self.library_bar = LibraryBar("linings", self._data, self._load)
        layout.addWidget(self.library_bar)
        form = QFormLayout()
        self.thickness = _spin(lining.thickness * 100, 1, 200, 1, "cm")
        self.E = _spin(lining.E_shotcrete / 1e6, 0.1, 100, 2, "GPa")
        self.E.setToolTip("Genç püskürtme beton ~5–15 GPa, sertleşmiş ~25–30 GPa")
        self.nu = _spin(lining.nu, 0, 0.49, 3)
        self.gamma = _spin(lining.unit_weight, 0, 100, 2, "kN/m³")
        self.mesh = QComboBox()
        self.mesh.addItems(list(WIRE_MESH))
        self.mesh.setCurrentText(lining.mesh)
        self.layers = QSpinBox()
        self.layers.setRange(1, 2)
        self.layers.setValue(lining.mesh_layers)
        self.cover = _spin(lining.cover * 100, 0, 50, 1, "cm")
        self.rib = QComboBox()
        self.rib.addItems([*STEEL_RIBS, "Özel"])
        self.rib.setCurrentText(lining.rib)
        self.rib_area = _spin(lining.rib_area, 0, 1e4, 2, "cm²")
        self.rib_inertia = _spin(lining.rib_inertia, 0, 1e7, 1, "cm⁴")
        self.rib_spacing = _spin(lining.rib_spacing, 0.1, 10, 2, "m")
        self.Es = _spin(lining.E_steel / 1e6, 1, 300, 1, "GPa")
        concrete = QGroupBox("Püskürtme beton")
        f = QFormLayout(concrete)
        f.addRow("Kalınlık", self.thickness)
        f.addRow("E", self.E)
        f.addRow("ν", self.nu)
        f.addRow("γ", self.gamma)
        mesh = QGroupBox("Hasır çelik")
        f = QFormLayout(mesh)
        f.addRow("Tip", self.mesh)
        f.addRow("Katman", self.layers)
        f.addRow("Pas payı", self.cover)
        rib = QGroupBox("Çelik iksa")
        f = QFormLayout(rib)
        f.addRow("Profil", self.rib)
        f.addRow("A (özel)", self.rib_area)
        f.addRow("I (özel)", self.rib_inertia)
        f.addRow("Aralık (tünel ekseni)", self.rib_spacing)
        f.addRow("Çelik E", self.Es)
        self.name = QComboBox()
        self.name.setEditable(True)
        self.name.setCurrentText(lining.name)
        form.addRow("Ad", self.name)
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
                  self.rib_inertia, self.rib_spacing, self.Es):  # fmt: skip
            w.valueChanged.connect(self.update_summary)
        for w in (self.mesh, self.rib):
            w.currentTextChanged.connect(self.update_summary)
        self.layers.valueChanged.connect(self.update_summary)
        self.update_summary()

    def lining(self):
        return LiningSystem(
            name=self.name.currentText().strip() or "Kaplama",
            thickness=self.thickness.value() / 100,
            E_shotcrete=self.E.value() * 1e6,
            nu=self.nu.value(),
            unit_weight=self.gamma.value(),
            mesh=self.mesh.currentText(),
            mesh_layers=self.layers.value(),
            cover=self.cover.value() / 100,
            rib=self.rib.currentText(),
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
        self.nu.setValue(lining.nu)
        self.gamma.setValue(lining.unit_weight)
        self.mesh.setCurrentText(lining.mesh)
        self.layers.setValue(lining.mesh_layers)
        self.cover.setValue(lining.cover * 100)
        self.rib.setCurrentText(lining.rib)
        self.rib_area.setValue(lining.rib_area)
        self.rib_inertia.setValue(lining.rib_inertia)
        self.rib_spacing.setValue(lining.rib_spacing)
        self.Es.setValue(lining.E_steel / 1e6)

    def update_summary(self, *_):
        custom = self.rib.currentText() == "Özel"
        self.rib_area.setEnabled(custom)
        self.rib_inertia.setEnabled(custom)
        try:
            lining = self.lining()
        except ValueError as exc:
            self.summary.setText(str(exc))
            return
        EA, EI = lining.stiffness()
        p = lining.liner_properties()
        d_eq = np.sqrt(12 * p["I"] / p["A"])
        self.summary.setText(
            f"Eşdeğer kaplama (1 m tünel boyu): EA = {EA:,.0f} kN/m · EI = {EI:,.1f} kNm²/m\n"
            f"Kiriş: E = {p['E'] / 1e6:.2f} GPa · A = {p['A']:.4f} m²/m · I = {p['I']:.3e} m⁴/m"
            f" · eşdeğer kalınlık d = {d_eq * 100:.1f} cm"
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
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.error or "Geçersiz kesit")
            return
        design, section = self.design, self.design.section
        parts = section.parts_at((0.0, 0.0))
        ring = _rounded(section.outline())
        reach = section.radius + (design.bolts.length if design.bolts else 0.0)
        lo, hi = section.bounds_y()
        span = max(2 * reach, hi - lo + 2 * (design.bolts.length if design.bolts else 0)) * 1.1
        scale = min(self.width(), self.height() - 30) / span
        origin = QPointF(self.width() / 2, (self.height() - 30) / 2 + 10)

        def at(xy):
            return QPointF(origin.x() + xy[0] * scale, origin.y() - xy[1] * scale)

        cuts = [section.heading_level, section.invert_level][: section.parts - 1]
        for key, pts in parts.items():
            color = QColor(self.COLORS[key])
            color.setAlpha(150)
            p.setPen(QPen(QColor("#4c6a7d"), 1))
            p.setBrush(color)
            p.drawPolygon(QPolygonF([at(xy) for xy in pts]))
            c = np.mean(pts, axis=0)
            p.setPen(QColor("#173b52"))
            p.drawText(at(c) + QPointF(-30, 4), PART_LABELS[key])
            if design.lining is not None:
                p.setPen(QPen(QColor("#b56324"), 3))
                for chain in _lining_chains(pts, cuts):
                    for a, b in zip(chain[:-1], chain[1:]):
                        p.drawLine(at(a), at(b))
        if design.bolts is not None:
            p.setPen(QPen(QColor("#218764"), 2))
            for head, direction in _bolt_heads(design.bolts, ring, (0.0, 0.0), section.radius):
                p.drawLine(at(head), at(head + direction * design.bolts.length))
        p.setPen(QColor("#526677"))
        p.drawText(
            8,
            self.height() - 10,
            f"Genişlik {np.ptp(ring[:, 0]):.2f} m · Yükseklik {np.ptp(ring[:, 1]):.2f} m · "
            f"Alan {_area(ring):.1f} m² · Merkez: tepe yayı merkezi (üzengi seviyesi)",
        )


def _area(ring):
    x, y = ring[:, 0], ring[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


class TunnelDesignerDialog(QDialog):
    """Separate window: section, lining, bolt pattern and staging of one NATM tunnel."""

    PLACE_CLICK, PLACE_COORDS = 1, 2

    def __init__(self, design=None, center=(0.0, 0.0), parent=None):
        super().__init__(parent)
        self.setWindowTitle("Eşdeğer kesit tünel")
        self.resize(900, 640)
        design = design or TunnelDesign()
        self.lining_value = design.lining or LiningSystem()
        self.placement = 0
        root = QVBoxLayout(self)
        note = QLabel(
            "Püskürtme beton, hasır ve çelik iksa tek Timoshenko kirişine toplanır. "
            "Doğrulama kiriş teorisi ve kazık çevre sürtünmesinin kapalı formudur. "
            "Bu pencere RS2/PLAXIS veya 3B NATM doğrulaması değildir."
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
        self.shape.addItem("NATM (at nalı)", "natm")
        self.shape.addItem("Dairesel", "circle")
        self.shape.setCurrentIndex(self.shape.findData(sec.shape))
        self.radius = _spin(sec.radius, 0.5, 50, 3, "m")
        self.wall_radius = _spin(sec.wall_radius, 0.5, 500, 3, "m")
        self.wall_height = _spin(sec.wall_height, 0, 50, 3, "m")
        self.invert_depth = _spin(sec.invert_depth, 0, 50, 3, "m")
        self.parts = QComboBox()
        self.parts.addItem("Tam kesit", 1)
        self.parts.addItem("Üst yarı + alt yarı", 2)
        self.parts.addItem("Üst yarı + alt yarı + invert", 3)
        self.parts.setCurrentIndex(self.parts.findData(sec.parts))
        self.heading_level = _spin(sec.heading_level, -50, 50, 3, "m")
        self.invert_level = _spin(sec.invert_level, -50, 50, 3, "m")
        self.segments = QSpinBox()
        self.segments.setRange(12, 400)
        self.segments.setValue(sec.segments)
        for label, w in [
            ("Ad", self.name),
            ("Kesit tipi", self.shape),
            ("Tepe yarıçapı R", self.radius),
            ("Yan duvar yarıçapı", self.wall_radius),
            ("Yan duvar yüksekliği", self.wall_height),
            ("İnvert derinliği", self.invert_depth),
            ("Kazı bölümleri", self.parts),
            ("Üst yarı tabanı (üzengiye göre)", self.heading_level),
            ("İnvert üstü (üzengiye göre)", self.invert_level),
            ("Çevre segment sayısı", self.segments),
        ]:
            f.addRow(label, w)
        tabs.addTab(page, "Kesit")

        # Lining
        page = QWidget()
        v = QVBoxLayout(page)
        self.use_lining = QCheckBox("Her bölüme püskürtme beton kaplama ekle")
        self.use_lining.setChecked(design.lining is not None)
        v.addWidget(self.use_lining)
        self.lining_label = QLabel()
        self.lining_label.setWordWrap(True)
        v.addWidget(self.lining_label)
        edit = QPushButton("Püskürtme beton / hasır / çelik iksa tasarla…")
        edit.setAutoDefault(False)
        edit.clicked.connect(self.edit_lining)
        v.addWidget(edit)
        v.addStretch(1)
        tabs.addTab(page, "Kaplama")

        # Bolts
        bolts = design.bolts or BoltPattern()
        page = QWidget()
        f = QFormLayout(page)
        self.use_bolts = QCheckBox("Radyal bulon paterni")
        self.use_bolts.setChecked(design.bolts is not None)
        self.bolt_count = QSpinBox()
        self.bolt_count.setRange(1, 200)
        self.bolt_count.setValue(max(bolts.count, 1))
        self.bolt_length = _spin(bolts.length, 0.1, 50, 2, "m")
        self.bolt_start = _spin(bolts.start_angle, -360, 360, 1, "°")
        self.bolt_end = _spin(bolts.end_angle, -360, 360, 1, "°")
        self.bolt_EA = _spin(bolts.EA, 1, 1e9, 0, "kN")
        self.bolt_T = _spin(bolts.T_yield, 1, 1e6, 1, "kN")
        self.bolt_spacing = _spin(bolts.spacing_out_of_plane, 0.1, 20, 2, "m")
        self.bolt_pre = _spin(bolts.pretension, 0, 1e5, 1, "kN")
        f.addRow(self.use_bolts)
        for label, w in [
            ("Bulon sayısı", self.bolt_count),
            ("Boy", self.bolt_length),
            ("Başlangıç açısı (+x'ten)", self.bolt_start),
            ("Bitiş açısı", self.bolt_end),
            ("EA (tek bulon)", self.bolt_EA),
            ("Akma kuvveti", self.bolt_T),
            ("Tünel ekseni boyunca aralık", self.bolt_spacing),
            ("Öngerme", self.bolt_pre),
        ]:
            f.addRow(label, w)
        tabs.addTab(page, "Bulon")

        # Staging
        page = QWidget()
        f = QFormLayout(page)
        self.load_split = _spin(design.load_split, 0.05, 1.0, 2)
        self.load_split.setToolTip(
            "Destek yerleştirilmeden önce serbest bırakılan kazı yükü oranı (β / ΣMstage). "
            "Kalan kısım destek aşamasında taşınır."
        )
        self.separate = QCheckBox("Her bölüm için ayrı kazı ve püskürtme beton aşaması")
        self.separate.setChecked(design.separate_support_stage)
        f.addRow("Destek öncesi yük oranı", self.load_split)
        f.addRow(self.separate)
        note = QLabel(
            "Aşamalar: üst yarı kazı → üst yarı püskürtme beton (+ bulon) → alt yarı kazı → "
            "alt yarı püskürtme beton → invert kazı → invert kapanışı. Ağ üretilince aşama "
            "yöneticisine eklenir."
        )
        note.setWordWrap(True)
        f.addRow(note)
        tabs.addTab(page, "Aşamalar")

        # Placement
        place = QHBoxLayout()
        place.addWidget(QLabel("Merkez x, y (m)"))
        self.cx = _spin(center[0], -1e6, 1e6, 3)
        self.cy = _spin(center[1], -1e6, 1e6, 3)
        place.addWidget(self.cx)
        place.addWidget(self.cy)
        place.addStretch(1)
        click = QPushButton("Kanvasta tıklayarak yerleştir")
        click.clicked.connect(lambda: self._finish(self.PLACE_CLICK))
        coords = QPushButton("Koordinata yerleştir")
        coords.clicked.connect(lambda: self._finish(self.PLACE_COORDS))
        cancel = QPushButton("İptal")
        cancel.clicked.connect(self.reject)
        for b in (click, coords, cancel):
            b.setAutoDefault(False)
            place.addWidget(b)
        root.addLayout(place)

        for w in self.findChildren(QDoubleSpinBox) + self.findChildren(QSpinBox):
            w.valueChanged.connect(self.refresh)
        for w in (self.shape, self.parts):
            w.currentIndexChanged.connect(self.refresh)
        for w in (self.use_lining, self.use_bolts, self.separate):
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

    def design(self):
        bolts = None
        if self.use_bolts.isChecked():
            bolts = BoltPattern(
                self.bolt_count.value(),
                self.bolt_length.value(),
                self.bolt_start.value(),
                self.bolt_end.value(),
                self.bolt_EA.value(),
                self.bolt_T.value(),
                self.bolt_spacing.value(),
                self.bolt_pre.value(),
            )
        return TunnelDesign(
            self.section(),
            self.lining_value if self.use_lining.isChecked() else None,
            bolts,
            self.load_split.value(),
            self.separate.isChecked(),
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
        for w in self.findChildren(QWidget):
            if w.parent() is self.use_bolts.parent() and w is not self.use_bolts:
                w.setEnabled(self.use_bolts.isChecked())
        p = self.lining_value.liner_properties()
        EA, EI = self.lining_value.stiffness()
        self.lining_label.setText(
            f"<b>{self.lining_value.name}</b><br>t = {self.lining_value.thickness * 100:.0f} cm"
            f" · hasır {self.lining_value.mesh} · iksa {self.lining_value.rib}"
            f"<br>EA = {EA:,.0f} kN/m · EI = {EI:,.1f} kNm²/m · A = {p['A']:.4f} m²/m"
        )
        try:
            self.preview.set_design(self.design())
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
            (self.load_split, design.load_split),
        ]:
            w.setValue(value)
        self.segments.setValue(sec.segments)
        self.use_lining.setChecked(design.lining is not None)
        if design.lining is not None:
            self.lining_value = design.lining
        self.use_bolts.setChecked(design.bolts is not None)
        if design.bolts is not None:
            b = design.bolts
            self.bolt_count.setValue(max(b.count, 1))
            for w, value in [
                (self.bolt_length, b.length),
                (self.bolt_start, b.start_angle),
                (self.bolt_end, b.end_angle),
                (self.bolt_EA, b.EA),
                (self.bolt_T, b.T_yield),
                (self.bolt_spacing, b.spacing_out_of_plane),
                (self.bolt_pre, b.pretension),
            ]:
                w.setValue(value)
        self.separate.setChecked(design.separate_support_stage)
        self.refresh()


# --------------------------------------------------------------------------- bolts
class BoltPatternDialog(QDialog):
    """Bolt pattern along a selected line: count, length, angle to the line and margins."""

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Bulon paterni · {host}")
        form = QFormLayout(self)
        default = BoltPattern()
        self.count = QSpinBox()
        self.count.setRange(1, 500)
        self.count.setValue(5)
        self.length = _spin(default.length, 0.1, 100, 2, "m")
        self.angle = _spin(90.0, -180, 180, 1, "°")
        self.angle.setToolTip("Çizgi yönünden saat yönü tersine açı (90° = sol normal)")
        self.margin = _spin(0.5, 0, 1e4, 2, "m")
        self.EA = _spin(default.EA, 1, 1e9, 0, "kN")
        self.T = _spin(default.T_yield, 1, 1e6, 1, "kN")
        self.spacing = _spin(default.spacing_out_of_plane, 0.1, 20, 2, "m")
        self.pre = _spin(0.0, 0, 1e5, 1, "kN")
        for label, w in [
            ("Bulon sayısı", self.count),
            ("Boy", self.length),
            ("Çizgiye açı", self.angle),
            ("Uçlardan kenar payı", self.margin),
            ("EA (tek bulon)", self.EA),
            ("Akma kuvveti", self.T),
            ("Düzlem dışı aralık", self.spacing),
            ("Öngerme", self.pre),
        ]:
            form.addRow(label, w)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def pattern(self):
        return BoltPattern(
            self.count.value(),
            self.length.value(),
            EA=self.EA.value(),
            T_yield=self.T.value(),
            spacing_out_of_plane=self.spacing.value(),
            pretension=self.pre.value(),
        )


__all__ = [
    "BoltPatternDialog",
    "LiningDesignerDialog",
    "TunnelDesignerDialog",
    "library",
    "library_remove",
    "library_store",
]

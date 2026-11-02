"""Editable support assignment for the selected CAD object."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..cad.supports import BOLT_GRADES, SupportAssignment, bolt_section, default_properties, pile_section

LABELS = {
    "E": "E (kPa)",
    "nu": "ν",
    "A": "A (m²/m)",
    "I": "I (m⁴/m)",
    "As": "As (m²/m)",
    "unit_weight": "γ (kN/m³)",
    "EA": "EA (kN / single nail)",
    "diameter_mm": "Bolt nominal diameter (mm)",
    "grade_code": "Steel grade",
    "T_yield": "Yield force (kN)",
    "pretension": "Pretension (kN)",
    "spacing_out_of_plane": "Out-of-plane spacing (m)",
    "D": "Pile diameter D (m)",
    "spacing": "Pile spacing s (m)",
    "interface": "Structural interface (both faces)",
    "T_skin": "Skin friction T (kN/m, single pile)",
    "kn": "Interface kn (kPa/m)",
    "ks": "Interface ks (kPa/m)",
}


class DrawingSupportPanel(QWidget):
    apply_requested = Signal()

    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        self.selection = QLabel("Select an object from the drawing.")
        self.selection.setWordWrap(True)
        root.addWidget(self.selection)
        self.kind = QComboBox()
        for title, value in [
            ("No support", ""),
            ("Pile / beam", "pile"),
            ("Lining / liner", "liner"),
            ("Anchor / soil nail", "bolt"),
        ]:
            self.kind.addItem(title, value)
        root.addWidget(self.kind)
        self.active = QCheckBox("Active in the CAD loading stage")
        self.active.setChecked(True)
        root.addWidget(self.active)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        fields = QWidget()
        self.form = QFormLayout(fields)
        scroll.setWidget(fields)
        root.addWidget(scroll, 1)
        self.section = QLabel()
        self.section.setWordWrap(True)
        self.section.setStyleSheet("color:#173b52;background:#eef4f8;padding:4px")
        root.addWidget(self.section)
        self.composite = QPushButton("Composite lining (shotcrete + wire mesh + steel set)…")
        self.composite.clicked.connect(self.design_lining)
        root.addWidget(self.composite)
        self.fields = {}
        self.kind.currentIndexChanged.connect(self.populate)
        self.note = QLabel(
            "Pile/beam sections are per metre out of plane. Pile default: "
            "D=0.8 m, spacing=2 m. Lining default: t=0.3 m. "
            "An anchor/nail is a fully bonded BAR2 along the line. "
            "Nodes are shared with the soil; a slip interface is defined separately."
        )
        self.note.setWordWrap(True)
        root.addWidget(self.note)
        button = QPushButton("Apply support to the selected object")
        button.clicked.connect(self.apply_requested)
        root.addWidget(button)
        self.populate()

    def populate(self, *_, properties=None):
        while self.form.rowCount():
            self.form.removeRow(0)
        self.fields = {}
        kind = self.kind.currentData()
        if kind:
            for key, value in (properties or default_properties(kind)).items():
                if key == "grade_code":
                    field = QComboBox()
                    for code, (title, _, _) in BOLT_GRADES.items():
                        field.addItem(title, code)
                    field.setCurrentIndex(field.findData(int(value)))
                    field.currentIndexChanged.connect(self.update_section)
                elif key == "interface":
                    field = QCheckBox("Pile–soil interface")
                    field.setChecked(bool(value))
                    field.toggled.connect(self.update_section)
                else:
                    field = QLineEdit(f"{value:.12g}")
                    field.textChanged.connect(self.update_section)
                self.fields[key] = field
                self.form.addRow(LABELS.get(key, key), field)
        self.composite.setVisible(kind == "liner")
        self.update_section()

    def values(self):
        return {
            k: (w.currentData() if isinstance(w, QComboBox) else
                (1.0 if w.isChecked() else 0.0) if isinstance(w, QCheckBox)
                else float(w.text()))
            for k, w in self.fields.items()
        }

    def update_section(self, *_):
        """Live equivalent section of a pile row (per metre out of plane)."""
        if "diameter_mm" in self.fields:
            self.section.show()
            try:
                data = self.values()
                ea, fy = bolt_section(data["diameter_mm"], data["grade_code"])
                self.section.setText(
                    f"Nominal steel bolt: EA={ea:,.1f} kN, yield={fy:,.1f} kN. "
                    "Bond, corrosion and threaded-area reduction are not included."
                )
            except (ValueError, KeyError) as exc:
                self.section.setText(str(exc))
            return
        if "D" not in self.fields:
            self.section.hide()
            return
        self.section.show()
        try:
            v = self.values()
            area, inertia = pile_section(v["D"], v["spacing"])
            text = (
                f"Equivalent section (1 m): A = πD²/4/s = {area:.4f} m²/m · "
                f"I = πD⁴/64/s = {inertia:.3e} m⁴/m · EI = {v['E'] * inertia:,.0f} kNm²/m"
            )
            if v.get("interface"):
                c = v["T_skin"] / (2 * v["spacing"])
                text += f"\nInterface shear strength c = T/(2s) = {c:.1f} kPa"
            self.section.setText(text)
        except (ValueError, KeyError) as exc:
            self.section.setText(str(exc))

    def design_lining(self):
        from .tunnel_designer import LiningDesignerDialog

        dialog = LiningDesignerDialog(parent=self)
        if dialog.exec() == LiningDesignerDialog.DialogCode.Accepted:
            for key, value in dialog.lining().liner_properties().items():
                if key in self.fields:
                    self.fields[key].setText(f"{value:.12g}")

    def load(self, entity, assignment):
        self.selection.setText(
            f"Selected: {entity.name}" if entity else "Select an object from the drawing."
        )
        kind = assignment.kind if assignment else ""
        self.kind.blockSignals(True)
        self.kind.setCurrentIndex(self.kind.findData(kind))
        self.kind.blockSignals(False)
        self.populate(properties=assignment.properties if assignment else None)
        if assignment:
            self.active.setChecked(assignment.active)

    def assignment(self, entity):
        kind = self.kind.currentData()
        if not kind:
            return None
        return SupportAssignment(
            entity.name,
            kind,
            self.values(),
            self.active.isChecked(),
        )

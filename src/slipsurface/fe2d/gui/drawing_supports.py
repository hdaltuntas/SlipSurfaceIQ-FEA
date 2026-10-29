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

from ..cad.supports import SupportAssignment, default_properties, pile_section

LABELS = {
    "E": "E (kPa)",
    "nu": "ν",
    "A": "A (m²/m)",
    "I": "I (m⁴/m)",
    "As": "As (m²/m)",
    "unit_weight": "γ (kN/m³)",
    "EA": "EA (kN / tek çivi)",
    "T_yield": "Akma kuvveti (kN)",
    "pretension": "Öngerme (kN)",
    "spacing_out_of_plane": "Düzlem dışı aralık (m)",
    "D": "Kazık çapı D (m)",
    "spacing": "Kazık aralığı s (m)",
    "interface": "Yapısal ara yüz (iki yüz)",
    "T_skin": "Çevre sürtünmesi T (kN/m, tek kazık)",
    "kn": "Ara yüz kn (kPa/m)",
    "ks": "Ara yüz ks (kPa/m)",
}


class DrawingSupportPanel(QWidget):
    apply_requested = Signal()

    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        self.selection = QLabel("Çizimden bir nesne seçin.")
        self.selection.setWordWrap(True)
        root.addWidget(self.selection)
        self.kind = QComboBox()
        for title, value in [
            ("Destek yok", ""),
            ("Kazık / kiriş", "pile"),
            ("Kaplama / liner", "liner"),
            ("Ankraj / zemin çivisi", "bolt"),
        ]:
            self.kind.addItem(title, value)
        root.addWidget(self.kind)
        self.active = QCheckBox("CAD yükleme aşamasında etkin")
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
        self.composite = QPushButton("Kompozit kaplama (püskürtme beton + hasır + iksa)…")
        self.composite.clicked.connect(self.design_lining)
        root.addWidget(self.composite)
        self.fields = {}
        self.kind.currentIndexChanged.connect(self.populate)
        self.note = QLabel(
            "Kazık/kiriş kesitleri düzlem dışı metre başınadır. Kazık varsayılanı: "
            "D=0,8 m, aralık=2 m. Kaplama varsayılanı: t=0,3 m. "
            "Ankraj/çivi çizgi boyunca tam bağlı BAR2 olarak modellenir. "
            "Zemin ile ortak düğüm kullanılır; kayma ara yüzü ayrıca tanımlanır."
        )
        self.note.setWordWrap(True)
        root.addWidget(self.note)
        button = QPushButton("Desteği seçili nesneye uygula")
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
                if key == "interface":
                    field = QCheckBox("Kazık–zemin ara yüzü")
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
            k: (1.0 if w.isChecked() else 0.0) if isinstance(w, QCheckBox) else float(w.text())
            for k, w in self.fields.items()
        }

    def update_section(self, *_):
        """Live equivalent section of a pile row (per metre out of plane)."""
        if "D" not in self.fields:
            self.section.hide()
            return
        self.section.show()
        try:
            v = self.values()
            area, inertia = pile_section(v["D"], v["spacing"])
            text = (
                f"Eşdeğer kesit (1 m): A = πD²/4/s = {area:.4f} m²/m · "
                f"I = πD⁴/64/s = {inertia:.3e} m⁴/m · EI = {v['E'] * inertia:,.0f} kNm²/m"
            )
            if v.get("interface"):
                c = v["T_skin"] / (2 * v["spacing"])
                text += f"\nAra yüz kayma dayanımı c = T/(2s) = {c:.1f} kPa"
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
        self.selection.setText(f"Seçili: {entity.name}" if entity else "Çizimden bir nesne seçin.")
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

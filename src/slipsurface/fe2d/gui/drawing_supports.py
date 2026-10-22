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

from ..cad.supports import SupportAssignment, default_properties

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

    def populate(self, *_):
        while self.form.rowCount():
            self.form.removeRow(0)
        self.fields = {}
        kind = self.kind.currentData()
        if kind:
            for key, value in default_properties(kind).items():
                field = QLineEdit(f"{value:.12g}")
                self.fields[key] = field
                self.form.addRow(LABELS[key], field)

    def load(self, entity, assignment):
        self.selection.setText(f"Seçili: {entity.name}" if entity else "Çizimden bir nesne seçin.")
        kind = assignment.kind if assignment else ""
        self.kind.setCurrentIndex(self.kind.findData(kind))
        self.populate()
        if assignment:
            for key, value in assignment.properties.items():
                self.fields[key].setText(f"{value:.12g}")
            self.active.setChecked(assignment.active)

    def assignment(self, entity):
        kind = self.kind.currentData()
        if not kind:
            return None
        return SupportAssignment(
            entity.name,
            kind,
            {k: float(w.text()) for k, w in self.fields.items()},
            self.active.isChecked(),
        )

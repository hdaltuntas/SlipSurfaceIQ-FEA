"""Material library and region assignments, committed only when the dialog accepts."""

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QScrollArea,
    QSplitter,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import api
from ..fem.materials import build
from ..model.materials import DP_MATCH
from .editing import put_material, remove_material, validate_edit
from .form_helpers import EditorDialog, table, toolbar

MODELS = ["elastic", "mohr_coulomb", "hoek_brown", "mcc", "drucker_prager", "von_mises"]
PARAM_LABELS = {
    "E": "E (kPa)",
    "nu": "Poisson ν",
    "c": "Kohezyon c (kPa)",
    "phi": "Sürtünme φ (°)",
    "psi": "Dilatans ψ (°)",
    "sig_t": "Çekme sınırı (kPa; boş=yok)",
    "rankine_at_apex": "Apex'te açık Rankine akışı",
    "Kw_n": "Kw/n (kPa; boş=otomatik)",
    "sigci": "Sağlam kaya UCS (kPa)",
    "GSI": "GSI",
    "mi": "mi",
    "D": "Bozulma D",
    "M": "M",
    "lam": "λ (e–ln p)",
    "kappa": "κ (e–ln p)",
    "e0": "e₀",
    "OCR": "OCR",
    "p_min": "Minimum p (kPa)",
    "p_ref": "Referans p (kPa)",
    "sy": "Akma dayanımı (kPa)",
    "H": "Pekleşme H (kPa)",
    "match": "DP eşleştirme",
}


def default_material(kind, name="Yeni malzeme"):
    constructors = {
        "elastic": lambda: api.MaterialSpec.elastic(name, 20000, 0.3),
        "mohr_coulomb": lambda: api.MaterialSpec.mohr_coulomb(name, 20000, 0.3, 20, 30),
        "hoek_brown": lambda: api.MaterialSpec.hoek_brown(name, 1e6, 0.25, 50000, 50, 10),
        "mcc": lambda: api.MaterialSpec.mcc(name, 0.3, 1.2, 0.15, 0.03, 1.0),
        "drucker_prager": lambda: api.MaterialSpec.drucker_prager(name, 20000, 0.3, 20, 30),
        "von_mises": lambda: api.MaterialSpec.von_mises(name, 20000, 0.3, 50),
    }
    return constructors[kind]()


class MaterialSpecDialog(EditorDialog):
    def __init__(self, spec=None, parent=None):
        super().__init__("Malzeme tanımı", parent)
        self.resize(560, 780)
        self.original = spec or default_material("elastic")
        form = QFormLayout()
        self.name = QLineEdit(self.original.name)
        self.kind = QComboBox()
        self.kind.addItems(MODELS)
        self.kind.setCurrentText(self.original.model)
        form.addRow("Ad", self.name)
        form.addRow("Bünye", self.kind)
        self.root.addLayout(form)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.parameters = QFormLayout(content)
        scroll.setWidget(content)
        self.root.addWidget(scroll, 1)
        self.fields = {}
        self.populate(self.original)
        self.kind.currentTextChanged.connect(lambda k: self.populate(default_material(k)))
        other = QFormLayout()
        self.extra = {}
        for key, title, value in [
            ("gamma", "γ (kN/m³)", self.original.gamma_unsat),
            ("gamma_sat", "γ doygun (kN/m³)", self.original.gamma_sat),
            ("kx", "kx (m/s)", self.original.k_sat[0]),
            ("ky", "ky (m/s)", self.original.k_sat[1]),
            ("alpha", "VG α (1/m)", self.original.vg[0]),
            ("n", "VG n", self.original.vg[1]),
            ("floor", "VG bağıl k alt sınırı", self.original.vg[2]),
        ]:
            self.extra[key] = QLineEdit(str(value))
            other.addRow(title, self.extra[key])
        self.drainage = QComboBox()
        for drainage in api.Drainage:
            self.drainage.addItem(drainage.value, drainage)
        self.drainage.setCurrentIndex(list(api.Drainage).index(self.original.drainage))
        other.addRow("Drenaj", self.drainage)
        self.root.addLayout(other)
        note = QLabel(
            "B: φ=0 ve c=su; C: toplam gerilme parametreleri. "
            "Rankine seçeneği ayrı bir akış kuralıdır; varsayılan kapalıdır."
        )
        note.setWordWrap(True)
        self.root.addWidget(note)
        self.finish_layout(self.apply)

    def populate(self, spec):
        while self.parameters.rowCount():
            self.parameters.removeRow(0)
        self.fields.clear()
        params = dict(spec.params)
        params.setdefault("Kw_n", None)
        if spec.model == "mohr_coulomb":
            params.setdefault("sig_t", None)
            params.setdefault("rankine_at_apex", False)
        for key, value in params.items():
            if key == "rankine_at_apex":
                widget = QCheckBox()
                widget.setChecked(bool(value))
            elif key == "match":
                widget = QComboBox()
                widget.addItems(DP_MATCH)
                widget.setCurrentIndex(int(value))
            else:
                widget = QLineEdit("" if value is None else str(value))
            self.fields[key] = widget
            self.parameters.addRow(PARAM_LABELS.get(key, key), widget)

    def specification(self):
        params = {}
        for key, widget in self.fields.items():
            if isinstance(widget, QCheckBox):
                params[key] = widget.isChecked()
            elif isinstance(widget, QComboBox):
                params[key] = widget.currentIndex()
            elif widget.text().strip():
                params[key] = float(widget.text())
            elif key not in {"Kw_n", "sig_t"}:
                raise ValueError(f"{key} boş olamaz.")
        v = {k: float(w.text()) for k, w in self.extra.items()}
        spec = api.MaterialSpec(
            self.name.text().strip(),
            self.kind.currentText(),
            params,
            v["gamma"],
            v["gamma_sat"],
            self.drainage.currentData(),
            (v["kx"], v["ky"]),
            (v["alpha"], v["n"], v["floor"]),
        )
        build(spec)
        return spec

    def apply(self):
        try:
            self.updated = self.specification()
        except Exception as exc:
            self.error(exc)
            return
        self.accept()


class MaterialDialog(EditorDialog):
    def __init__(self, model, parent=None):
        super().__init__("Malzemeler ve bölge atamaları", parent)
        self.model = model
        self.resize(900, 540)
        self.root.addWidget(
            QLabel(
                "Yeni malzemeyi oluşturun, ardından bölgelere atayın. "
                "Aşama değişimleri Aşamalar → Ayrıntı altında."
            )
        )
        split = QSplitter()
        self.list = QListWidget()
        split.addWidget(self.list)
        right = QWidget()
        layout = QVBoxLayout(right)
        self.assignments = table(["Bölge", "Malzeme"])
        layout.addWidget(self.assignments)
        split.addWidget(right)
        self.root.addWidget(split)
        toolbar(
            self.root,
            [
                ("Yeni", self.add_material),
                ("Düzenle", self.edit_material),
                ("Kopyala", self.copy_material),
                ("Sil", self.delete_material),
            ],
        )
        self.list.itemDoubleClicked.connect(self.edit_material)
        self.refresh()
        self.finish_layout(self.apply)

    def refresh(self):
        self.list.clear()
        self.list.addItems(list(self.model.materials))
        self.regions = sorted(self.model.mesh.regions())
        self.assignments.setRowCount(len(self.regions))
        for i, region in enumerate(self.regions):
            item = QTableWidgetItem(str(region))
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.assignments.setItem(i, 0, item)
            box = QComboBox()
            box.addItems(list(self.model.materials))
            box.setCurrentText(self.model.region_material[region])
            self.assignments.setCellWidget(i, 1, box)

    def current_model(self):
        mapping = dict(self.model.region_material)
        mapping.update(
            {r: self.assignments.cellWidget(i, 1).currentText() for i, r in enumerate(self.regions)}
        )
        return replace(self.model, region_material=mapping)

    def store_material(self, spec, old_name=None):
        self.model = put_material(self.current_model(), spec, old_name)
        self.refresh()

    def add_material(self):
        dialog = MaterialSpecDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.store_material(dialog.updated)
            except Exception as exc:
                self.error(exc)

    def selected_name(self):
        return self.list.currentItem().text() if self.list.currentItem() else None

    def edit_material(self, *_):
        name = self.selected_name()
        if name is None:
            return
        dialog = MaterialSpecDialog(self.model.materials[name], self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.store_material(dialog.updated, name)
            except Exception as exc:
                self.error(exc)

    def copy_material(self):
        name = self.selected_name()
        if name is None:
            return
        index = 1
        while f"{name} ({index})" in self.model.materials:
            index += 1
        self.store_material(replace(self.model.materials[name], name=f"{name} ({index})"))

    def delete_material(self):
        name = self.selected_name()
        if name is not None:
            try:
                self.model = remove_material(self.current_model(), name)
                self.refresh()
            except Exception as exc:
                self.error(exc)

    def apply(self):
        try:
            self.updated = validate_edit(self.current_model())
        except Exception as exc:
            self.error(exc)
            return
        self.accept()

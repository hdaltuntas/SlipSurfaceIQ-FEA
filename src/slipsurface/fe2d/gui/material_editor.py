"""Material library and region assignments, committed only when the dialog accepts."""

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
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
from ..fem.materials import build, hb_parameters
from ..model.materials import DP_MATCH, hoek_diederichs_ratio
from .editing import apply_blast_disturbance, put_material, remove_material, validate_edit
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
    "D": "Örselenme faktörü D",
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
        self.hb_preview = QLabel()
        self.hb_preview.setWordWrap(True)
        self.hb_preview.setStyleSheet("padding:6px;background:#eef4f8;color:#173b52")
        self.root.addWidget(self.hb_preview)
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
            if spec.model == "hoek_brown" and key in {"E", "GSI", "mi", "D"} and isinstance(
                widget, QLineEdit
            ):
                widget.textChanged.connect(self._update_hb)
        self.hb_preview.setVisible(spec.model == "hoek_brown")
        if spec.model == "hoek_brown":
            self._update_hb()

    def _update_hb(self, *_):
        try:
            E = float(self.fields["E"].text())
            gsi = float(self.fields["GSI"].text())
            mi = float(self.fields["mi"].text())
            D = float(self.fields["D"].text() or 0)
            mb, s, a = hb_parameters(gsi, mi, D)
            ratio = hoek_diederichs_ratio(gsi, D) / hoek_diederichs_ratio(gsi, 0.0)
            self.hb_preview.setText(
                f"Kaya kütlesi: mb = {mb:.4g} · s = {s:.4g} · a = {a:.4g} · E = {E:.4g} kPa\n"
                f"Hoek–Diederichs Erm(D)/Erm(0) = {ratio:.3f}. "
                f"Örselenmiş kopya bu D ile E ve D'yi günceller; ana malzeme D=0 kalmalıdır."
            )
        except (KeyError, TypeError, ValueError):
            self.hb_preview.setText("GSI, mi ve D girilince mb, s, a ve E oranı hesaplanır.")

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
                ("Örselenmiş kopya", self.disturb_material),
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

    def disturb_material(self):
        name = self.selected_name()
        if name is None:
            return
        spec = self.model.materials[name]
        if spec.model != "hoek_brown":
            self.error(ValueError("Örselenme yalnız Hoek-Brown kaya malzemesinde tanımlanır."))
            return
        dialog = DisturbanceDialog(spec, self.model, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            if dialog.assign:
                self.model = apply_blast_disturbance(
                    self.current_model(), dialog.updated, parent=spec.name
                )
                self.refresh()
            else:
                self.store_material(dialog.updated)
        except Exception as exc:
            self.error(exc)

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


class DisturbanceDialog(QDialog):
    """Create a Hoek-Brown copy with blast factor D and reduced E."""

    def __init__(self, spec, model, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Örselenmiş kopya · {spec.name}")
        self.parent_spec = spec
        self.updated = None
        self.assign = False
        from .editing import blast_disturbance_regions

        layout = QFormLayout(self)
        D0 = float(spec.params.get("D", 0.0))
        self.D = QDoubleSpinBox()
        self.D.setRange(0.0, 1.0)
        self.D.setDecimals(2)
        self.D.setValue(0.8 if D0 == 0 else D0)
        self.name = QLineEdit(f"{spec.name}_D{self.D.value():g}")
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.assign_box = QCheckBox("Patlatma zonuna ve kazıdan sonraki aşamalara ata")
        regions = blast_disturbance_regions(model.geometry)
        self.assign_box.setEnabled(bool(regions))
        self.assign_box.setChecked(bool(regions))
        if not regions:
            self.assign_box.setText("Patlatma zonu yok (tünel tasarımcısından eklenir)")
        layout.addRow("Örselenme faktörü D", self.D)
        layout.addRow("Yeni malzeme adı", self.name)
        layout.addRow(self.preview)
        layout.addRow(self.assign_box)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        self.D.valueChanged.connect(self._refresh)
        self._refresh()

    def _refresh(self, *_):
        D = self.D.value()
        try:
            spec = self.parent_spec.with_disturbance(D, self.name.text().strip() or None)
        except Exception as exc:
            self.preview.setText(str(exc))
            return
        p, q = self.parent_spec.params, spec.params
        mb0, s0, a0 = hb_parameters(p["GSI"], p["mi"], p.get("D", 0.0))
        mb, s, a = hb_parameters(q["GSI"], q["mi"], q["D"])
        self.preview.setText(
            f"E {p['E']:.4g} → {q['E']:.4g} kPa  (×{q['E'] / p['E']:.3f})\n"
            f"mb {mb0:.4g} → {mb:.4g} · s {s0:.4g} → {s:.4g} · a = {a:.4g}"
        )
        auto = f"{self.parent_spec.name}_D{self.D.value():g}"
        if not self.name.text() or self.name.text() == auto:
            self.name.setText(f"{self.parent_spec.name}_D{D:g}")

    def _accept(self):
        try:
            self.updated = self.parent_spec.with_disturbance(
                self.D.value(), self.name.text().strip() or None
            )
            build(self.updated)
        except Exception as exc:
            self.preview.setText(str(exc))
            return
        self.assign = self.assign_box.isChecked() and self.assign_box.isEnabled()
        self.accept()

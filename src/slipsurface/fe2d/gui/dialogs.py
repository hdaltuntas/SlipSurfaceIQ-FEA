"""Small, transactional model editors for the first native desktop milestone."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .. import api
from ..core.errors import SlipSurfaceError
from ..mesh import rectangle


def sample_model(width=12.0, height=6.0, nx=12, ny=6, E=20000.0, nu=0.3, load=50.0):
    mesh = rectangle(width, height, nx, ny)
    return api.Model(
        api.Analysis.PLANE_STRAIN,
        mesh,
        {"soil": api.MaterialSpec.elastic("soil", E, nu)},
        {1: "soil"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        initial=api.InitialStress("none"),
        stages=[api.Stage("Yükleme", loads=(api.EdgeLoad("top", qn=load),))],
    )


def buttons(dialog, layout, accept):
    box = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    box.accepted.connect(accept)
    box.rejected.connect(dialog.reject)
    layout.addWidget(box)


class NewModelDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Yeni dikdörtgen zemin modeli")
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Düzlem şekil değiştirme · T6 · taban sabit · yanlar yatay sabit\n"
                "Üst kenara basınç; başlangıç gerilmesi ve ağırlık sıfır."
            )
        )
        form = QFormLayout()
        self.fields = {}
        specs = [
            ("width", "Genişlik (m)", 12.0, 0.1, 10000.0),
            ("height", "Yükseklik (m)", 6.0, 0.1, 10000.0),
            ("nx", "Yatay ağ bölümü", 12, 1, 100),
            ("ny", "Düşey ağ bölümü", 6, 1, 100),
            ("E", "E (kPa)", 20000.0, 1.0, 1e10),
            ("nu", "Poisson oranı", 0.3, 0.0, 0.499),
            ("load", "Üst basınç (kPa)", 50.0, -1e6, 1e6),
        ]
        for key, title, value, low, high in specs:
            widget = QSpinBox() if isinstance(value, int) else QDoubleSpinBox()
            widget.setRange(low, high)
            if isinstance(widget, QDoubleSpinBox):
                widget.setDecimals(4)
            widget.setValue(value)
            self.fields[key] = widget
            form.addRow(title, widget)
        layout.addLayout(form)
        buttons(self, layout, self.accept)

    def model(self):
        return sample_model(**{k: w.value() for k, w in self.fields.items()})


class MaterialDialog(QDialog):
    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.updated = None
        self.setWindowTitle("Malzeme özellikleri")
        layout = QVBoxLayout(self)
        self.choice = QComboBox()
        self.choice.addItems(model.materials)
        layout.addWidget(self.choice)
        self.form = QFormLayout()
        layout.addLayout(self.form)
        self.fields = {}
        self.choice.currentTextChanged.connect(self.populate)
        self.populate(self.choice.currentText())
        buttons(self, layout, self.apply)

    def populate(self, name):
        while self.form.rowCount():
            self.form.removeRow(0)
        self.fields.clear()
        mat = self.model.materials[name]
        self.form.addRow("Bünye modeli", QLabel(mat.model))
        for key, value in mat.params.items():
            widget = QCheckBox() if isinstance(value, bool) else QLineEdit(str(value))
            if isinstance(widget, QCheckBox):
                widget.setChecked(value)
            self.fields[key] = widget
            self.form.addRow(key, widget)
        self.gamma = QLineEdit(str(mat.gamma_unsat))
        self.gamma_sat = QLineEdit(str(mat.gamma_sat))
        self.form.addRow("γ (kN/m³)", self.gamma)
        self.form.addRow("γ doygun (kN/m³)", self.gamma_sat)
        self.drainage = QComboBox()
        for d in api.Drainage:
            self.drainage.addItem(d.value, d)
        self.drainage.setCurrentIndex(list(api.Drainage).index(mat.drainage))
        self.form.addRow("Drenaj", self.drainage)

    def apply(self):
        try:
            name = self.choice.currentText()
            mat = self.model.materials[name]
            params = {
                k: w.isChecked() if isinstance(w, QCheckBox) else float(w.text())
                for k, w in self.fields.items()
            }
            mat = replace(
                mat,
                params=params,
                gamma_unsat=float(self.gamma.text()),
                gamma_sat=float(self.gamma_sat.text()),
                drainage=self.drainage.currentData(),
            )
            from ..fem.materials import build

            build(mat)
            self.updated = replace(self.model, materials={**self.model.materials, name: mat})
            self.updated.validate()
        except (ValueError, TypeError, KeyError, SlipSurfaceError) as exc:
            QMessageBox.warning(self, "Geçersiz malzeme", str(exc))
            return
        self.accept()


class StageDialog(QDialog):
    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model, self.updated = model, None
        self.setWindowTitle("Aşama yöneticisi")
        self.resize(850, 360)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Aktif bölgeler: boş = tümü; örnek 1,2. Yapılar: etiketler virgülle.\n"
                "Yükler, su ve yer değiştirme sınırları korunur."
            )
        )
        self.table = QTableWidget(len(model.stages), 5)
        self.table.setHorizontalHeaderLabels(
            ["Ad", "Serbest bırakma λ", "Drenajlı", "Aktif bölgeler", "Aktif yapılar"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for i, stage in enumerate(model.stages):
            vals = [
                stage.name,
                str(stage.load_split),
                "",
                ""
                if stage.active_regions is None
                else ",".join(map(str, sorted(stage.active_regions))),
                ",".join(sorted(stage.active_structures)),
            ]
            for j, v in enumerate(vals):
                self.table.setItem(i, j, QTableWidgetItem(v))
            item = self.table.item(i, 2)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if stage.drained else Qt.CheckState.Unchecked)
        layout.addWidget(self.table)
        buttons(self, layout, self.apply)

    def apply(self):
        try:
            stages = []
            for i, st in enumerate(self.model.stages):
                text = [self.table.item(i, j).text().strip() for j in range(5)]
                if not text[0]:
                    raise ValueError("Aşama adı boş olamaz.")
                regions = frozenset(int(x.strip()) for x in text[3].split(",")) if text[3] else None
                structures = frozenset(x.strip() for x in text[4].split(",") if x.strip())
                stages.append(
                    replace(
                        st,
                        name=text[0],
                        load_split=float(text[1]),
                        drained=self.table.item(i, 2).checkState() == Qt.CheckState.Checked,
                        active_regions=regions,
                        active_structures=structures,
                    )
                )
            self.updated = replace(self.model, stages=stages)
            self.updated.validate()
        except (ValueError, TypeError, KeyError, SlipSurfaceError) as exc:
            QMessageBox.warning(self, "Geçersiz aşama", str(exc))
            return
        self.accept()

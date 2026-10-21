"""Small, transactional model editors for the first native desktop milestone."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from .. import api
from ..mesh import rectangle
from .material_editor import MaterialDialog as MaterialDialog
from .stage_editor import StageDialog as StageDialog


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

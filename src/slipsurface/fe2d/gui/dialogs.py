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
        stages=[api.Stage("Loading", loads=(api.EdgeLoad("top", qn=load),))],
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
        self.setWindowTitle("New rectangular soil model")
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Plane strain · T6 · base fixed · sides fixed horizontally\n"
                "Pressure on the top edge; initial stress and self-weight are zero."
            )
        )
        form = QFormLayout()
        self.fields = {}
        specs = [
            ("width", "Width (m)", 12.0, 0.1, 10000.0),
            ("height", "Height (m)", 6.0, 0.1, 10000.0),
            ("nx", "Horizontal mesh divisions", 12, 1, 100),
            ("ny", "Vertical mesh divisions", 6, 1, 100),
            ("E", "E (kPa)", 20000.0, 1.0, 1e10),
            ("nu", "Poisson's ratio", 0.3, 0.0, 0.499),
            ("load", "Top pressure (kPa)", 50.0, -1e6, 1e6),
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

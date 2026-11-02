"""Project schedule and picked-region assignment forms."""

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QTableWidgetItem,
)

from .editing import region_label, set_region_stage_state, stage_region_material
from .form_helpers import EditorDialog, table


class ProjectPropertiesDialog(EditorDialog):
    def __init__(self, names, parent=None):
        super().__init__("Project properties", parent)
        self.resize(540, 460)
        self._names = list(names) or ["Stage 1"]
        self.count = QSpinBox()
        self.count.setRange(1, max(1000, len(self._names)))
        self.count.setValue(len(self._names))
        form = QFormLayout()
        form.addRow("Construction stages (excluding Initial)", self.count)
        self.root.addLayout(form)
        self.names = table(["Stage name"])
        self.names.verticalHeader().setMinimumWidth(32)
        self.root.addWidget(self.names)
        note = QLabel(
            "0. Initial is always present. Reducing the count removes stages from the end. "
            "Existing stage settings are kept; added stages copy the preceding stage "
            "with full load release. Use Stages for loads, supports and relaxation."
        )
        note.setWordWrap(True)
        self.root.addWidget(note)
        self._resize_names(len(self._names))
        self.count.valueChanged.connect(self._resize_names)
        self.finish_layout(self.apply)

    def _resize_names(self, count):
        for i in range(self.names.rowCount()):
            self._names[i] = self.names.item(i, 0).text()
        while len(self._names) < count:
            n = len(self._names) + 1
            while f"Stage {n}" in self._names:
                n += 1
            self._names.append(f"Stage {n}")
        self.names.setRowCount(count)
        for i in range(count):
            self.names.setItem(i, 0, QTableWidgetItem(self._names[i]))
        self.names.setVerticalHeaderLabels([str(i + 1) for i in range(count)])

    def apply(self):
        names = [self.names.item(i, 0).text().strip() for i in range(self.names.rowCount())]
        if any(not name for name in names) or len(set(names)) != len(names):
            self.error("Stage names must be non-empty and unique.")
            return
        self.updated = names
        self.accept()


class RegionStageDialog(EditorDialog):
    def __init__(self, model, stage_index, region, parent=None):
        super().__init__("Assign materials", parent)
        self.model, self.stage_index, self.region = model, stage_index, region
        self.resize(510, 230)
        name = "Initial" if stage_index == 0 else model.stages[stage_index - 1].name
        form = QFormLayout()
        form.addRow("Stage", QLabel(f"{stage_index}. {name}"))
        form.addRow("Region", QLabel(region_label(model, region)))
        self.material = QComboBox()
        self.material.addItem("Excavated (void)", None)
        for material in model.materials:
            self.material.addItem(material, material)
        self.material.setCurrentIndex(
            self.material.findData(stage_region_material(model, stage_index, region))
        )
        form.addRow("Material", self.material)
        self.root.addLayout(form)
        self.propagate = QCheckBox("Apply to this and all following stages")
        self.root.addWidget(self.propagate)
        note = QLabel(
            "Choose the intact or softened/disturbed material defined under Model > Materials. "
            "By default, only the selected stage changes. Results must be recalculated."
        )
        note.setWordWrap(True)
        self.root.addWidget(note)
        self.finish_layout(self.apply)

    def apply(self):
        try:
            self.updated = set_region_stage_state(
                self.model,
                self.stage_index,
                self.region,
                self.material.currentData(),
                propagate=self.propagate.isChecked(),
            )
        except Exception as exc:
            self.error(exc)
            return
        self.accept()

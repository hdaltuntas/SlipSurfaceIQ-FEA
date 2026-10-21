"""Transactional mechanical restraints and total prescribed displacements."""

from dataclasses import replace

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QLabel,
    QLineEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import api
from ..model.boundary import Displacement
from .editing import validate_edit
from .form_helpers import EditorDialog, remove_row, table, toolbar


class DisplacementEditor(QWidget):
    def __init__(self, mesh, values=(), parent=None):
        super().__init__(parent)
        self.mesh = mesh
        layout = QVBoxLayout(self)
        note = QLabel(
            "Toplam ux/uy (m). Boş bileşen bu satırda tanımlanmaz. "
            "Yer değiştirme mesnet sıfırını, aşama değeri genel değeri geçersiz kılar. "
            "Kesişen kümelerde son satır önceliklidir."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = table(["Düğüm kümesi", "ux (m; boş=tanımsız)", "uy (m; boş=tanımsız)"])
        layout.addWidget(self.table)
        toolbar(layout, [("Ekle", self.add), ("Sil", lambda: remove_row(self.table))])
        for value in values:
            self.add(value)

    def add(self, value=None):
        value = value if isinstance(value, Displacement) else Displacement("")
        row = self.table.rowCount()
        self.table.insertRow(row)
        names = QComboBox()
        names.addItems(sorted(self.mesh.node_sets))
        if value.node_set:
            names.setCurrentText(value.node_set)
        self.table.setCellWidget(row, 0, names)
        for j, v in enumerate([value.ux, value.uy], 1):
            self.table.setCellWidget(row, j, QLineEdit("" if v is None else str(v)))

    def values(self):
        result = []
        for i in range(self.table.rowCount()):
            values = [
                float(w.text()) if w.text().strip() else None
                for w in [self.table.cellWidget(i, j) for j in (1, 2)]
            ]
            if values == [None, None]:
                raise ValueError(
                    "Yer değiştirme satırında en az bir bileşen girin veya satırı silin."
                )
            result.append(Displacement(self.table.cellWidget(i, 0).currentText(), *values))
        return tuple(result)


class BoundaryDialog(EditorDialog):
    def __init__(self, model, parent=None):
        super().__init__("Mekanik sınır koşulları", parent)
        self.model = model
        self.resize(850, 550)
        tabs = QTabWidget()
        pane = QWidget()
        layout = QVBoxLayout(pane)
        layout.addWidget(
            QLabel("İşaretli serbestlik sabit. rz yalnız liner/kiriş düğümlerinde etkili.")
        )
        self.table = table(["Düğüm kümesi", "ux=0", "uy=0", "rz=0"])
        layout.addWidget(self.table)
        toolbar(layout, [("Ekle", self.add), ("Sil", lambda: remove_row(self.table))])
        for fixity in model.fixities:
            self.add(fixity)
        self.displacements = DisplacementEditor(model.mesh, model.displacements)
        tabs.addTab(pane, "Mesnetler")
        tabs.addTab(self.displacements, "Genel yer değiştirme")
        self.root.addWidget(tabs)
        self.finish_layout(self.apply)

    def add(self, value=None):
        value = value if isinstance(value, api.Fixity) else api.Fixity("", False, False)
        row = self.table.rowCount()
        self.table.insertRow(row)
        names = QComboBox()
        names.addItems(sorted(self.model.mesh.node_sets))
        if value.node_set:
            names.setCurrentText(value.node_set)
        self.table.setCellWidget(row, 0, names)
        for j, v in enumerate([value.ux, value.uy, value.rz], 1):
            box = QCheckBox()
            box.setChecked(v)
            self.table.setCellWidget(row, j, box)

    def apply(self):
        try:
            fixities = tuple(
                api.Fixity(
                    self.table.cellWidget(i, 0).currentText(),
                    *[self.table.cellWidget(i, j).isChecked() for j in (1, 2, 3)],
                )
                for i in range(self.table.rowCount())
            )
            self.updated = validate_edit(
                replace(self.model, fixities=fixities, displacements=self.displacements.values())
            )
        except Exception as exc:
            self.error(exc)
            return
        self.accept()

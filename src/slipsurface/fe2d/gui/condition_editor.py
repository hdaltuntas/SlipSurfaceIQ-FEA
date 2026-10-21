"""Native load and groundwater forms shared by stage and initial-state editors."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import api
from ..model.boundary import FluxBC, HeadBC
from .form_helpers import remove_row, table, toolbar


class NamedValues(QWidget):
    def __init__(self, names, heading, values=(), parent=None):
        super().__init__(parent)
        self.names = sorted(names)
        layout = QVBoxLayout(self)
        self.table = table(["Küme", heading])
        layout.addWidget(self.table)
        toolbar(layout, [("Ekle", self.add), ("Sil", lambda: remove_row(self.table))])
        for name, value in values:
            self.add(name, value)

    def add(self, name=None, value=0.0):
        i = self.table.rowCount()
        self.table.insertRow(i)
        box = QComboBox()
        box.addItems(self.names)
        if isinstance(name, str):
            box.setCurrentText(name)
        self.table.setCellWidget(i, 0, box)
        self.table.setCellWidget(i, 1, QLineEdit(str(value)))

    def values(self):
        values = []
        seen = set()
        for i in range(self.table.rowCount()):
            name = self.table.cellWidget(i, 0).currentText()
            if not name or name in seen:
                raise ValueError("Sınır kümesi seçilmeli ve aynı tabloda tek kez kullanılmalı.")
            seen.add(name)
            values.append((name, float(self.table.cellWidget(i, 1).text())))
        return values


class WaterEditor(QWidget):
    def __init__(self, mesh, water, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.mode = QComboBox()
        for label, mode in [
            ("Su yok", "none"),
            ("Piyezometrik çizgi", "piezo_line"),
            ("Durağan sızma", "seepage"),
        ]:
            self.mode.addItem(label, mode)
        form.addRow("Su modeli", self.mode)
        layout.addLayout(form)
        self.piezo = QPlainTextEdit()
        self.piezo.setPlaceholderText("Her satır: x  hidrolik yük h (m)\n0 5\n20 4")
        self.piezo.setMaximumHeight(110)
        if water.piezo_polyline is not None:
            self.piezo.setPlainText(
                "\n".join(f"{x:.17g} {h:.17g}" for x, h in water.piezo_polyline)
            )
        layout.addWidget(self.piezo)
        self.tabs = QTabWidget()
        self.heads = NamedValues(
            mesh.node_sets, "Hidrolik yük h (m)", [(h.node_set, h.head) for h in water.head_bcs]
        )
        self.fluxes = NamedValues(
            mesh.edge_sets, "İçeri akı q (m/s)", [(f.edge_set, f.q) for f in water.flux_bcs]
        )
        self.faces = QListWidget()
        for name in sorted(set(mesh.node_sets) | set(mesh.edge_sets)):
            item = QListWidgetItem(name)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if name in water.seepage_faces else Qt.CheckState.Unchecked
            )
            self.faces.addItem(item)
        self.tabs.addTab(self.heads, "Yük sınırları")
        self.tabs.addTab(self.fluxes, "Akı sınırları")
        self.tabs.addTab(self.faces, "Olası sızma yüzleri")
        layout.addWidget(self.tabs)
        note = QLabel(
            "h toplam hidrolik yük kotudur; basınç yüksekliği değildir. Akı pozitif içeri. "
            "Diğer sızma sınırları geçirimsiz; her bağlantılı bölge referans ister."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.mode.currentIndexChanged.connect(self.update_enabled)
        self.mode.setCurrentIndex(self.mode.findData(water.mode))
        self.update_enabled()

    def update_enabled(self):
        self.piezo.setEnabled(self.mode.currentData() == "piezo_line")
        self.tabs.setEnabled(self.mode.currentData() == "seepage")

    def value(self):
        mode = self.mode.currentData()
        if mode == "none":
            return api.WaterCondition()
        if mode == "piezo_line":
            p = [
                tuple(map(float, line.replace(",", " ").split()))
                for line in self.piezo.toPlainText().splitlines()
                if line.strip()
            ]
            return api.WaterCondition.piezo(p)
        return api.WaterCondition.seepage(
            tuple(HeadBC(name, v) for name, v in self.heads.values()),
            tuple(FluxBC(name, v) for name, v in self.fluxes.values()),
            tuple(
                self.faces.item(i).text()
                for i in range(self.faces.count())
                if self.faces.item(i).checkState() == Qt.CheckState.Checked
            ),
        )


class LoadEditor(QWidget):
    def __init__(self, mesh, loads, parent=None):
        super().__init__(parent)
        self.mesh = mesh
        layout = QVBoxLayout(self)
        note = QLabel(
            "Bu aşamanın toplam yükleri. Kenar: qn basınç (+ içeri), qt teğetsel (kPa). "
            "Nokta: fx/fy global kuvvet (düzlemde kN/m, eksenel simetride kN/rad)."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = table(["Tür", "Kenar kümesi / düğüm", "qn / fx", "qt / fy"])
        layout.addWidget(self.table)
        toolbar(layout, [("Ekle", self.add), ("Sil", lambda: remove_row(self.table))])
        for load in loads:
            self.add(load)

    def add(self, load=None):
        if not isinstance(load, (api.EdgeLoad, api.PointLoad)):
            load = api.EdgeLoad(next(iter(self.mesh.edge_sets), ""))
        i = self.table.rowCount()
        self.table.insertRow(i)
        kind = QComboBox()
        kind.addItems(["Kenar", "Nokta"])
        kind.setCurrentIndex(isinstance(load, api.PointLoad))
        self.table.setCellWidget(i, 0, kind)
        self.set_target(kind)
        target = self.table.cellWidget(i, 1)
        if isinstance(load, api.EdgeLoad):
            target.setCurrentText(load.edge_set)
            a, b = load.qn, load.qt
        else:
            target.setValue(load.node)
            a, b = load.fx, load.fy
        self.table.setCellWidget(i, 2, QLineEdit(str(a)))
        self.table.setCellWidget(i, 3, QLineEdit(str(b)))
        kind.currentIndexChanged.connect(lambda: self.set_target(kind))

    def set_target(self, kind):
        i = next(r for r in range(self.table.rowCount()) if self.table.cellWidget(r, 0) is kind)
        if kind.currentIndex() == 0:
            widget = QComboBox()
            widget.addItems(sorted(self.mesh.edge_sets))
        else:
            widget = QSpinBox()
            widget.setRange(0, self.mesh.nn - 1)
        self.table.setCellWidget(i, 1, widget)

    def values(self):
        result = []
        for i in range(self.table.rowCount()):
            target = self.table.cellWidget(i, 1)
            a, b = (float(self.table.cellWidget(i, j).text()) for j in (2, 3))
            if self.table.cellWidget(i, 0).currentIndex() == 0:
                result.append(api.EdgeLoad(target.currentText(), a, b))
            else:
                result.append(api.PointLoad(target.value(), a, b))
        return tuple(result)

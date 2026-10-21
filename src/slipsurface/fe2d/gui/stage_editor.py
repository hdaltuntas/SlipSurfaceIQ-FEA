"""Transactional initial-state and ordered construction-stage editors."""

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import api
from .condition_editor import LoadEditor, WaterEditor
from .editing import parse_regions, parse_tags, regions_text, validate_edit
from .form_helpers import EditorDialog, table, toolbar


class StageDetailDialog(EditorDialog):
    def __init__(self, model, index, parent=None):
        super().__init__(f"Aşama: {model.stages[index].name}", parent)
        self.model, self.index = model, index
        self.resize(800, 620)
        stage = model.stages[index]
        note = QLabel(
            "Yükler, su ve malzeme değişimleri bu aşamanın toplam tanımıdır; "
            "önceki aşamadan örtük devralınmaz. Mevcut yer değiştirme sınırları korunur."
        )
        note.setWordWrap(True)
        self.root.addWidget(note)
        tabs = QTabWidget()
        self.loads = LoadEditor(model.mesh, stage.loads)
        self.water = WaterEditor(model.mesh, stage.water)
        self.overrides = table(["Bölge", "Bu aşamada malzeme"])
        self.regions = sorted(model.mesh.regions())
        self.overrides.setRowCount(len(self.regions))
        for i, r in enumerate(self.regions):
            item = QTableWidgetItem(str(r))
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.overrides.setItem(i, 0, item)
            box = QComboBox()
            box.addItem(f"Temel atama ({model.region_material[r]})", None)
            for name in model.materials:
                box.addItem(name, name)
            box.setCurrentIndex(box.findData(stage.material_override.get(r)))
            self.overrides.setCellWidget(i, 1, box)
        tabs.addTab(self.loads, "Yükler")
        tabs.addTab(self.water, "Su")
        tabs.addTab(self.overrides, "Malzeme değişimi")
        self.root.addWidget(tabs)
        self.finish_layout(self.apply)

    def apply(self):
        try:
            stage = replace(
                self.model.stages[self.index],
                loads=self.loads.values(),
                water=self.water.value(),
                material_override={
                    r: self.overrides.cellWidget(i, 1).currentData()
                    for i, r in enumerate(self.regions)
                    if self.overrides.cellWidget(i, 1).currentData() is not None
                },
            )
            stages = list(self.model.stages)
            stages[self.index] = stage
            validate_edit(replace(self.model, stages=stages))
            self.updated = stage
        except Exception as exc:
            self.error(exc)
            return
        self.accept()


class InitialDialog(EditorDialog):
    def __init__(self, model, parent=None):
        super().__init__("Başlangıç durumu", parent)
        self.model = model
        init = model.initial
        self.resize(760, 710)
        tabs = QTabWidget()
        pane = QWidget()
        layout = QVBoxLayout(pane)
        form = QFormLayout()
        self.mode = QComboBox()
        for label, mode in [
            ("Gerilmesiz / ağırlıksız", "none"),
            ("Ağırlık çözümü", "gravity"),
            ("K₀ alanı", "k0_field"),
            ("Sabit gerilme alanı", "field"),
        ]:
            self.mode.addItem(label, mode)
        self.mode.setCurrentIndex(self.mode.findData(init.mode))
        form.addRow("Yöntem", self.mode)
        self.k0 = QLineEdit("" if init.k0 is None else str(init.k0))
        self.surface = QLineEdit("" if init.surface_y is None else str(init.surface_y))
        form.addRow("K₀ (boş=malzemeden)", self.k0)
        form.addRow("Yüzey y (m; boş=ağın üstü)", self.surface)
        self.stress = []
        for label, value in zip(["σxx", "σyy", "σzz", "τxy"], init.field or (0, 0, 0, 0)):
            edit = QLineEdit(str(value))
            self.stress.append(edit)
            form.addRow(f"{label} (kPa; basınç negatif)", edit)
        self.gravity = QCheckBox("Sabit alan ile öz ağırlık")
        self.gravity.setChecked(init.gravity)
        form.addRow(self.gravity)
        self.regions = QLineEdit(regions_text(init.active_regions))
        self.structures = QLineEdit(
            "auto" if init.active_structures is None else ",".join(sorted(init.active_structures))
        )
        form.addRow("Aktif bölgeler (boş=tümü; -=hiçbiri)", self.regions)
        form.addRow("Aktif yapılar (boş=hiçbiri; auto=ara yüzler)", self.structures)
        layout.addLayout(form)
        note = QLabel(
            "K₀ alanı yatay tabakalanma içindir. Sabit alan dengeli bir sınır "
            "tanımı gerektirir. Yapı adları: " + (", ".join(model.structure_tags()) or "—")
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        self.water = WaterEditor(model.mesh, init.water)
        tabs.addTab(pane, "Gerilme ve aktivasyon")
        tabs.addTab(self.water, "Başlangıç suyu")
        self.root.addWidget(tabs)
        self.mode.currentIndexChanged.connect(self.update_enabled)
        self.update_enabled()
        self.finish_layout(self.apply)

    def update_enabled(self):
        mode = self.mode.currentData()
        self.k0.setEnabled(mode == "k0_field")
        self.surface.setEnabled(mode == "k0_field")
        for edit in [*self.stress, self.gravity]:
            edit.setEnabled(mode == "field")

    def apply(self):
        try:
            mode = self.mode.currentData()
            initial = replace(
                self.model.initial,
                mode=mode,
                k0=float(self.k0.text()) if self.k0.text().strip() else None,
                surface_y=float(self.surface.text()) if self.surface.text().strip() else None,
                field=tuple(float(w.text()) for w in self.stress) if mode == "field" else None,
                gravity=self.gravity.isChecked(),
                active_regions=parse_regions(self.regions.text()),
                active_structures=None
                if self.structures.text().strip() == "auto"
                else parse_tags(self.structures.text()),
                water=self.water.value(),
            )
            validate_edit(replace(self.model, initial=initial))
            self.updated = initial
        except Exception as exc:
            self.error(exc)
            return
        self.accept()


class StageDialog(EditorDialog):
    def __init__(self, model, parent=None):
        super().__init__("Aşama yöneticisi", parent)
        self.model = model
        self.items = list(model.stages)
        self.resize(1080, 580)
        note = QLabel(
            "Sıra yukarıdan aşağıya. λ, kalan değişimin serbest bırakılan payıdır: "
            "0.4 ardından 0.5 → toplam %70.\n"
            "Bölgeler: boş=tümü, -=hiçbiri. Yapılar: virgülle etiketler; boş=hiçbiri. "
            "Kopyalama tüm yük/su/atamaları taşır."
        )
        note.setWordWrap(True)
        self.root.addWidget(note)
        self.table = table(
            ["Ad", "Kalanın λ payı", "Drenajlı", "Aktif bölgeler", "Aktif yapılar", "u sıfırla"]
        )
        self.root.addWidget(self.table)
        toolbar(
            self.root,
            [
                ("Ekle", self.add_stage),
                ("Kopyala", self.copy_stage),
                ("Sil", self.delete_stage),
                ("↑ Yukarı", lambda: self.move_stage(-1)),
                ("↓ Aşağı", lambda: self.move_stage(1)),
                ("Yük / su / malzeme", self.edit_detail),
                ("Başlangıç", self.edit_initial),
            ],
        )
        self.root.addWidget(
            QLabel("Mevcut yapı etiketleri: " + (", ".join(model.structure_tags()) or "—"))
        )
        self.refresh()
        self.finish_layout(self.apply)

    def refresh(self, selected=0):
        self.table.setRowCount(len(self.items))
        for i, stage in enumerate(self.items):
            values = [
                stage.name,
                str(stage.load_split),
                "",
                regions_text(stage.active_regions),
                ",".join(sorted(stage.active_structures)),
                "",
            ]
            for j, value in enumerate(values):
                self.table.setItem(i, j, QTableWidgetItem(value))
            for j, value in [(2, stage.drained), (5, stage.reset_displacements)]:
                item = self.table.item(i, j)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if value else Qt.CheckState.Unchecked)
        if self.items:
            self.table.selectRow(min(max(0, selected), len(self.items) - 1))

    def read_stages(self):
        return [
            replace(
                s,
                name=self.table.item(i, 0).text().strip(),
                load_split=float(self.table.item(i, 1).text()),
                drained=self.table.item(i, 2).checkState() == Qt.CheckState.Checked,
                active_regions=parse_regions(self.table.item(i, 3).text()),
                active_structures=parse_tags(self.table.item(i, 4).text()),
                reset_displacements=self.table.item(i, 5).checkState() == Qt.CheckState.Checked,
            )
            for i, s in enumerate(self.items)
        ]

    def sync(self):
        try:
            items = self.read_stages()
            validate_edit(replace(self.model, stages=items))
            self.items = items
            self.status.clear()
            return True
        except Exception as exc:
            self.error(exc)
            return False

    def unique_name(self, base):
        names = {s.name for s in self.items}
        candidate, i = base, 1
        while candidate in names:
            candidate = f"{base} ({i})"
            i += 1
        return candidate

    def add_stage(self):
        if self.sync():
            self.items.append(api.Stage(self.unique_name("Yeni aşama")))
            self.refresh(len(self.items) - 1)

    def copy_stage(self):
        i = self.table.currentRow()
        if i >= 0 and self.sync():
            self.items.insert(
                i + 1, replace(self.items[i], name=self.unique_name(self.items[i].name))
            )
            self.refresh(i + 1)

    def delete_stage(self):
        i = self.table.currentRow()
        if i >= 0 and self.sync():
            self.items.pop(i)
            self.refresh(i)

    def move_stage(self, step):
        i = self.table.currentRow()
        if 0 <= i + step < len(self.items) and i >= 0 and self.sync():
            self.items[i], self.items[i + step] = self.items[i + step], self.items[i]
            self.refresh(i + step)

    def edit_detail(self):
        i = self.table.currentRow()
        if i >= 0 and self.sync():
            dialog = StageDetailDialog(replace(self.model, stages=self.items), i, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.items[i] = dialog.updated
                self.refresh(i)

    def edit_initial(self):
        if self.sync():
            dialog = InitialDialog(replace(self.model, stages=self.items), self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.model = replace(self.model, initial=dialog.updated)

    def apply(self):
        if self.sync():
            self.updated = replace(self.model, stages=list(self.items))
            self.accept()

"""Transactional initial-state and ordered construction-stage editors."""

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import api
from .boundary_editor import DisplacementEditor
from .condition_editor import LoadEditor, WaterEditor
from .editing import (
    parse_regions,
    parse_tags,
    region_label,
    regions_text,
    structure_label,
    validate_edit,
)
from .form_helpers import EditorDialog, table, toolbar
from .timeline import StageTimeline


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
        self.displacements = DisplacementEditor(model.mesh, stage.displacements)
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
        tabs.addTab(self.displacements, "Yer değiştirme")
        self.root.addWidget(tabs)
        self.finish_layout(self.apply)

    def apply(self):
        try:
            stage = replace(
                self.model.stages[self.index],
                loads=self.loads.values(),
                displacements=self.displacements.values(),
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
        super().__init__("Aşama yöneticisi (RS2 tarzı kazı ve destek ataması)", parent)
        self.model = model
        self.items = list(model.stages)
        self.all_regions = sorted(model.mesh.regions())
        self.all_structures = list(model.structure_tags())
        self._panel_updating = False
        self.resize(1180, 660)
        note = QLabel(
            "Sol tablodan aşamayı seçin; sağdaki RS2 panelinden her bölge için "
            "'Kazıldı (Boş)' veya malzeme seçin, destekleri (kazık/kaplama/ankraj) işaretleyin.\n"
            "λ, kalan değişimin serbest bırakılan payıdır (0.4 ardından 0.5 → toplam %70)."
        )
        note.setWordWrap(True)
        self.root.addWidget(note)

        init_bar = QHBoxLayout()
        init_bar.addWidget(QLabel("Başlangıç durumu:"))
        self.initial_mode = QComboBox()
        for label, mode in [
            ("Gerilmesiz / ağırlıksız", "none"),
            ("Ağırlık çözümü (Gravity)", "gravity"),
            ("K₀ alanı (In-Situ)", "k0_field"),
            ("Sabit gerilme alanı", "field"),
        ]:
            self.initial_mode.addItem(label, mode)
        self.initial_mode.setCurrentIndex(self.initial_mode.findData(model.initial.mode))
        self.initial_mode.currentIndexChanged.connect(self._on_initial_mode_changed)
        init_bar.addWidget(self.initial_mode)
        init_btn = QPushButton("Başlangıç ayrıntıları…")
        init_btn.clicked.connect(self.edit_initial)
        init_bar.addWidget(init_btn)
        init_bar.addStretch(1)
        self.propagate_check = QCheckBox("Değişiklikleri sonraki aşamalara da yay (RS2 tarzı)")
        self.propagate_check.setChecked(True)
        init_bar.addWidget(self.propagate_check)
        self.root.addLayout(init_bar)

        split = QSplitter(Qt.Orientation.Horizontal)
        left_pane = QWidget()
        left_layout = QVBoxLayout(left_pane)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.table = table(
            ["Ad", "Kalanın λ payı", "Drenajlı", "Aktif bölgeler", "Aktif yapılar", "u sıfırla"]
        )
        left_layout.addWidget(self.table, 1)
        toolbar(
            left_layout,
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
        split.addWidget(left_pane)

        right_pane = QWidget()
        right_layout = QVBoxLayout(right_pane)
        right_layout.setContentsMargins(6, 0, 0, 0)
        self.stage_header = QLabel("SEÇİLİ AŞAMA: —")
        self.stage_header.setStyleSheet("font-weight:bold; color:#124d70;")
        right_layout.addWidget(self.stage_header)

        right_layout.addWidget(QLabel("Bölgeler (Kazı / Malzeme durumu):"))
        self.region_table = table(["Bölge", "Durum / Malzeme"])
        self.region_table.setRowCount(len(self.all_regions))
        for idx, r in enumerate(self.all_regions):
            r_item = QTableWidgetItem(region_label(model, r))
            r_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.region_table.setItem(idx, 0, r_item)
            combo = QComboBox()
            base_mat = model.region_material[r]
            combo.addItem(f"🧱 Aktif — Temel ({base_mat})", "__base__")
            for m_name in model.materials:
                if m_name != base_mat:
                    combo.addItem(f"🧱 Aktif — {m_name}", m_name)
            combo.addItem("⛏️ Kazıldı (Boşaltıldı)", "__excavated__")
            combo.currentIndexChanged.connect(
                lambda _=0, reg=r, cb=combo: self._on_region_combo_changed(reg, cb.currentData())
            )
            self.region_table.setCellWidget(idx, 1, combo)
        right_layout.addWidget(self.region_table, 1)

        reg_btns = QHBoxLayout()
        exc_btn = QPushButton("⛏️ Seçili bölgeyi kaz")
        exc_btn.clicked.connect(self.excavate_selected_region)
        restore_btn = QPushButton("↩️ Tüm bölgeleri aktif yap")
        restore_btn.clicked.connect(self.restore_all_regions)
        reg_btns.addWidget(exc_btn)
        reg_btns.addWidget(restore_btn)
        right_layout.addLayout(reg_btns)

        right_layout.addWidget(
            QLabel("Destekler / Yapılar (" + (", ".join(self.all_structures) or "yok") + "):")
        )
        self.structure_table = table(["Destek / Yapı", "Bu aşamada etkin"])
        self.structure_table.setRowCount(len(self.all_structures))
        for idx, tag in enumerate(self.all_structures):
            s_item = QTableWidgetItem(f"{structure_label(model, tag)} [{tag}]")
            s_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.structure_table.setItem(idx, 0, s_item)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            chk.setCheckState(Qt.CheckState.Unchecked)
            self.structure_table.setItem(idx, 1, chk)
        self.structure_table.itemChanged.connect(self._on_structure_item_changed)
        right_layout.addWidget(self.structure_table, 1)

        split.addWidget(right_pane)
        split.setSizes([660, 480])
        self.root.addWidget(split, 1)

        self.timeline = StageTimeline()
        self.timeline.selected.connect(
            lambda i: self.table.selectRow(i - 1) if i else self.edit_initial()
        )
        self.root.addWidget(self.timeline)
        self.refresh()
        self.table.itemChanged.connect(self.update_timeline)
        self.table.itemSelectionChanged.connect(self._load_selected_stage_panel)
        self.finish_layout(self.apply)

    def _on_initial_mode_changed(self, *_):
        mode = self.initial_mode.currentData()
        if mode and mode != self.model.initial.mode:
            if mode == "field" and self.model.initial.field is None:
                self.model = replace(
                    self.model,
                    initial=replace(self.model.initial, mode=mode, field=(0.0, 0.0, 0.0, 0.0)),
                )
            else:
                self.model = replace(self.model, initial=replace(self.model.initial, mode=mode))
            self.update_timeline()

    def _load_selected_stage_panel(self):
        row = self.table.currentRow()
        if self._panel_updating:
            return
        self._panel_updating = True
        try:
            try:
                stages = self.read_stages()
            except Exception:
                stages = self.items
            if not (0 <= row < len(stages)):
                self.stage_header.setText("SEÇİLİ AŞAMA: —")
                return
            st = stages[row]
            self.stage_header.setText(f"SEÇİLİ AŞAMA ({row + 1}/{len(stages)}): {st.name}")
            active_regs = (
                set(self.all_regions) if st.active_regions is None else set(st.active_regions)
            )
            for idx, r in enumerate(self.all_regions):
                cb = self.region_table.cellWidget(idx, 1)
                if cb is None:
                    continue
                cb.blockSignals(True)
                if r not in active_regs:
                    target = "__excavated__"
                elif (
                    r in st.material_override
                    and st.material_override[r] != self.model.region_material[r]
                ):
                    target = st.material_override[r]
                else:
                    target = "__base__"
                pos = cb.findData(target)
                cb.setCurrentIndex(max(0, pos))
                cb.blockSignals(False)
            self.structure_table.blockSignals(True)
            for idx, tag in enumerate(self.all_structures):
                item = self.structure_table.item(idx, 1)
                if item is not None:
                    item.setCheckState(
                        Qt.CheckState.Checked
                        if tag in st.active_structures
                        else Qt.CheckState.Unchecked
                    )
            self.structure_table.blockSignals(False)
        finally:
            self._panel_updating = False

    def _on_region_combo_changed(self, region: int, data):
        if self._panel_updating:
            return
        row = self.table.currentRow()
        if row < 0 or not self.sync():
            return
        all_set = frozenset(self.all_regions)
        indices = range(row, len(self.items)) if self.propagate_check.isChecked() else (row,)
        for i in indices:
            st = self.items[i]
            cur = set(all_set if st.active_regions is None else st.active_regions)
            overrides = dict(st.material_override)
            if data == "__excavated__":
                cur.discard(region)
            else:
                cur.add(region)
                if data == "__base__" or data == self.model.region_material[region]:
                    overrides.pop(region, None)
                else:
                    overrides[region] = data
            active_val = None if cur == all_set else frozenset(cur)
            self.items[i] = replace(st, active_regions=active_val, material_override=overrides)
        self.refresh(row)

    def excavate_selected_region(self):
        r_row = self.region_table.currentRow()
        if 0 <= r_row < len(self.all_regions):
            cb = self.region_table.cellWidget(r_row, 1)
            if cb is not None:
                cb.setCurrentIndex(cb.findData("__excavated__"))

    def restore_all_regions(self):
        row = self.table.currentRow()
        if row < 0 or not self.sync():
            return
        indices = range(row, len(self.items)) if self.propagate_check.isChecked() else (row,)
        for i in indices:
            self.items[i] = replace(self.items[i], active_regions=None)
        self.refresh(row)

    def _on_structure_item_changed(self, item):
        if self._panel_updating or item.column() != 1:
            return
        row = self.table.currentRow()
        s_row = item.row()
        if row < 0 or not (0 <= s_row < len(self.all_structures)) or not self.sync():
            return
        tag = self.all_structures[s_row]
        checked = item.checkState() == Qt.CheckState.Checked
        indices = range(row, len(self.items)) if self.propagate_check.isChecked() else (row,)
        for i in indices:
            st = self.items[i]
            cur = set(st.active_structures)
            if checked:
                cur.add(tag)
            else:
                cur.discard(tag)
            self.items[i] = replace(st, active_structures=frozenset(cur))
        self.refresh(row)

    def update_timeline(self, *_):
        try:
            self.timeline.set_stages(self.read_stages(), self.model.initial)
            self._load_selected_stage_panel()
        except (ValueError, AttributeError):
            pass  # incomplete table edits remain editable until Apply

    def refresh(self, selected=0):
        self.table.blockSignals(True)
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

        self.table.blockSignals(False)
        self.update_timeline()

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
            if self.items:
                prev = self.items[-1]
                new_st = replace(
                    prev,
                    name=self.unique_name("Yeni aşama"),
                    load_split=1.0,
                    reset_displacements=False,
                )
            else:
                new_st = api.Stage(self.unique_name("Yeni aşama"))
            self.items.append(new_st)
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
                self.initial_mode.blockSignals(True)
                self.initial_mode.setCurrentIndex(self.initial_mode.findData(self.model.initial.mode))
                self.initial_mode.blockSignals(False)
                self.update_timeline()

    def apply(self):
        if self.sync():
            self.updated = replace(self.model, stages=list(self.items))
            self.accept()

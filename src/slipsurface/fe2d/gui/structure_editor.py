"""Native liner and bolt authoring on named mesh edges or existing end nodes."""

from dataclasses import replace

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QSpinBox,
)

from .. import api
from .editing import put_interface, put_structure, remove_interface, remove_structure, validate_edit
from .form_helpers import EditorDialog, toolbar


class StructureSpecDialog(EditorDialog):
    def __init__(self, model, tag=None, parent=None):
        super().__init__("Yapı özellikleri", parent)
        self.model, self.tag = model, tag
        self.resize(620, 600)
        form = QFormLayout()
        self.name = QLineEdit(tag or "Yeni yapı")
        self.name.setEnabled(tag is None)
        self.kind = QComboBox()
        self.kind.addItems(["Liner / kiriş", "Tam bağlı bolt", "Uçtan ankrajlı bolt"])
        spec = model.liners.get(tag) or model.bolts.get(tag)
        self.original = spec
        if isinstance(spec, api.BoltSpec):
            self.kind.setCurrentIndex(1)
            self.kind.setItemText(1, "Bolt (mevcut bağlantı)")
        self.kind.setEnabled(tag is None)
        form.addRow("Etiket", self.name)
        form.addRow("Tür", self.kind)
        self.edge = QComboBox()
        self.edge.addItems(sorted(model.mesh.edge_sets))
        form.addRow("Mevcut kenar kümesi", self.edge)
        self.nodes = []
        for label in ["İlk uç düğümü", "İkinci uç düğümü"]:
            node = QSpinBox()
            node.setRange(0, model.mesh.nn - 1)
            self.nodes.append(node)
            form.addRow(label, node)
        if model.mesh.nn > 1:
            self.nodes[1].setValue(1)
        self.root.addLayout(form)
        self.properties = QFormLayout()
        self.root.addLayout(self.properties)
        self.fields = {}
        self.kind.currentIndexChanged.connect(self.populate)
        self.populate()
        note = QLabel(
            "Liner: kesit bir metre düzlem dışı genişlik içindir. "
            "Bolt: EA ve akma kuvveti tek bolt içindir; aralık ile 2B eşdeğerlenir. "
            "Akma üstü öngerme motor tarafından akma kuvvetine kesilir. "
            "Yeni yapı başlangıçta ve aşamalarda pasiftir; Aşamalar'da etkinleştirin. "
            "Özellik düzenlemesi mevcut bağlantıyı korur."
        )
        note.setWordWrap(True)
        self.root.addWidget(note)
        self.finish_layout(self.apply)

    def populate(self):
        while self.properties.rowCount():
            self.properties.removeRow(0)
        self.fields.clear()
        liner = self.kind.currentIndex() == 0
        self.edge.setEnabled(self.tag is None and self.kind.currentIndex() != 2)
        for node in self.nodes:
            node.setEnabled(self.tag is None and self.kind.currentIndex() == 2)
        defaults = (
            [
                ("E", "E (kPa)", 3e7),
                ("nu", "ν", 0.2),
                ("A", "A (m²/m)", 0.2),
                ("I", "I (m⁴/m)", 0.2**3 / 12),
                ("As", "As (m²/m)", 0.2 * 5 / 6),
                ("unit_weight", "γ (kN/m³)", 24),
            ]
            if liner
            else [
                ("EA", "EA (kN)", 200000),
                ("T_yield", "Akma kuvveti (kN)", 200),
                ("pretension", "Öngerme (kN)", 0),
                ("spacing_out_of_plane", "Düzlem dışı aralık (m)", 1),
            ]
        )
        for key, label, value in defaults:
            edit = QLineEdit(str(getattr(self.original, key, value)))
            self.fields[key] = edit
            self.properties.addRow(label, edit)

    def apply(self):
        try:
            values = {k: float(w.text()) for k, w in self.fields.items()}
            cls = api.LinerSpec if self.kind.currentIndex() == 0 else api.BoltSpec
            spec = (
                replace(self.original, **values)
                if self.original
                else cls(self.name.text().strip(), **values)
            )
            if self.tag is not None:
                key = "liners" if isinstance(spec, api.LinerSpec) else "bolts"
                result = replace(self.model, **{key: {**getattr(self.model, key), self.tag: spec}})
                self.updated = validate_edit(result)
            else:
                nodes = (
                    tuple(w.value() for w in self.nodes) if self.kind.currentIndex() == 2 else None
                )
                self.updated = put_structure(
                    self.model, spec, edge_set=self.edge.currentText(), nodes=nodes
                )
        except Exception as exc:
            self.error(exc)
            return
        self.accept()


class StructureDialog(EditorDialog):
    def __init__(self, model, parent=None):
        super().__init__("Yapı elemanları", parent)
        self.model = model
        self.resize(760, 440)
        note = QLabel(
            "Liner, bolt ve ara yüzler. Kenar adları CAD çiziminden veya mevcut ağdan gelir. "
            "Ara yüz silme eş düğümleri birleştirir; başlangıç auto ise yeni ara yüz aktiftir."
        )
        note.setWordWrap(True)
        self.root.addWidget(note)
        self.list = QListWidget()
        self.root.addWidget(self.list)
        toolbar(
            self.root,
            [
                ("Liner / bolt ekle", self.add_structure),
                ("Ara yüz ekle", self.add_interface),
                ("Özellikler", self.edit_structure),
                ("Sil", self.delete_structure),
            ],
        )
        self.list.itemDoubleClicked.connect(self.edit_structure)
        self.refresh()
        self.finish_layout(self.apply)

    def refresh(self):
        self.tags = list(self.model.structure_tags())
        self.list.clear()
        for tag, kind in self.model.structure_tags().items():
            self.list.addItem(f"{tag} · {kind} · {self.model.mesh.block(tag).ne} eleman")
        if self.tags:
            self.list.setCurrentRow(0)

    def selected(self):
        i = self.list.currentRow()
        return self.tags[i] if i >= 0 else None

    def add_structure(self):
        dialog = StructureSpecDialog(self.model, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.model = dialog.updated
            self.refresh()

    def add_interface(self):
        dialog = InterfaceDialog(self.model, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.model = dialog.updated
            self.refresh()

    def edit_structure(self, *_):
        tag = self.selected()
        if tag is None:
            return
        cls = (
            InterfaceDialog
            if self.model.structure_tags()[tag] == "interface"
            else StructureSpecDialog
        )
        dialog = cls(self.model, tag, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.model = dialog.updated
            self.refresh()

    def delete_structure(self):
        tag = self.selected()
        if tag is not None:
            try:
                operation = (
                    remove_interface
                    if self.model.structure_tags()[tag] == "interface"
                    else remove_structure
                )
                self.model = operation(self.model, tag)
                self.refresh()
            except Exception as exc:
                self.error(exc)

    def apply(self):
        try:
            self.updated = validate_edit(self.model)
        except Exception as exc:
            self.error(exc)
            return
        self.accept()


class InterfaceDialog(EditorDialog):
    def __init__(self, model, tag=None, parent=None):
        super().__init__("Ara yüz", parent)
        self.model, self.tag = model, tag
        self.resize(640, 530)
        form = QFormLayout()
        self.name = QLineEdit(tag or "joint")
        self.name.setEnabled(tag is None)
        self.edge, self.side = QComboBox(), QComboBox()
        self.edge.addItems(sorted(model.mesh.edge_sets))
        self.side.addItems(["left", "right"])
        self.edge.setEnabled(tag is None)
        self.side.setEnabled(tag is None)
        form.addRow("Etiket", self.name)
        form.addRow("Kenar kümesi", self.edge)
        form.addRow("Düğümleri ayrılacak taraf", self.side)
        self.fields = {}
        spec = model.interfaces.get(tag)
        for key, title, default in [
            ("kn", "kn (kPa/m)", 1e6),
            ("ks", "ks (kPa/m)", 1e5),
            ("c", "c (kPa)", 0),
            ("phi", "φ (°)", 20),
            ("psi", "ψ (°)", 0),
            ("sig_t", "Çekme sınırı (kPa)", 0),
        ]:
            edit = QLineEdit(str(getattr(spec, key, default)))
            self.fields[key] = edit
            form.addRow(title, edit)
        self.root.addLayout(form)
        note = QLabel(
            "Sol/sağ, CAD çizgisinin giriş yönüne göredir. Ara yüz eklemek düğüm "
            "topolojisini değiştirir. Önce liner, ardından ara yüzleri, en son boltları "
            "kurun. Pasif ara yüzün iki yüzü mekanik olarak bağlanır. Sonuçlar silinir."
        )
        note.setWordWrap(True)
        self.root.addWidget(note)
        self.finish_layout(self.apply)

    def apply(self):
        try:
            spec = api.InterfaceSpec(
                self.name.text().strip(), **{k: float(w.text()) for k, w in self.fields.items()}
            )
            self.updated = (
                validate_edit(
                    replace(self.model, interfaces={**self.model.interfaces, self.tag: spec})
                )
                if self.tag
                else put_interface(
                    self.model, spec, self.edge.currentText(), self.side.currentText()
                )
            )
        except Exception as exc:
            self.error(exc)
            return
        self.accept()

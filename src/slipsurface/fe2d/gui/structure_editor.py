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
from .editing import put_structure, remove_interface, remove_structure, validate_edit
from .form_helpers import EditorDialog, toolbar
from .interface_authoring import (
    GOODMAN_FIELDS,
    NORMAL_FIELDS,
    apply_interface_spec,
    interface_spec_from_fields,
)


class StructureSpecDialog(EditorDialog):
    def __init__(self, model, tag=None, parent=None):
        super().__init__("Structure properties", parent)
        self.model, self.tag = model, tag
        self.resize(620, 600)
        form = QFormLayout()
        self.name = QLineEdit(tag or "New structure")
        self.name.setEnabled(tag is None)
        self.kind = QComboBox()
        self.kind.addItems(["Liner / beam", "Fully bonded bolt", "End-anchored bolt"])
        spec = model.liners.get(tag) or model.bolts.get(tag)
        self.original = spec
        if isinstance(spec, api.BoltSpec):
            self.kind.setCurrentIndex(1)
            self.kind.setItemText(1, "Bolt (existing connection)")
        self.kind.setEnabled(tag is None)
        form.addRow("Tag", self.name)
        form.addRow("Type", self.kind)
        self.edge = QComboBox()
        self.edge.addItems(sorted(model.mesh.edge_sets))
        form.addRow("Existing edge set", self.edge)
        self.nodes = []
        for label in ["First end node", "Second end node"]:
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
            "Liner: the section is for one metre of out-of-plane width. "
            "Bolt: EA and the yield force are for one bolt; spacing smears them to 2D. "
            "Pretension above yield is clipped to the yield force by the solver. "
            "A new structure is inactive in the initial state and in stages; activate it "
            "under Stages. Editing properties keeps the existing connection."
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
                ("T_yield", "Yield force (kN)", 200),
                ("pretension", "Pretension (kN)", 0),
                ("spacing_out_of_plane", "Out-of-plane spacing (m)", 1),
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
        super().__init__("Structural elements", parent)
        self.model = model
        self.resize(760, 440)
        note = QLabel(
            "Liners, bolts and interfaces. Edge names come from the CAD drawing or the "
            "current mesh. Deleting an interface welds coincident nodes; if the initial "
            "policy is auto, a new interface is active. Inactive Goodman joints are tied; "
            "inactive unilateral normal contacts are not."
        )
        note.setWordWrap(True)
        self.root.addWidget(note)
        self.list = QListWidget()
        self.root.addWidget(self.list)
        toolbar(
            self.root,
            [
                ("Add liner / bolt", self.add_structure),
                ("Add interface", self.add_interface),
                ("Properties", self.edit_structure),
                ("Delete", self.delete_structure),
            ],
        )
        self.list.itemDoubleClicked.connect(self.edit_structure)
        self.refresh()
        self.finish_layout(self.apply)

    def refresh(self):
        self.tags = list(self.model.structure_tags())
        self.list.clear()
        for tag, kind in self.model.structure_tags().items():
            law = f" · {self.model.interfaces[tag].law}" if kind == "interface" else ""
            self.list.addItem(f"{tag} · {kind}{law} · {self.model.mesh.block(tag).ne} elements")
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
        kind = self.model.structure_tags()[tag]
        if kind == "bond":
            self.error(ValueError(
                "Embedded tieback bond-transfer elements are read-only in this editor."
            ))
            return
        cls = InterfaceDialog if kind == "interface" else StructureSpecDialog
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
        super().__init__("Interface", parent)
        self.model, self.tag = model, tag
        self.resize(680, 680)
        form = QFormLayout()
        self.original = model.interfaces.get(tag)
        self.name = QLineEdit(self.original.name if self.original else "joint")
        self.name.setEnabled(tag is None)
        self.edge, self.side = QComboBox(), QComboBox()
        self.edge.addItems(sorted(model.mesh.edge_sets))
        self.side.addItems(["left", "right"])
        self.edge.setEnabled(tag is None)
        self.side.setEnabled(tag is None)
        form.addRow("Tag", self.name)
        form.addRow("Edge set", self.edge)
        form.addRow("Side whose nodes are duplicated", self.side)
        self.law = QComboBox()
        self.law.addItem("Goodman - elastoplastic joint", "goodman")
        self.law.addItem("Unilateral normal contact - dry, frictionless", "unilateral_normal")
        self.law.setCurrentIndex(self.law.findData(
            self.original.law if self.original else "goodman"))
        form.addRow("Interface law", self.law)
        self.fields = {}
        spec = self.original
        for key, title, default in [
            ("kn", "kn (kPa/m)", 1e6),
            ("ks", "ks (kPa/m)", 1e5),
            ("c", "c (kPa)", 0),
            ("phi", "φ (°)", 20),
            ("psi", "ψ (°)", 0),
            ("sig_t", "Tensile cutoff (kPa)", 0),
            ("initial_gap", "Initial clearance (m, opening positive)", 0),
        ]:
            edit = QLineEdit(str(getattr(spec, key, default)))
            self.fields[key] = edit
            form.addRow(title, edit)
        self.root.addLayout(form)
        self.law_note = QLabel()
        self.law_note.setWordWrap(True)
        self.root.addWidget(self.law_note)
        note = QLabel(
            "Left/right follows the directed CAD line. Adding an interface changes node "
            "topology. Install the liner first, interfaces next and bolts last. "
            "Property edits clear results; they do not transfer nonlinear contact history. "
            "Changing the law is an explicit model change, not a repair of old results."
        )
        note.setWordWrap(True)
        self.root.addWidget(note)
        self.law.currentIndexChanged.connect(self.update_law)
        self.update_law()
        self.finish_layout(self.apply)

    def update_law(self, *_):
        normal = self.law.currentData() == "unilateral_normal"
        active = NORMAL_FIELDS if normal else GOODMAN_FIELDS
        for key, edit in self.fields.items():
            edit.setEnabled(key in active)
        self.law_note.setText(
            "Unbonded normal-only penalty contact: positive gap carries zero force, "
            "closure carries compression, and shear is always zero. Inactive faces are "
            "NOT tied. Requires dry/drained plane strain, initial stress 'none', full "
            "Newton (NR), straight reference faces and no seismic loading or SRF. "
            "Provide real supports for open-body mechanisms. Disabled strength fields "
            "are ignored. Model settings will NOT be changed automatically."
            if normal else
            "Goodman elastoplastic joint: a tensile cutoff is not geometric gap "
            "opening/reclosure. Inactive Goodman faces are tied. Initial clearance "
            "is disabled and stored as zero. This remains the default for old models."
        )

    def apply(self):
        try:
            spec = interface_spec_from_fields(
                self.name.text(), self.law.currentData(),
                {key: edit.text() for key, edit in self.fields.items()},
                original=self.original,
            )
            self.updated = apply_interface_spec(
                self.model, spec, tag=self.tag,
                edge_set=self.edge.currentText(), side=self.side.currentText(),
            )
        except Exception as exc:
            self.error(exc)
            return
        self.accept()

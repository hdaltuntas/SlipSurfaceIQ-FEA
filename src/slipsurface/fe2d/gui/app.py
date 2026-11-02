"""SlipSurfaceIQ-FEA desktop shell, adapted from the SlipSurfaceIQ-LE modeler.

menu bar
workflow bar   Geometry › Supports › Fixity/load › Mesh › Materials › Stages › Solve › Results
               with a "next step" hint; finished steps are ticked
left dock      Document viewer (stages, model summary) + Display options
centre         result canvas + field selectors + solve log
status bar     hints, coordinates, SNAP / GRID / ORTHO toggles
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabBar,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import api
from ..core.errors import ModelError
from ..io.report import export_beam_csv, export_csv, export_html
from .boundary_editor import BoundaryDialog
from .canvas import MeshCanvas
from .dialogs import MaterialDialog, NewModelDialog
from .editing import (
    region_label,
    set_project_stages,
    set_region_stage_state,
    stage_active_structures,
    stage_region_material,
    structure_label,
)
from .icons import icon
from .structure_editor import StructureDialog
from .worker import SolveWorker
from .workflow import WorkflowBar

STEPS = [
    "Geometry",
    "Supports",
    "Fixity / load",
    "Mesh",
    "Materials",
    "Stages",
    "Solve",
    "Results",
]


class ModelFileError(ModelError):
    """A project/model file is not valid JSON — report the file, not just the parse."""

    def __init__(self, name: str, exc: json.JSONDecodeError) -> None:
        where = f"line {exc.lineno}, column {exc.colno}"
        super().__init__(
            f"'{name}' could not be read as JSON ({where}). "
            f"The file is not a SlipSurfaceIQ-FEA model (.ssproj / model JSON) "
            "or it is corrupt. Detail: " + str(exc)
        )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        from .preferences import apply_theme

        apply_theme()
        self.setWindowTitle("SlipSurfaceIQ-FEA · Desktop")
        self.resize(1280, 840)
        self.setIconSize(QSize(24, 24))
        self.model = self.result = None
        self.path = None
        self.worker = None
        self.dirty = False
        self._closing = False
        self._build_dock()
        self._actions()
        root = QWidget()
        layout = QVBoxLayout(root)
        self.workflow = WorkflowBar(STEPS)
        self.workflow.step_changed.connect(self._activate_step)
        self.guidance = QLabel()
        self.guidance.setObjectName("guidance")
        self.guidance.setStyleSheet("color:#124d70;padding:0 8px;font-weight:bold;")
        # Clip instead of widening the window on small screens; the tooltip keeps the text.
        self.guidance.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        # Full-width row above the dock, so the project panel never squeezes the steps.
        flow_bar = QToolBar("Workflow")
        flow_bar.setObjectName("workflow_bar")
        flow_bar.setMovable(False)
        flow = QWidget()
        flow_layout = QHBoxLayout(flow)
        flow_layout.setContentsMargins(4, 0, 4, 0)
        flow_layout.addWidget(self.workflow)
        flow_layout.addWidget(self.guidance, 1)
        flow_bar.addWidget(flow)
        self.addToolBarBreak()
        self.addToolBar(flow_bar)
        split = QSplitter(Qt.Orientation.Vertical)
        self.result_split = split
        view = QWidget()
        right = QVBoxLayout(view)
        from .statusbar import CadStatusBar

        self.status = CadStatusBar(self, shortcuts=False)
        self.setStatusBar(self.status)
        self.status.add_fit_button(self.fit_action)
        self.canvas = MeshCanvas()
        self.canvas.queried.connect(self.status.showMessage)
        self.canvas.mouse_world.connect(self.status.show_coords)
        self.canvas.region_clicked.connect(self._on_canvas_region_clicked)
        self.canvas.structure_clicked.connect(self._on_canvas_structure_clicked)
        self.canvas.context_menu_requested.connect(self._on_canvas_context_menu)
        right.addWidget(self.canvas, 1)
        self.stage_tabs = QTabBar()
        self.stage_tabs.setExpanding(False)
        self.stage_tabs.currentChanged.connect(self._on_stage_tab_changed)
        right.addWidget(self.stage_tabs)
        self.legend = QLabel("")
        self.legend.setWordWrap(True)
        self.legend.setStyleSheet("padding:8px;color:#526677")
        right.addWidget(self.legend)
        split.addWidget(view)
        self.result_page = QWidget()
        result_layout = QVBoxLayout(self.result_page)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.addWidget(split, 1)
        self.workspace = QStackedWidget()
        self.workspace.addWidget(self.result_page)
        from .cad import CadDialog

        self.cad = CadDialog(parent=self, embedded=True)
        self.cad.model_ready.connect(self._accept_cad_model)
        self.cad.worker_stopped.connect(self._cad_worker_stopped)
        self.cad.drawing_changed.connect(self._on_drawing_changed)
        self.cad.structure_requested.connect(self.show_structure_forces)
        self.cad.stage_menu_requested.connect(self._add_region_stage_action)
        self.model_stage_tabs = QTabBar()
        self.model_stage_tabs.setExpanding(False)
        self.model_stage_tabs.currentChanged.connect(self._on_stage_tab_changed)
        # Keep the schedule immediately beneath the model canvas/editor.
        self.cad.layout().insertWidget(2, self.model_stage_tabs)
        self.workspace.addWidget(self.cad)
        self.status.attach(self.cad.canvas)
        self.cad.canvas.mouse_world.connect(self.status.show_coords)
        for name, checkbox in [
            ("snap", self.cad.snap),
            ("grid", self.cad.grid_toggle),
            ("ortho", self.cad.ortho),
            ("osnap", self.cad.osnap),
        ]:
            toggle = self.status.toggles[name]
            checkbox.toggled.connect(toggle.setChecked)
            toggle.toggled.connect(checkbox.setChecked)
        layout.addWidget(self.workspace, 1)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Solve log")
        self.log_panel = self.log
        split.addWidget(self.log)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes([600, 150])
        split.setCollapsible(0, False)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        result_layout.addWidget(self.progress)
        self.setCentralWidget(root)
        self.status.showMessage("Ready · Units kN, m, kPa · Tension positive in stress")
        self._view_menu()
        self._restore_layout()
        self.set_model(None)

    def _build_dock(self):
        """Left dock: document viewer (stage list + summary) and display
        options (field, deformation scale, overlays) — LE modeler layout."""
        self.stages = QListWidget()
        self.stages.currentRowChanged.connect(self._on_stage_list_changed)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("padding:12px;line-height:1.4;color:#526677")
        self.fields = QComboBox()
        self.fields.addItems(
            [
                "|u|",
                "ux",
                "uy",
                "N",
                "V",
                "M",
                "sxx",
                "syy",
                "szz",
                "txy",
                "s1",
                "s3",
                "q",
                "plastic",
                "pore",
                "excess_pore",
            ]
        )
        self.fields.currentTextChanged.connect(self.draw)
        self.result_objects = QComboBox()
        self.result_objects.setMinimumContentsLength(18)
        self.result_objects.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.result_objects.addItem("Whole model", None)
        self.result_objects.currentIndexChanged.connect(self._on_result_object_changed)
        self.diagram_scale = QDoubleSpinBox()
        self.diagram_scale.setRange(0.05, 10.0)
        self.diagram_scale.setSingleStep(0.25)
        self.diagram_scale.setValue(1.0)
        self.diagram_scale.valueChanged.connect(self.draw)
        self.chart_button = QPushButton("Open element charts…")
        self.chart_button.clicked.connect(self.open_selected_charts)
        self.deform = QDoubleSpinBox()
        self.deform.setRange(0, 1e6)
        self.deform.setValue(1.0)
        self.deform.valueChanged.connect(self.draw)
        self.principal = QCheckBox("Principal arrows")
        self.plastic_points = QCheckBox("Plastic points")
        for checkbox in (self.principal, self.plastic_points):
            checkbox.toggled.connect(self.draw)
        reset = QPushButton("Restore defaults")
        reset.clicked.connect(self._reset_display)
        dock_split = QSplitter(Qt.Orientation.Vertical)
        left = QVBoxLayout()
        left.addWidget(QLabel("DOCUMENT VIEWER"))
        left.addWidget(self.stages, 1)
        left.addWidget(self.summary)
        viewer = QWidget()
        viewer.setLayout(left)
        right = QVBoxLayout()
        right.addWidget(QLabel("DISPLAY OPTIONS"))
        right.addWidget(QLabel("Model element"))
        right.addWidget(self.result_objects)
        row = QHBoxLayout()
        row.addWidget(QLabel("Field"))
        row.addWidget(self.fields, 1)
        right.addLayout(row)
        right.addWidget(self.chart_button)
        row = QHBoxLayout()
        row.addWidget(QLabel("Diagram ×"))
        row.addWidget(self.diagram_scale)
        right.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Deformation ×"))
        row.addWidget(self.deform)
        right.addLayout(row)
        right.addWidget(self.principal)
        right.addWidget(self.plastic_points)
        right.addStretch(1)
        right.addWidget(reset)
        options = QWidget()
        options.setLayout(right)
        dock_split.addWidget(viewer)
        dock_split.addWidget(options)
        dock_split.setSizes([420, 380])
        dock = QDockWidget("Proje", self)
        self.project_dock = dock
        dock.setObjectName("project_dock")
        dock.setWidget(dock_split)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        self.resizeDocks([dock], [290], Qt.Orientation.Horizontal)

    def _reset_display(self):
        self.result_objects.setCurrentIndex(0)
        self.diagram_scale.setValue(1.0)
        self.deform.setValue(1.0)
        self.principal.setChecked(False)
        self.plastic_points.setChecked(False)
        self.fields.setCurrentText("|u|")
        self.draw()

    def _activate_step(self, i):
        slot = (
            self.edit_geometry,
            self.edit_structures,
            self.edit_drawing_conditions,
            self.build_mesh,
            self.edit_materials,
            self.edit_stages,
            self.start_solve,
            self.show_results,
        )[i]
        slot()
        self._update_guidance()

    def step_state(self):
        """(finished step indices, next-step hint) from the drawing, model and results."""
        drawing = self.cad.current_drawing()
        done = set()
        regions = any(e.kind == "region" for e in drawing.entities)
        meshed = self.model is not None and not self.cad.mesh_outdated
        if regions or meshed:
            done.add(0)
        if drawing.supports or (meshed and self.model.structure_tags()):
            done.add(1)
        if any(r.ux or r.uy for r in drawing.rules) or (meshed and self.model.fixities):
            done.add(2)
        if meshed:
            done.update({3, 4, 5})
        if meshed and self.result is not None:
            done.update({6, 7})
        if self.worker is not None:
            hint = "Solve running · ■ Stop to cancel"
        elif 0 not in done:
            hint = "Next: draw a soil region from the Geometry menu"
        elif 2 not in done:
            hint = "Next: check ux/uy in the fixity / load table"
        elif 3 not in done:
            hint = "Next: generate the mesh (Ctrl+M)"
        elif 6 not in done:
            hint = "Next: check materials and stages, then Solve (F5)"
        else:
            hint = "Results ready · Inspect results / Export results menus"
        return done, hint

    def _update_guidance(self, *_):
        if not hasattr(self, "guidance"):
            return
        done, hint = self.step_state()
        self.workflow.set_done(done)
        self.guidance.setText(hint)
        self.guidance.setToolTip(hint)

    def _view_menu(self):
        menu = self.menuBar().addMenu("View")
        menu.addAction(self.fit_action)
        menu.addSeparator()
        # The dock is hidden by design while drawing; this is the results-view choice.
        self.dock_action = QAction("Project panel", self)
        self.dock_action.setCheckable(True)
        self.dock_action.setChecked(True)
        self.dock_action.toggled.connect(self._dock_toggled)
        menu.addAction(self.dock_action)
        self.log_action = QAction("Solve log panel", self)
        self.log_action.setCheckable(True)
        self.log_action.setChecked(True)
        self.log_action.toggled.connect(self.log_panel.setVisible)
        menu.addAction(self.log_action)
        menu.addSeparator()
        reset = QAction("Reset layout", self)
        reset.triggered.connect(self.reset_layout)
        menu.addAction(reset)

    def _dock_toggled(self, visible):
        if self.workspace.currentWidget() is self.result_page:
            self.project_dock.setVisible(visible)

    def reset_layout(self):
        self.log_action.setChecked(True)
        self.dock_action.setChecked(True)
        self.result_split.setSizes([600, 150])
        self.project_dock.setFloating(False)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.project_dock)
        if self.workspace.currentWidget() is self.result_page:
            self.project_dock.show()
        self.resizeDocks([self.project_dock], [290], Qt.Orientation.Horizontal)

    def _restore_layout(self):
        from .preferences import settings

        store = settings()
        geometry = store.value("main/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        state = store.value("main/state")
        if state is not None:
            self.restoreState(state)
        sizes = store.value("main/results")
        if sizes is not None:
            self.result_split.restoreState(sizes)
        self.log_action.setChecked(store.value("main/log", True, type=bool))
        self.dock_action.setChecked(store.value("main/dock", True, type=bool))
        self.project_dock.setVisible(
            self.workspace.currentWidget() is self.result_page and self.dock_action.isChecked()
        )

    def _save_layout(self):
        from .preferences import settings

        store = settings()
        store.setValue("main/geometry", self.saveGeometry())
        store.setValue("main/state", self.saveState())
        store.setValue("main/dock", self.dock_action.isChecked())
        store.setValue("main/results", self.result_split.saveState())
        store.setValue("main/log", self.log_action.isChecked())

    def _actions(self):
        toolbar = QToolBar("Workspace")
        toolbar.setObjectName("main_toolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self.edit_actions = []
        self.export_actions = []

        def action(title, slot, shortcut=None, ic=None):
            a = QAction(icon(ic), title, self) if ic else QAction(title, self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(shortcut)
            return a

        def add_icon(a):
            toolbar.addAction(a)
            button = toolbar.widgetForAction(a)
            if isinstance(button, QToolButton):
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
                button.setAutoRaise(True)
            return a

        file_menu = self.menuBar().addMenu("File")
        for title, slot, shortcut, ic in [
            ("New", self.new_model, "Ctrl+N", "new"),
            ("Open", self.open_dialog, "Ctrl+O", "open"),
            ("Save", self.save_dialog, "Ctrl+S", "save"),
        ]:
            a = action(title, slot, shortcut, ic)
            a.setToolTip(f"{title} ({shortcut})")
            add_icon(a)
            file_menu.addAction(a)
            self.edit_actions.append(a)
        file_menu.addAction(action("Parametric rectangle model…", self.new_mesh_model))
        for title, method in [
            ("Open drawing…", "open_drawing"),
            ("Save drawing…", "save_drawing"),
            ("Import DXF…", "import_dxf"),
            ("Export DXF…", "export_dxf"),
        ]:
            file_menu.addAction(
                action(title, lambda _=False, m=method: self.drawing_file_action(m))
            )
        file_menu.addSeparator()
        self.examples_menu = file_menu.addMenu("Examples")
        for title, slot in [
            ("Four-stage tunnel", self.open_tunnel_example),
            ("Staged excavation (sheet pile + anchor)", self.open_excavation_example),
            ("Two-layer strip footing", self.open_footing_example),
        ]:
            ex_action = action(title, slot)
            self.examples_menu.addAction(ex_action)
            self.edit_actions.append(ex_action)
        edit_menu = self.menuBar().addMenu("Edit")
        for title, method in [
            ("Undo", "undo"),
            ("Redo", "redo"),
            ("Delete selection", "delete_entity"),
        ]:
            edit_menu.addAction(
                action(title, lambda _=False, m=method: self.drawing_file_action(m))
            )
        # Modelling steps live in the numbered workflow bar; the toolbar keeps file/run.
        model_menu = self.menuBar().addMenu("Model")
        for title, slot in [
            ("Project properties…", self.edit_project_properties),
            ("Geometry / CAD", self.edit_geometry),
            ("Materials…", self.edit_materials),
            ("Structures (drawing)", self.edit_structures),
            ("Boundaries (mesh sets)…", self.edit_boundaries),
            ("Model Properties / Stages…", self.edit_project_properties),
        ]:
            a = action(title, slot)
            model_menu.addAction(a)
            self.edit_actions.append(a)
        toolbar.addSeparator()
        self.mesh_action = action("Generate mesh", self.build_mesh, "Ctrl+M", "mesh")
        self.mesh_action.setToolTip("Generate mesh (Ctrl+M)")
        add_icon(self.mesh_action)
        self.edit_actions.append(self.mesh_action)
        self.run_action = action("Solve", self.start_solve, "F5", "compute")
        self.run_action.setToolTip("Solve (F5)")
        self.stop_action = action("Stop", self.cancel_solve, ic="stop")
        self.stop_action.setToolTip("Stop")
        self.stop_action.setEnabled(False)
        add_icon(self.run_action)
        add_icon(self.stop_action)
        self.mesh_view_action = action("Mesh", self.show_results, "F6", "mesh_view")
        self.mesh_view_action.setToolTip("Mesh (F6)")
        self.results_action = action("Results", self.open_interpret, ic="results")
        self.results_action.setToolTip("Results")
        add_icon(self.mesh_view_action)
        add_icon(self.results_action)
        self.fit_action = action("Fit view", self.fit_active_view, "F2", "zoom_all")
        self.fit_action.setToolTip("Fit view (F2)")
        geometry_menu = self.menuBar().addMenu("Geometry")
        for title, kind in [
            ("Polygon region", "region"),
            ("Excavation / split line", "split"),
            ("Void", "hole"),
            ("Mesh constraint line", "line"),
        ]:
            geometry_menu.addAction(action(title, lambda _=False, k=kind: self.draft_tool(k)))
        support_menu = self.menuBar().addMenu("Support")
        for title, kind in [
            ("Draw pile", "pile"),
            ("Draw lining / beam", "liner"),
            ("Draw single bolt / anchor / soil nail", "bolt"),
        ]:
            support_menu.addAction(action(title, lambda _=False, k=kind: self.draft_tool(k)))
        support_menu.addSeparator()
        support_menu.addAction(
            action(
                "Bolt pattern (drag along boundary)…",
                lambda _=False: self.drawing_file_action("bolt_pattern"),
            )
        )
        support_menu.addSeparator()
        support_menu.addAction(
            action("Structure properties on the current mesh…", self.edit_mesh_structures)
        )
        tunnel_menu = self.menuBar().addMenu("Tunnel")
        tunnel_menu.addAction(action(
            "Tunnel Designer…",
            lambda _=False: self.drawing_file_action("open_tunnel_designer"),
        ))
        result_menu = self.menuBar().addMenu("Inspect results")
        result_menu.addAction(action("Open Interpret window…", self.open_interpret))
        result_menu.addAction(action("Open Interpret window…", self.open_interpret))
        for title, slot in [
            ("Query line", self.query_line),
            ("Liner N–V–M", self.beam_diagrams),
            ("Tunnel / pile displacement", self.structure_displacements),
        ]:
            a = action(title, slot)
            result_menu.addAction(a)
            self.export_actions.append(a)
        export_menu = self.menuBar().addMenu("Export results")
        for title, kind in [
            ("VTU / ParaView", "vtu"),
            ("Node CSV", "csv"),
            ("Beam N–V–M CSV", "beam"),
            ("HTML report", "html"),
        ]:
            a = action(title, lambda checked=False, k=kind: self.export_dialog(k), None, "export")
            export_menu.addAction(a)
            self.export_actions.append(a)

    def _sync_stage_tabs(self, selected_row: int):
        names = [self.stages.item(i).text() for i in range(self.stages.count())]
        for tabs in (self.stage_tabs, self.model_stage_tabs):
            tabs.blockSignals(True)
            while tabs.count():
                tabs.removeTab(0)
            for i, name in enumerate(names):
                tabs.addTab(f"{i}. {name}")
                tabs.setTabToolTip(i, name)
            tabs.setCurrentIndex(max(0, min(selected_row, tabs.count() - 1)))
            tabs.blockSignals(False)
        self._refresh_cad_stage()

    def _on_drawing_changed(self):
        if self.model is None and hasattr(self, "model_stage_tabs"):
            drawing = self.cad.current_drawing()
            names = (
                ["Initial", drawing.loading_name, *[s.name for s in drawing.sequence]]
                if drawing.entities or drawing.sequence or drawing.loading_name != "CAD loading"
                else []
            )
            row = max(0, min(self.stages.currentRow(), len(names) - 1))
            self.stages.blockSignals(True)
            self.stages.clear()
            self.stages.addItems(names)
            self.stages.setCurrentRow(row)
            self.stages.blockSignals(False)
            self._sync_stage_tabs(row)
        elif hasattr(self, "model_stage_tabs"):
            self._refresh_cad_stage()
        self._update_guidance()

    def _refresh_cad_stage(self):
        row = max(0, self.stages.currentRow())
        drawing = self.cad.current_drawing()
        materials = {}
        if self.model is not None and not self.cad.mesh_outdated:
            materials = {
                r: stage_region_material(self.model, row, r) for r in self.model.mesh.regions()
            }
            names = list(self.model.materials)
        else:
            from ..cad.material_assignment import material_specs, region_state, stage_names

            if self.model is not None:
                drawing = drawing.with_stage_names([s.name for s in self.model.stages])
            row = min(row, len(stage_names(drawing)) - 1)
            materials = {e.region: region_state(drawing, row, e, self.model)
                         for e in drawing.entities if e.kind == "region"}
            names = list(material_specs(drawing, self.model))
        colors = ("#65b4c8", "#e2b878", "#82c39b", "#b39ddb", "#e5989b", "#80cbc4")
        self.cad.canvas.stage_materials = materials
        self.cad.canvas.material_colors = {n: colors[i % len(colors)] for i, n in enumerate(names)}
        index = self.cad.entities.currentRow()
        selected = drawing.entities[index].name if 0 <= index < len(drawing.entities) else None
        self.cad.canvas.redraw(drawing.entities, self.cad.pending, selected)

    def _on_stage_list_changed(self, row: int):
        if hasattr(self, "model_stage_tabs"):
            for tabs in (self.stage_tabs, self.model_stage_tabs):
                tabs.blockSignals(True)
                tabs.setCurrentIndex(row)
                tabs.blockSignals(False)
            self._refresh_cad_stage()
        self.draw()

    def _on_stage_tab_changed(self, index: int):
        if 0 <= index < self.stages.count() and self.stages.currentRow() != index:
            self.stages.setCurrentRow(index)
        else:
            self.draw()

    def _on_canvas_region_clicked(self, region: int):
        if self.busy or self.model is None:
            return
        stage_idx = max(0, self.stages.currentRow())
        cur_mat = stage_region_material(self.model, stage_idx, region)
        state = f"material {cur_mat}" if cur_mat else "excavated in this stage"
        self.status.showMessage(
            f"{region_label(self.model, region)} · {state}. "
            "Click a lining, pile or anchor for section forces.",
            6000,
        )

    def _on_canvas_structure_clicked(self, tag: str):
        if self.busy or self.model is None:
            return
        self.show_structure_forces(tag)

    def _on_canvas_context_menu(self, region: int, struct_tag: str, global_pos):
        if self.busy or self.model is None:
            return
        stage_idx = max(0, self.stages.currentRow())
        menu = QMenu(self)
        if region > 0 and not struct_tag:
            self._add_region_stage_action(menu, region)
        if struct_tag:
            s_lbl = structure_label(self.model, struct_tag)
            active = struct_tag in stage_active_structures(self.model, stage_idx)
            forces = menu.addAction(f"Section forces (N–V–M): {s_lbl}")
            forces.setEnabled(
                self.result is not None
                and self.model.structure_tags().get(struct_tag) in {"beam", "bar"}
            )
            forces.triggered.connect(lambda _=False, t=struct_tag: self.show_structure_forces(t))
            if not active:
                note = menu.addAction("Not active in this stage; choose a stage after installation")
                note.setEnabled(False)
        menu.exec(global_pos)

    def _add_region_stage_action(self, menu, region):
        action = menu.addAction("Assign materials…")
        ready = not self.busy and (
            any(e.kind == "region" and e.region == region for e in self.cad.document.entities)
            or (self.model is not None and region in self.model.mesh.regions())
        )
        action.setEnabled(ready)
        action.setToolTip("Choose a material or Excavated (void) for the selected stage.")
        menu.setToolTipsVisible(True)
        action.triggered.connect(lambda _=False: self.edit_region_stage(region))

    def excavate_region(self, region, *, propagate=False):
        """Deactivate the picked region without deleting its geometry or material."""
        if self.busy or not self._require_model():
            return
        try:
            updated = set_region_stage_state(
                self.model, max(0, self.stages.currentRow()), region, None, propagate=propagate
            )
        except (ValueError, ModelError) as exc:
            QMessageBox.warning(self, "Excavation", str(exc))
            return
        self._apply_stage_edit(updated)

    def edit_region_stage(self, region):
        from .project_properties import DraftRegionStageDialog, RegionStageDialog

        if self.busy:
            return
        if self.model is None or self.cad.mesh_outdated:
            drawing = self.cad.current_drawing()
            if self.model is not None:
                drawing = drawing.with_stage_names([s.name for s in self.model.stages])
            entity = next((e for e in drawing.entities
                           if e.kind == "region" and e.region == region), None)
            if entity is None:
                return
            dialog = DraftRegionStageDialog(drawing, max(0, self.stages.currentRow()),
                                            entity, self.model, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.cad.commit(dialog.updated)
                self.result = None
                self.dirty = True
            return
        if not self._require_model():
            return
        dialog = RegionStageDialog(self.model, max(0, self.stages.currentRow()), region, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._apply_stage_edit(dialog.updated)

    def _apply_stage_edit(self, model):
        row = min(max(0, self.stages.currentRow()), len(model.stages))
        was_cad = self.workspace.currentWidget() is self.cad
        history = self.cad.undo_stack[:], self.cad.redo_stack[:]
        transform = self.cad.canvas.transform()
        center = self.cad.canvas.mapToScene(self.cad.canvas.viewport().rect().center())
        self.set_model(model, path=self.path, dirty=True)
        self.cad.undo_stack, self.cad.redo_stack = history
        self.stages.setCurrentRow(row)
        if was_cad:
            self.edit_geometry()
            self.cad.canvas.setTransform(transform)
            self.cad.canvas.centerOn(center)
        self.status.showMessage("Stage settings updated · Recalculate to view results.")

    def edit_project_properties(self):
        from .project_properties import ProjectPropertiesDialog

        if self.busy:
            return
        if self.model is not None and not self._require_model():
            return
        drawing = self.cad.current_drawing()
        names = (
            [s.name for s in self.model.stages]
            if self.model is not None
            else [drawing.loading_name, *[s.name for s in drawing.sequence]]
        )
        dialog = ProjectPropertiesDialog(names, self, model=self.model)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            if self.model is not None:
                edited = getattr(dialog, "updated_model", self.model)
                self._apply_stage_edit(set_project_stages(edited, dialog.updated))
            else:
                self.cad.commit(drawing.with_stage_names(dialog.updated))
        except Exception as exc:
            QMessageBox.warning(self, "Project properties", str(exc))

    @property
    def busy(self):
        return self.worker is not None or (hasattr(self, "cad") and self.cad.worker is not None)

    def set_model(self, model, result=None, path=None, dirty=False):
        if model is None:
            self._set_empty_state(path, dirty)
            return
        model.validate()
        self.cad.load_model(model)
        self.model, self.result, self.path, self.dirty = model, result, path, dirty
        self.show_results()
        self._sync_result_objects()
        selected_row = len(model.stages) if result else (1 if model.stages else 0)
        self.stages.blockSignals(True)
        self.stages.clear()
        self.stages.addItems(["Initial", *[s.name for s in model.stages]])
        self.stages.setCurrentRow(selected_row)
        self.stages.blockSignals(False)
        self._sync_stage_tabs(selected_row)
        self.summary.setText(
            f"{model.analysis.value}\n\n{model.mesh.nn} nodes\n"
            f"{sum(b.ne for b in model.mesh.blocks)} elements\n"
            f"{len(model.materials)} materials · {len(model.mesh.regions())} regions\n\n"
            "Results:\n"
            "· Pick a stage from the tabs below\n"
            "· Field: |u| / ux / uy or N / V / M\n"
            "· Click a structure for the section window · Node: double-click"
        )
        for a in self.export_actions:
            a.setEnabled(result is not None)
        self.setWindowTitle(
            f"SlipSurfaceIQ-FEA · {Path(path).name if path else 'New model'}"
            + (" *" if dirty else "")
        )
        if result is not None:
            self.progress.setValue(100)
        else:
            self.progress.setValue(0)
        self.draw()
        self._update_guidance()
        self.status.showMessage("Model ready · Units kN, m, kPa")

    def _set_empty_state(self, path=None, dirty=False):
        """No model yet: blank scene, clear stage list, hint at first steps."""
        self.model = self.result = None
        self._sync_result_objects()
        self.cad.load_model(None)
        self.edit_geometry()
        self.path = path
        self.dirty = dirty
        self.stages.blockSignals(True)
        self.stages.clear()
        self.stages.blockSignals(False)
        self._sync_stage_tabs(0)
        self.summary.setText(
            "Empty project.\n\nTo start:\n"
            "· File > New for a rectangular soil model\n"
            "· Geometry / CAD to mesh from a drawing\n"
            "· File > Open for an existing project"
        )
        for a in self.export_actions:
            a.setEnabled(False)
        self.setWindowTitle(f"SlipSurfaceIQ-FEA · {Path(path).name if path else 'Empty project'}")
        self.progress.setValue(0)
        self.canvas.scene().clear()
        self.canvas.model = self.canvas.stage = None
        self.legend.setText("")
        self._update_guidance()
        self.statusBar().showMessage(
            "Modeler · Start a drawing from the Geometry, Tunnel or Support menu"
        )

    def _require_model(self):
        if self.cad.mesh_outdated:
            self.edit_geometry()
            self.status.showMessage(
                "Drawing changed · Generate the mesh before updating the analysis model."
            )
            return False
        if self.model is None:
            self.status.showMessage(
                "No model · Start with File > New, Geometry / CAD, or File > Open", 8000
            )
            return False
        return True

    def selected_stage(self):
        if self.result is None:
            return None
        index = self.stages.currentRow()
        return self.result.initial if index <= 0 else self.result.stages[index - 1]

    def _sync_result_objects(self):
        previous = self.result_objects.currentData()
        self.result_objects.blockSignals(True)
        self.result_objects.clear()
        self.result_objects.addItem("Whole model", None)
        if self.model is not None:
            for region in sorted(self.model.mesh.regions()):
                self.result_objects.addItem(region_label(self.model, region), f"region:{region}")
            for tag in self.model.structure_tags():
                self.result_objects.addItem(structure_label(self.model, tag), f"structure:{tag}")
        self.result_objects.setCurrentIndex(max(0, self.result_objects.findData(previous)))
        self.result_objects.blockSignals(False)
        self._update_result_controls()

    def result_selection(self):
        key = self.result_objects.currentData()
        if key is None:
            return None
        kind, value = key.split(":", 1)
        return kind, int(value) if kind == "region" else value

    def _update_result_controls(self):
        selection = self.result_selection()
        kind = (
            self.model.structure_tags().get(selection[1])
            if self.model is not None and selection and selection[0] == "structure"
            else None
        )
        allowed = (
            {"|u|", "ux", "uy", "N", "V", "M"}
            if kind == "beam"
            else {"|u|", "ux", "uy", "N"}
            if kind == "bar"
            else {"|u|", "ux", "uy"}
            if kind == "interface"
            else None
        )
        self.fields.blockSignals(True)
        for i in range(self.fields.count()):
            name = self.fields.itemText(i)
            enabled = name in allowed if allowed is not None else name not in {"N", "V", "M"}
            self.fields.model().item(i).setEnabled(enabled)
        if not self.fields.model().item(self.fields.currentIndex()).isEnabled():
            self.fields.setCurrentText("|u|")
        self.fields.blockSignals(False)
        self.chart_button.setEnabled(self.result is not None and kind in {"beam", "bar"})
        self.diagram_scale.setEnabled(self.fields.currentText() in {"N", "V", "M"})

    def _on_result_object_changed(self, *_):
        self._update_result_controls()
        self.draw()

    def open_selected_charts(self):
        selection = self.result_selection()
        if selection and selection[0] == "structure":
            self.show_structure_forces(selection[1])

    def draw(self, *_):
        if self.model is None:
            return
        st = self.selected_stage()
        stage_idx = max(0, self.stages.currentRow())
        field = self.fields.currentText()
        section = field in ("N", "V", "M")
        selection = self.result_selection()
        if section and (not selection or selection[0] != "structure"):
            # Programmatic field changes also select a single compatible member.
            tags = self.model.structure_tags()
            tag = next(
                (t for t, k in tags.items() if k == "beam" or (k == "bar" and field == "N")), None
            )
            if tag is not None:
                self.result_objects.blockSignals(True)
                self.result_objects.setCurrentIndex(
                    self.result_objects.findData(f"structure:{tag}")
                )
                self.result_objects.blockSignals(False)
                selection = ("structure", tag)
        self._update_result_controls()
        field = self.fields.currentText()
        section = field in {"N", "V", "M"}
        soil = selection is None or selection[0] == "region"
        self.principal.setEnabled(not section and soil)
        self.plastic_points.setEnabled(not section and soil)
        self.canvas.show_model(
            self.model,
            st,
            field,
            self.deform.value(),
            result=self.result,
            principal=self.principal.isChecked() and not section and soil,
            plastic_points=self.plastic_points.isChecked() and not section and soil,
            stage_index=stage_idx,
            selection=selection,
            diagram_scale=self.diagram_scale.value(),
        )
        self.legend.setText(self.canvas.legend)
        if st is not None:
            self.statusBar().showMessage(f"{st.name} · accepted λ={st.lam:.6g}")

    def query_line(self):
        if self.result is not None:
            from .result_tools import QueryDialog

            dialog = QueryDialog(
                self.result, self.selected_stage(), self, deform=self.deform.value()
            )
            dialog.line_changed.connect(self.canvas.show_query_line)
            dialog.query()
            dialog.exec()

    def show_structure_forces(self, tag):
        """Plaxis-style N–V–M window of the clicked pile / liner / anchor."""
        if self.result is None:
            self.status.showMessage(
                "Finish the analysis with Solve (F5) before opening section forces.", 6000
            )
            return
        if tag not in self.result.model.structure_tags():
            self.status.showMessage(
                f"{tag} was not found as a structure in the mesh; regenerate the mesh."
            )
            return
        if self.result.model.structure_tags()[tag] not in {"beam", "bar"}:
            self.result_objects.setCurrentIndex(self.result_objects.findData(f"structure:{tag}"))
            self.fields.setCurrentText("|u|")
            return
        from .result_tools import StructureForceDialog

        if getattr(self, "force_dialog", None) is not None:
            self.force_dialog.close()
        self.force_dialog = StructureForceDialog(
            self.result, max(0, self.stages.currentRow()), tag, self
        )
        field = self.fields.currentText()
        if field in {"N", "V", "M"}:
            index = {"N": 0, "V": 1, "M": 2}[field]
            if index < self.force_dialog.component.count():
                self.force_dialog.component.setCurrentIndex(index)
        elif field in {"|u|", "ux", "uy"}:
            self.force_dialog.tabs.setCurrentIndex(2)
        self.force_dialog.show()

    def beam_diagrams(self):
        if self.result is not None:
            from .result_tools import BeamDiagramDialog

            BeamDiagramDialog(self.result, self.selected_stage(), self).exec()

    def structure_displacements(self):
        if self.result is None:
            self.status.showMessage(
                "Finish the analysis with Solve (F5) before opening the displacement chart.", 6000
            )
            return
        from .result_tools import StructureDisplacementDialog

        StructureDisplacementDialog(self.result, max(0, self.stages.currentRow()), self).exec()

    def discard_changes(self):
        if not self.dirty and not self.cad.unsaved:
            return True
        return (
            QMessageBox.question(
                self,
                "Unsaved changes",
                "Discard unsaved changes?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            == QMessageBox.StandardButton.Discard
        )

    def new_model(self):
        if self.busy or not self.discard_changes():
            return
        self.set_model(None)

    def new_mesh_model(self):
        if self.busy or not self.discard_changes():
            return
        dialog = NewModelDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set_model(dialog.model(), dirty=True)

    def open_dialog(self):
        if self.busy or not self.discard_changes():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open project", "", "SlipSurface (*.ssproj *.json)"
        )
        if path:
            try:
                self.open_path(path)
            except Exception as exc:
                self.show_error(str(exc))

    def open_path(self, path):
        if self.busy:
            raise RuntimeError("The project cannot be changed while a solve is running.")
        try:
            if str(path).lower().endswith(".sscad.json"):
                from ..cad.geometry import Drawing

                drawing = Drawing.from_dict(json.loads(Path(path).read_text("utf-8")))
                self.set_model(None)
                self.cad.commit(drawing)
                self.cad.saved_drawing = drawing
                self.cad.canvas.fit_drawing()
            elif Path(path).suffix.lower() == ".ssproj":
                project = api.load_project(path)
                self.set_model(project.model, project.results, path)
            else:
                self.set_model(api.load_model(path), path=path)
        except json.JSONDecodeError as exc:
            raise ModelFileError(Path(path).name, exc) from exc

    def save_path(self, path):
        if self.busy:
            raise RuntimeError("Cannot save while a solve is running.")
        if self.cad.mesh_outdated:
            raise ValueError(
                "Drawing changed; generate the mesh first or use Save drawing to keep the draft."
            )
        api.save_project(self.model, path, self.result)
        self.set_model(self.model, self.result, path, False)
        self.statusBar().showMessage(f"Saved: {Path(path).name}")

    def save_dialog(self):
        if self.busy:
            return
        if self.cad.mesh_outdated or self.model is None:
            self.cad.save_drawing()
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save project", str(self.path or "model.ssproj"), "SlipSurface (*.ssproj)"
        )
        if path:
            try:
                self.save_path(path if path.endswith(".ssproj") else path + ".ssproj")
            except Exception as exc:
                self.show_error(str(exc))

    def open_tunnel_example(self):
        if self.busy or not self.discard_changes():
            return
        from .demo import tunnel_model

        self.set_model(tunnel_model(), dirty=True)

    def open_excavation_example(self):
        if self.busy or not self.discard_changes():
            return
        from .demo import excavation_model

        self.set_model(excavation_model(), dirty=True)

    def open_footing_example(self):
        if self.busy or not self.discard_changes():
            return
        from .demo import footing_model

        self.set_model(footing_model(), dirty=True)

    def edit_boundaries(self):
        if self.workspace.currentWidget() is self.cad:
            self.cad.show_inspector(1)
            return
        if self.busy or not self._require_model():
            return
        dialog = BoundaryDialog(self.model, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set_model(dialog.updated, path=self.path, dirty=True)

    def edit_drawing_conditions(self):
        """Fixity/load step: the drawing's edge table, or the mesh form for a meshed-only model."""
        if self.busy:
            return
        if self.model is not None and not self.model.geometry and not self.cad.document.entities:
            self.edit_boundaries()
            return
        self.edit_geometry()
        self.workflow.set_current(2, emit=False)
        self.cad.show_inspector(1)

    def build_mesh(self):
        if self.busy:
            return
        self.edit_geometry()
        self.workflow.set_current(3, emit=False)
        self.cad.start_mesh()

    def edit_materials(self):
        if self.busy:
            return
        if self.model is None or self.cad.mesh_outdated:
            from dataclasses import replace

            from ..cad.material_assignment import material_specs, serialize_materials
            from .project_properties import DraftMaterialDialog

            drawing = self.cad.current_drawing()
            dialog = DraftMaterialDialog(material_specs(drawing, self.model), self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.cad.commit(replace(
                    drawing, material_library=serialize_materials(dialog.updated)
                ))
                self.result = None
                self.dirty = True
            return
        if not self._require_model():
            return
        dialog = MaterialDialog(self.model, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set_model(dialog.updated, path=self.path, dirty=True)

    def edit_geometry(self):
        if self.worker is not None:
            return
        self.workspace.setCurrentWidget(self.cad)
        self.project_dock.hide()
        for toggle in self.status.toggles.values():
            toggle.setEnabled(True)
        self.workflow.set_current(0, emit=False)
        self.status.showMessage(
            "Modeler · Pick points / enter coordinates · F2: whole drawing · F6: mesh"
        )
        self.cad.canvas.viewport().update()

    def open_interpret(self):
        """Open an independent results window without replacing the CAD workspace."""
        if self.model is None:
            return
        dlg = getattr(self, "_interpret_window", None)
        if dlg is None:
            dlg = QDialog(self)
            dlg.setWindowTitle("SlipSurfaceIQ-FEA · Interpret")
            dlg.resize(1100, 760)
            layout = QVBoxLayout(dlg)
            controls = QHBoxLayout()
            stages = QComboBox()
            fields = QComboBox()
            fields.addItems(["|u|", "ux", "uy"])
            controls.addWidget(QLabel("Stage"))
            controls.addWidget(stages)
            controls.addWidget(QLabel("Field"))
            controls.addWidget(fields)
            layout.addLayout(controls)
            canvas = MeshCanvas()
            layout.addWidget(canvas, 1)
            legend = QLabel()
            layout.addWidget(legend)
            dlg.viewer = (stages, fields, canvas, legend)
            stages.currentIndexChanged.connect(self._refresh_interpret)
            fields.currentIndexChanged.connect(self._refresh_interpret)
            dlg.finished.connect(lambda _code: setattr(self, "_interpret_window", None))
            self._interpret_window = dlg
        stages = dlg.viewer[0]
        stages.blockSignals(True)
        stages.clear()
        stages.addItems(["Initial", *[stage.name for stage in self.model.stages]])
        stages.setCurrentIndex(min(max(0, self.stages.currentRow()), stages.count() - 1))
        stages.blockSignals(False)
        self._refresh_interpret()
        dlg.show()
        dlg.raise_()

    def _refresh_interpret(self, *_):
        dlg = getattr(self, "_interpret_window", None)
        if dlg is None or self.model is None:
            return
        stages, fields, canvas, legend = dlg.viewer
        idx = stages.currentIndex()
        stage = None if self.result is None else (
            self.result.initial if idx == 0 else self.result.stages[idx - 1]
        )
        canvas.show_model(self.model, stage, fields.currentText(), 1.0,
                          result=self.result, stage_index=idx)
        legend.setText(canvas.legend)

    def show_results(self):
        self.workspace.setCurrentWidget(self.result_page)
        self.project_dock.setVisible(
            self.dock_action.isChecked() if hasattr(self, "dock_action") else True
        )
        self.workflow.set_current(7 if self.result is not None else 4, emit=False)
        for toggle in self.status.toggles.values():
            toggle.setEnabled(False)

    def fit_active_view(self):
        if self.workspace.currentWidget() is self.cad:
            self.cad.canvas.fit_drawing()
        else:
            self.canvas.fit_model()

    def drawing_file_action(self, method):
        if not self.busy:
            self.edit_geometry()
            getattr(self.cad, method)()

    def draft_tool(self, kind):
        if self.busy:
            return
        self.edit_geometry()
        if kind in {"region", "split", "hole", "line"}:
            self.cad.start_tool(kind)
        elif kind == "tunnel":
            self.workflow.set_current(0, emit=False)
            self.cad.start_engineering_tool(kind)
        else:
            self.workflow.set_current(1, emit=False)
            self.cad.start_engineering_tool(kind)

    def _accept_cad_model(self, model):
        from ..cad.transfer import transfer_model

        history = self.cad.undo_stack[:], self.cad.redo_stack[:]
        try:
            model, report = transfer_model(self.model, model)
        except Exception as exc:  # noqa: BLE001 - fall back to the drawing's fresh model
            report = [
                "Previous model definitions were not transferred; "
                f"a new elastic model was built: {exc}"
            ]
        carried = self.model is not None
        self.set_model(model, dirty=True)
        self.cad.undo_stack, self.cad.redo_stack = history
        self.log.clear()
        if carried:
            self.log.appendPlainText(
                "New mesh generated. Materials, stages, interfaces and extra structures "
                "were transferred; previous results are invalid on the new mesh."
            )
        for line in report:
            self.log.appendPlainText("· " + line)
        self.status.showMessage(
            f"Mesh ready · {len(report)} warnings, see the solve log."
            if report
            else "Mesh and supports are ready · Check the stages, then Solve."
        )

    def _cad_worker_stopped(self):
        if self._closing:
            self.close()

    def edit_structures(self):
        if self.busy:
            return
        self.edit_geometry()
        self.workflow.set_current(1, emit=False)
        self.cad.show_inspector(2)

    def edit_mesh_structures(self):
        if self.busy or not self._require_model():
            return
        dialog = StructureDialog(self.model, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set_model(dialog.updated, path=self.path, dirty=True)

    def edit_stages(self):
        """Stage editing is a tab in Model Properties, not a separate window."""
        self.edit_project_properties()

    def start_solve(self):
        if self.busy or not self._require_model():
            return
        self.show_results()
        self.cad.setEnabled(False)
        self.result = None
        for a in self.export_actions:
            a.setEnabled(False)
        self.log.clear()
        self.progress.setValue(0)
        self.draw()
        try:
            worker = SolveWorker(self.model, self)
        except Exception as exc:
            self.cad.setEnabled(True)
            self.show_error(str(exc))
            return
        self.worker = worker
        self._open_analysis_progress()
        for a in [*self.edit_actions, self.run_action]:
            a.setEnabled(False)
        self.stop_action.setEnabled(True)
        worker.progress.connect(self.on_progress)
        worker.succeeded.connect(self.on_success)
        worker.failed.connect(self.on_failure)
        worker.cancelled.connect(self.on_cancelled)
        worker.finished.connect(self.on_finished)
        worker.start()
        self.workflow.set_current(6, emit=False)
        self._update_guidance()

    def _open_analysis_progress(self):
        """Non-modal stage/iteration monitor; computation remains in SolveWorker."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Analysis progress · stages and iterations")
        dlg.resize(660, 420)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        layout = QVBoxLayout(dlg)
        self.analysis_stage_label = QLabel("Preparing analysis…")
        layout.addWidget(self.analysis_stage_label)
        self.analysis_progress = QProgressBar()
        self.analysis_progress.setRange(0, 100)
        layout.addWidget(self.analysis_progress)
        self.analysis_log = QPlainTextEdit()
        self.analysis_log.setReadOnly(True)
        layout.addWidget(self.analysis_log, 1)
        stop = QPushButton("Stop analysis")
        stop.clicked.connect(self.cancel_solve)
        layout.addWidget(stop)
        self.analysis_stop_button = stop
        self.analysis_dialog = dlg
        dlg.show()

    @Slot(object)
    def on_progress(self, event):
        if event.completed:
            self.progress.setValue(round(100 * (event.stage_index + 1) / event.stage_count))
            self.log.appendPlainText(f"{event.stage} · completed · λ={event.lam:.6g}")
        elif event.accepted:
            self.log.appendPlainText(
                f"{event.stage} · λ={event.lam:.6g} · "
                f"{event.iteration} iterations · R={event.residual:.3g}"
            )
        self.statusBar().showMessage(
            f"{event.stage} · λ={event.lam:.5g} · iteration {event.iteration}"
        )
        if hasattr(self, "analysis_dialog") and self.analysis_dialog is not None:
            pct = round(
                100 * (event.stage_index + int(event.completed)) / max(1, event.stage_count)
            )
            self.analysis_progress.setValue(pct)
            self.analysis_stage_label.setText(
                f"Stage {event.stage_index + 1}/{event.stage_count}: {event.stage} · "
                f"{pct}% · load factor λ={event.lam:.5g}"
            )
            self.analysis_log.appendPlainText(
                f"{event.stage} | λ={event.lam:.6g} | iteration {event.iteration} | "
                f"residual {event.residual:.3g} | "
                + ("completed" if event.completed else
                   "accepted" if event.accepted else "iterating")
            )

    @Slot(object)
    def on_success(self, result):
        self.set_model(result.model, result, self.path, dirty=True)
        self.workflow.set_current(7, emit=False)
        self.progress.setValue(100)
        self.log.appendPlainText("Analysis completed. Results are ready to save.")
        if hasattr(self, "analysis_dialog") and self.analysis_dialog is not None:
            self.analysis_progress.setValue(100)
            self.analysis_stage_label.setText("100% · Analysis completed")
            self.analysis_stop_button.setEnabled(False)

    @Slot(str)
    def on_failure(self, message):
        self.log.appendPlainText(message)
        if hasattr(self, "analysis_log"):
            self.analysis_log.appendPlainText("FAILED: " + message)
            self.analysis_stop_button.setEnabled(False)
        self.statusBar().showMessage("Solve failed; no result was produced. Inspect the log.")

    @Slot()
    def on_cancelled(self):
        self.log.appendPlainText("Analysis cancelled. No result was produced.")
        if hasattr(self, "analysis_log"):
            self.analysis_log.appendPlainText("Analysis cancelled.")
            self.analysis_stop_button.setEnabled(False)
        self.statusBar().showMessage("Cancelled")

    @Slot()
    def on_finished(self):
        self.cad.setEnabled(True)
        worker, self.worker = self.worker, None
        worker.deleteLater()
        for a in [*self.edit_actions, self.run_action]:
            a.setEnabled(True)
        self.stop_action.setEnabled(False)
        self._update_guidance()
        if self._closing:
            self.close()

    def cancel_solve(self):
        if self.worker is not None:
            self.worker.requestInterruption()
            self.stop_action.setEnabled(False)
            self.statusBar().showMessage(
                "Cancel requested; the current operation is finishing safely…"
            )

    def export_dialog(self, kind):
        if self.result is None:
            return
        ext = "csv" if kind == "beam" else kind
        path, _ = QFileDialog.getSaveFileName(
            self, "Export results", f"result.{ext}", f"{ext.upper()} (*.{ext})"
        )
        if not path:
            return
        try:
            st = self.selected_stage()
            if kind == "html":
                export_html(self.result, path)
            elif kind == "beam":
                export_beam_csv(self.result, path, st)
            elif kind == "csv":
                export_csv(self.result, path, st)
            else:
                api.export_vtu(self.result, path, st)
            self.statusBar().showMessage(f"Exported: {Path(path).name}")
        except Exception as exc:
            self.show_error(str(exc))

    def show_error(self, text):
        self.log.appendPlainText(text)
        QMessageBox.warning(self, "Operation failed", text)

    def closeEvent(self, event):
        if self.cad.worker is not None:
            self._closing = True
            self.cad.reject()
            event.ignore()
        elif self.busy:
            self._closing = True
            self.cancel_solve()
            event.ignore()
        elif self.discard_changes():
            self._save_layout()
            event.accept()
        else:
            self._closing = False
            event.ignore()


def main(argv=None):
    if argv is not None and len(argv) > 0:
        first = str(argv[0])
        if first.endswith(".py") or Path(first).name == Path(sys.argv[0]).name:
            argv = list(argv[1:])
    parser = argparse.ArgumentParser(description="SlipSurfaceIQ native desktop")
    parser.add_argument("project", nargs="?", help=".ssproj or model JSON")
    parser.add_argument("--smoke-test", metavar="DIRECTORY", help="run source application checks")
    args = parser.parse_args(argv)
    if sys.platform == "win32" and QApplication.instance() is None:
        # Native title bar/menus must not switch to the dark palette under our light theme.
        os.environ.setdefault("QT_QPA_PLATFORM", "windows:darkmode=0")
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("SlipSurfaceIQ-FEA")
    from .preferences import apply_theme

    apply_theme()
    if args.smoke_test:
        from .smoke import smoke_check

        return smoke_check(app, args.smoke_test)
    window = MainWindow()
    if args.project:
        try:
            window.open_path(args.project)
        except Exception as exc:
            window.show_error(str(exc))
    window.show()
    return app.exec()

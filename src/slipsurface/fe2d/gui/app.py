"""SlipSurfaceIQ-FEA desktop shell, adapted from the SlipSurfaceIQ-LE modeler.

menu bar
workflow bar   Geometri › Destekler › Mesnet/yük › Ağ › Malzemeler › Aşamalar › Çöz › Sonuçlar
               with a "next step" hint; finished steps are ticked
left dock      Belge Görüntüleyici (aşamalar, model özeti) + Görüntüleme Seçenekleri
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
    QVBoxLayout,
    QWidget,
)

from .. import api
from ..core.errors import ModelError
from ..io.report import export_beam_csv, export_csv, export_html
from .boundary_editor import BoundaryDialog
from .canvas import MeshCanvas
from .dialogs import MaterialDialog, NewModelDialog, StageDialog
from .editing import (
    region_label,
    stage_active_structures,
    stage_region_material,
    structure_label,
)
from .icons import icon
from .structure_editor import StructureDialog
from .worker import SolveWorker
from .workflow import WorkflowBar

STEPS = [
    "Geometri",
    "Destekler",
    "Mesnet / yük",
    "Ağ",
    "Malzemeler",
    "Aşamalar",
    "Çöz",
    "Sonuçlar",
]


class ModelFileError(ModelError):
    """A project/model file is not valid JSON — report the file, not just the parse."""

    def __init__(self, name: str, exc: json.JSONDecodeError) -> None:
        where = f"satır {exc.lineno}, kolon {exc.colno}"
        super().__init__(
            f"'{name}' JSON olarak okunamadı ({where}). "
            f"Dosya bir SlipSurfaceIQ-FEA modeli (.ssproj / model JSON) değil "
            "veya bozuk. Detay: " + str(exc)
        )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        from .preferences import apply_theme

        apply_theme()
        self.setWindowTitle("SlipSurfaceIQ-FEA · Masaüstü")
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
        flow_bar = QToolBar("İş akışı")
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
        self.cad.drawing_changed.connect(self._update_guidance)
        self.cad.structure_requested.connect(self.show_structure_forces)
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
        self.log.setPlaceholderText("Çözüm günlüğü")
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
        self.status.showMessage("Hazır · Birimler kN, m, kPa · Gerilmede çekme pozitif")
        self._view_menu()
        self._restore_layout()
        self.set_model(None)

    def _build_dock(self):
        """Left dock: Belge Görüntüleyici (aşama listesi + özet) ve Görüntüleme
        Seçenekleri (alan, deformasyon ölçeği, kaplamalar) — LE modeler layout."""
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
        self.deform = QDoubleSpinBox()
        self.deform.setRange(0, 1e6)
        self.deform.setValue(1.0)
        self.deform.valueChanged.connect(self.draw)
        self.principal = QCheckBox("Asal oklar")
        self.plastic_points = QCheckBox("Plastik noktalar")
        for checkbox in [self.principal, self.plastic_points]:
            checkbox.toggled.connect(self.draw)
        reset = QPushButton("Varsayılanlara dön")
        reset.clicked.connect(self._reset_display)
        dock_split = QSplitter(Qt.Orientation.Vertical)
        left = QVBoxLayout()
        left.addWidget(QLabel("BELGE GÖRÜNTÜLEYİCİ"))
        left.addWidget(self.stages, 1)
        left.addWidget(self.summary)
        viewer = QWidget()
        viewer.setLayout(left)
        right = QVBoxLayout()
        right.addWidget(QLabel("GÖRÜNTÜLEME SEÇENEKLERİ"))
        row = QHBoxLayout()
        row.addWidget(QLabel("Alan"))
        row.addWidget(self.fields, 1)
        right.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Deformasyon ×"))
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
            hint = "Çözüm sürüyor · ■ Durdur ile iptal"
        elif 0 not in done:
            hint = "Sıradaki: Geometri menüsünden zemin bölgesi çizin"
        elif 2 not in done:
            hint = "Sıradaki: Mesnet / yük tablosunda ux/uy işaretleyin"
        elif 3 not in done:
            hint = "Sıradaki: Ağı üret (Ctrl+M)"
        elif 6 not in done:
            hint = "Sıradaki: Malzeme ve aşamaları kontrol edip Çöz (F5)"
        else:
            hint = "Sonuçlar hazır · Sonuç incele / Sonuç aktar menüleri"
        return done, hint

    def _update_guidance(self, *_):
        if not hasattr(self, "guidance"):
            return
        done, hint = self.step_state()
        self.workflow.set_done(done)
        self.guidance.setText(hint)
        self.guidance.setToolTip(hint)

    def _view_menu(self):
        menu = self.menuBar().addMenu("Görünüm")
        # The dock is hidden by design while drawing; this is the results-view choice.
        self.dock_action = QAction("Proje paneli", self)
        self.dock_action.setCheckable(True)
        self.dock_action.setChecked(True)
        self.dock_action.toggled.connect(self._dock_toggled)
        menu.addAction(self.dock_action)
        self.log_action = QAction("Çözüm günlüğü paneli", self)
        self.log_action.setCheckable(True)
        self.log_action.setChecked(True)
        self.log_action.toggled.connect(self.log_panel.setVisible)
        menu.addAction(self.log_action)
        menu.addSeparator()
        reset = QAction("Yerleşimi sıfırla", self)
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
        toolbar = QToolBar("Çalışma alanı")
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

        file_menu = self.menuBar().addMenu("Dosya")
        for title, slot, shortcut in [
            ("Yeni", self.new_model, "Ctrl+N"),
            ("Aç", self.open_dialog, "Ctrl+O"),
            ("Kaydet", self.save_dialog, "Ctrl+S"),
        ]:
            a = action(title, slot, shortcut)
            toolbar.addAction(a)
            file_menu.addAction(a)
            self.edit_actions.append(a)
        file_menu.addAction(action("Parametrik dikdörtgen model…", self.new_mesh_model))
        for title, method in [
            ("Çizim aç…", "open_drawing"),
            ("Çizim kaydet…", "save_drawing"),
            ("DXF al…", "import_dxf"),
            ("DXF ver…", "export_dxf"),
        ]:
            file_menu.addAction(
                action(title, lambda _=False, m=method: self.drawing_file_action(m))
            )
        file_menu.addSeparator()
        self.examples_menu = file_menu.addMenu("Örnekler")
        for title, slot in [
            ("Dört aşamalı tünel", self.open_tunnel_example),
            ("Aşamalı iksa kazısı (palplanş + ankraj)", self.open_excavation_example),
            ("İki tabakalı şerit temel", self.open_footing_example),
        ]:
            ex_action = action(title, slot)
            self.examples_menu.addAction(ex_action)
            self.edit_actions.append(ex_action)
        edit_menu = self.menuBar().addMenu("Düzenle")
        for title, method in [
            ("Geri al", "undo"),
            ("Yinele", "redo"),
            ("Seçileni sil", "delete_entity"),
        ]:
            edit_menu.addAction(
                action(title, lambda _=False, m=method: self.drawing_file_action(m))
            )
        # Modelling steps live in the numbered workflow bar; the toolbar keeps file/run.
        model_menu = self.menuBar().addMenu("Model")
        for title, slot in [
            ("Geometri / CAD", self.edit_geometry),
            ("Malzemeler…", self.edit_materials),
            ("Yapılar (çizim)", self.edit_structures),
            ("Sınırlar (ağ kümeleri)…", self.edit_boundaries),
            ("Aşamalar…", self.edit_stages),
        ]:
            a = action(title, slot)
            model_menu.addAction(a)
            self.edit_actions.append(a)
        toolbar.addSeparator()
        self.mesh_action = action("Ağı üret", self.build_mesh, "Ctrl+M")
        toolbar.addAction(self.mesh_action)
        self.edit_actions.append(self.mesh_action)
        self.run_action = action("▶ Çöz", self.start_solve, "F5")
        self.stop_action = action("■ Durdur", self.cancel_solve)
        self.stop_action.setEnabled(False)
        toolbar.addAction(self.run_action)
        toolbar.addAction(self.stop_action)
        toolbar.addAction(action("Görünüme sığdır", self.fit_active_view, "F2", "zoom_all"))
        toolbar.addAction(action("Ağ / Sonuçlar", self.show_results, "F6"))
        geometry_menu = self.menuBar().addMenu("Geometri")
        for title, kind in [
            ("Çokgen bölge", "region"),
            ("Kazı / bölme çizgisi", "split"),
            ("Boşluk", "hole"),
            ("Ağ kısıt çizgisi", "line"),
        ]:
            geometry_menu.addAction(action(title, lambda _=False, k=kind: self.draft_tool(k)))
        support_menu = self.menuBar().addMenu("Destek")
        for title, kind in [
            ("Kazık çiz", "pile"),
            ("Kaplama / kiriş çiz", "liner"),
            ("Tek bulon / ankraj / zemin çivisi çiz", "bolt"),
        ]:
            support_menu.addAction(action(title, lambda _=False, k=kind: self.draft_tool(k)))
        support_menu.addSeparator()
        support_menu.addAction(
            action(
                "Bulon paterni (seçili çizgi)…",
                lambda _=False: self.drawing_file_action("bolt_pattern"),
            )
        )
        support_menu.addSeparator()
        support_menu.addAction(action("Mevcut ağdaki yapı özellikleri…", self.edit_mesh_structures))
        tunnel_menu = self.menuBar().addMenu("Tünel")
        tunnel_menu.addAction(
            action(
                "Tünel çiz (merkez + yarıçap)",
                lambda _=False: self.draft_tool("tunnel"),
            )
        )
        for title, method in [
            ("Eşdeğer kesit tünel…", "open_tunnel_designer"),
            ("Kaplama / püskürtme beton / iksa tasarımcısı…", "open_lining_designer"),
        ]:
            tunnel_menu.addAction(
                action(title, lambda _=False, m=method: self.drawing_file_action(m))
            )
        result_menu = self.menuBar().addMenu("Sonuç incele")
        for title, slot in [
            ("Sorgu çizgisi", self.query_line),
            ("Liner N–V–M", self.beam_diagrams),
        ]:
            a = action(title, slot)
            result_menu.addAction(a)
            self.export_actions.append(a)
        export_menu = self.menuBar().addMenu("Sonuç aktar")
        for title, kind in [
            ("VTU / ParaView", "vtu"),
            ("Düğüm CSV", "csv"),
            ("Kiriş N–V–M CSV", "beam"),
            ("HTML rapor", "html"),
        ]:
            a = action(title, lambda checked=False, k=kind: self.export_dialog(k), None, "export")
            export_menu.addAction(a)
            self.export_actions.append(a)

    def _sync_stage_tabs(self, selected_row: int):
        self.stage_tabs.blockSignals(True)
        while self.stage_tabs.count():
            self.stage_tabs.removeTab(0)
        if self.model is not None:
            names = [
                "0. Başlangıç",
                *[f"{i + 1}. {s.name}" for i, s in enumerate(self.model.stages)],
            ]
            for name in names:
                self.stage_tabs.addTab(name)
            self.stage_tabs.setCurrentIndex(max(0, min(selected_row, self.stage_tabs.count() - 1)))
        self.stage_tabs.blockSignals(False)

    def _on_stage_list_changed(self, row: int):
        if hasattr(self, "stage_tabs") and 0 <= row < self.stage_tabs.count():
            self.stage_tabs.blockSignals(True)
            self.stage_tabs.setCurrentIndex(row)
            self.stage_tabs.blockSignals(False)
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
        state = f"malzeme {cur_mat}" if cur_mat else "bu aşamada kazılmış"
        self.status.showMessage(
            f"{region_label(self.model, region)} · {state}. "
            "Kesit tesiri için kaplama, kazık veya ankraja tıklayın.",
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
        st_title = (
            "0. Başlangıç"
            if stage_idx <= 0
            else f"{stage_idx}. {self.model.stages[stage_idx - 1].name}"
        )
        header = menu.addAction(f"Aşama: {st_title}")
        header.setEnabled(False)
        if region > 0:
            cur_mat = stage_region_material(self.model, stage_idx, region)
            state = cur_mat if cur_mat else "kazılmış"
            label = menu.addAction(f"{region_label(self.model, region)} · {state}")
            label.setEnabled(False)
        if struct_tag:
            s_lbl = structure_label(self.model, struct_tag)
            active = struct_tag in stage_active_structures(self.model, stage_idx)
            forces = menu.addAction(f"Kesit tesirleri (N–V–M): {s_lbl}")
            forces.setEnabled(self.result is not None)
            forces.triggered.connect(lambda _=False, t=struct_tag: self.show_structure_forces(t))
            if not active:
                note = menu.addAction("Bu aşamada henüz yok; pencere yüklü aşamayı açar")
                note.setEnabled(False)
        menu.exec(global_pos)

    @property
    def busy(self):
        return self.worker is not None or (hasattr(self, "cad") and self.cad.worker is not None)

    def set_model(self, model, result=None, path=None, dirty=False):
        if model is None:
            self._set_empty_state(path, dirty)
            return
        model.validate()
        self.cad.load_model(model)
        self.show_results()
        self.model, self.result, self.path, self.dirty = model, result, path, dirty
        selected_row = len(model.stages) if result else (1 if model.stages else 0)
        self.stages.blockSignals(True)
        self.stages.clear()
        self.stages.addItems(["Başlangıç", *[s.name for s in model.stages]])
        self.stages.setCurrentRow(selected_row)
        self.stages.blockSignals(False)
        self._sync_stage_tabs(selected_row)
        self.summary.setText(
            f"{model.analysis.value}\n\n{model.mesh.nn} düğüm\n"
            f"{sum(b.ne for b in model.mesh.blocks)} eleman\n"
            f"{len(model.materials)} malzeme · {len(model.mesh.regions())} bölge\n\n"
            "Sonuç:\n"
            "· Alt sekmelerden aşama seçin\n"
            "· Kaplama, kazık veya ankraja tıklayınca N–V–M açılır\n"
            "· Düğüm sorgusu: çift tık"
        )
        for a in self.export_actions:
            a.setEnabled(result is not None)
        self.setWindowTitle(
            f"SlipSurfaceIQ-FEA · {Path(path).name if path else 'Yeni model'}"
            + (" *" if dirty else "")
        )
        if result is not None:
            self.progress.setValue(100)
        else:
            self.progress.setValue(0)
        self.draw()
        self._update_guidance()
        self.status.showMessage("Model hazır · Birimler kN, m, kPa")

    def _set_empty_state(self, path=None, dirty=False):
        """No model yet: blank scene, clear stage list, hint at first steps."""
        self.model = self.result = None
        self.cad.load_model(None)
        self.edit_geometry()
        self.path = path
        self.dirty = dirty
        self.stages.blockSignals(True)
        self.stages.clear()
        self.stages.blockSignals(False)
        self._sync_stage_tabs(0)
        self.summary.setText(
            "Boş proje.\n\nBaşlamak için:\n"
            "· Dosya > Yeni ile dikdörtgen zemin modeli\n"
            "· Geometri / CAD ile çizimden ağ\n"
            "· Dosya > Aç ile mevcut proje"
        )
        for a in self.export_actions:
            a.setEnabled(False)
        self.setWindowTitle(f"SlipSurfaceIQ-FEA · {Path(path).name if path else 'Boş proje'}")
        self.progress.setValue(0)
        self.canvas.scene().clear()
        self.canvas.model = self.canvas.stage = None
        self.legend.setText("")
        self._update_guidance()
        self.statusBar().showMessage(
            "Modelleyici · Geometri, Tünel veya Destek menüsünden çizime başlayın"
        )

    def _require_model(self):
        if self.cad.mesh_outdated:
            self.edit_geometry()
            self.status.showMessage("Çizim değişti · Önce Ağ üret ile hesap modelini güncelleyin.")
            return False
        if self.model is None:
            self.status.showMessage(
                "Model yok · Dosya > Yeni, Geometri / CAD ya da Dosya > Aç ile başlayın", 8000
            )
            return False
        return True

    def selected_stage(self):
        if self.result is None:
            return None
        index = self.stages.currentRow()
        return self.result.initial if index <= 0 else self.result.stages[index - 1]

    def draw(self, *_):
        if self.model is None:
            return
        st = self.selected_stage()
        stage_idx = max(0, self.stages.currentRow())
        self.canvas.show_model(
            self.model,
            st,
            self.fields.currentText(),
            self.deform.value(),
            result=self.result,
            principal=self.principal.isChecked(),
            plastic_points=self.plastic_points.isChecked(),
            stage_index=stage_idx,
        )
        self.legend.setText(self.canvas.legend)
        if st is not None:
            self.statusBar().showMessage(f"{st.name} · kabul edilen λ={st.lam:.6g}")

    def query_line(self):
        if self.result is not None:
            from .result_tools import QueryDialog

            dialog = QueryDialog(self.result, self.selected_stage(), self)
            dialog.line_changed.connect(self.canvas.show_query_line)
            dialog.query()
            dialog.exec()

    def show_structure_forces(self, tag):
        """Plaxis-style N–V–M window of the clicked pile / liner / anchor."""
        if self.result is None:
            self.status.showMessage(
                "Kesit tesirleri için önce Çöz (F5) ile analizi tamamlayın.", 6000
            )
            return
        if tag not in self.result.model.structure_tags():
            self.status.showMessage(f"{tag} ağda yapı olarak bulunamadı; ağı yeniden üretin.")
            return
        from .result_tools import StructureForceDialog

        if getattr(self, "force_dialog", None) is not None:
            self.force_dialog.close()
        self.force_dialog = StructureForceDialog(
            self.result, max(0, self.stages.currentRow()), tag, self
        )
        self.force_dialog.show()

    def beam_diagrams(self):
        if self.result is not None:
            from .result_tools import BeamDiagramDialog

            BeamDiagramDialog(self.result, self.selected_stage(), self).exec()

    def discard_changes(self):
        if not self.dirty and not self.cad.unsaved:
            return True
        return (
            QMessageBox.question(
                self,
                "Kaydedilmemiş değişiklikler",
                "Kaydedilmemiş değişiklikler bırakılsın mı?",
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
        path, _ = QFileDialog.getOpenFileName(self, "Proje aç", "", "SlipSurface (*.ssproj *.json)")
        if path:
            try:
                self.open_path(path)
            except Exception as exc:
                self.show_error(str(exc))

    def open_path(self, path):
        if self.busy:
            raise RuntimeError("Çözüm sürerken proje değiştirilemez.")
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
            raise RuntimeError("Çözüm sürerken kayıt yapılamaz.")
        if self.cad.mesh_outdated:
            raise ValueError(
                "Çizim değişti; önce ağı üretin veya Çizim kaydet ile taslağı saklayın."
            )
        api.save_project(self.model, path, self.result)
        self.set_model(self.model, self.result, path, False)
        self.statusBar().showMessage(f"Kaydedildi: {Path(path).name}")

    def save_dialog(self):
        if self.busy:
            return
        if self.cad.mesh_outdated or self.model is None:
            self.cad.save_drawing()
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Proje kaydet", str(self.path or "model.ssproj"), "SlipSurface (*.ssproj)"
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
        """Mesnet/yük step: the drawing's edge table, or the mesh form for a meshed-only model."""
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
        if self.busy or not self._require_model():
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
        self.status.showMessage("Modelleyici · Nokta seç / koordinat gir · F2: tüm çizim · F6: ağ")
        self.cad.canvas.viewport().update()

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
            report = [f"Önceki model tanımları aktarılamadı, yeni elastik model kuruldu: {exc}"]
        carried = self.model is not None
        self.set_model(model, dirty=True)
        self.cad.undo_stack, self.cad.redo_stack = history
        self.log.clear()
        if carried:
            self.log.appendPlainText(
                "Yeni ağ üretildi. Malzemeler, aşamalar, ara yüzler ve ek yapılar aktarıldı; "
                "önceki sonuçlar yeni ağda geçersiz."
            )
        for line in report:
            self.log.appendPlainText("· " + line)
        self.status.showMessage(
            f"Ağ hazır · {len(report)} uyarı, Çözüm günlüğüne bakın."
            if report
            else "Ağ ve destekler hazır · Aşamaları kontrol edip Çöz ile ilerleyin."
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
        if self.busy or not self._require_model():
            return
        dialog = StageDialog(self.model, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set_model(dialog.updated, path=self.path, dirty=True)

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

    @Slot(object)
    def on_progress(self, event):
        if event.completed:
            self.progress.setValue(round(100 * (event.stage_index + 1) / event.stage_count))
            self.log.appendPlainText(f"{event.stage} · tamamlandı · λ={event.lam:.6g}")
        elif event.accepted:
            self.log.appendPlainText(
                f"{event.stage} · λ={event.lam:.6g} · "
                f"{event.iteration} iterasyon · R={event.residual:.3g}"
            )
        self.statusBar().showMessage(
            f"{event.stage} · λ={event.lam:.5g} · iterasyon {event.iteration}"
        )

    @Slot(object)
    def on_success(self, result):
        self.set_model(result.model, result, self.path, dirty=True)
        self.workflow.set_current(7, emit=False)
        self.progress.setValue(100)
        self.log.appendPlainText("Analiz tamamlandı. Sonuçlar kaydedilmeye hazır.")

    @Slot(str)
    def on_failure(self, message):
        self.log.appendPlainText(message)
        self.statusBar().showMessage("Çözüm başarısız; sonuç üretilmedi. Günlüğü inceleyin.")

    @Slot()
    def on_cancelled(self):
        self.log.appendPlainText("Analiz iptal edildi. Sonuç üretilmedi.")
        self.statusBar().showMessage("İptal edildi")

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
            self.statusBar().showMessage("İptal isteniyor; mevcut işlem güvenle tamamlanıyor…")

    def export_dialog(self, kind):
        if self.result is None:
            return
        ext = "csv" if kind == "beam" else kind
        path, _ = QFileDialog.getSaveFileName(
            self, "Sonuç aktar", f"sonuc.{ext}", f"{ext.upper()} (*.{ext})"
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
            self.statusBar().showMessage(f"Aktarıldı: {Path(path).name}")
        except Exception as exc:
            self.show_error(str(exc))

    def show_error(self, text):
        self.log.appendPlainText(text)
        QMessageBox.warning(self, "İşlem tamamlanamadı", text)

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
    parser.add_argument(
        "--smoke-test", metavar="DIRECTORY", help="run installed application checks"
    )
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

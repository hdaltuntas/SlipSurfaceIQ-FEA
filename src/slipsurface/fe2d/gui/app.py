"""SlipSurfaceIQ-FEA desktop shell, adapted from the SlipSurfaceIQ-LE modeler.

menu bar
workflow bar   Geometri › Malzemeler › Yapılar › Sınırlar › Aşamalar
left dock      Belge Görüntüleyici (aşamalar, model özeti) + Görüntüleme Seçenekleri
centre         result canvas + field selectors + convergence tabs
status bar     hints, coordinates, SNAP / GRID / ORTHO toggles
"""

from __future__ import annotations

import argparse
import json
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
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .. import api
from ..core.errors import ModelError
from ..io.report import export_beam_csv, export_csv, export_html
from .boundary_editor import BoundaryDialog
from .canvas import ConvergencePlot, MeshCanvas
from .dialogs import MaterialDialog, NewModelDialog, StageDialog
from .icons import icon
from .structure_editor import StructureDialog
from .worker import SolveWorker
from .workflow import WorkflowBar

STEPS = ["Geometri", "Malzemeler", "Yapılar", "Sınırlar", "Aşamalar"]


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
        layout.addWidget(self.workflow)
        split = QSplitter()
        view = QWidget()
        right = QVBoxLayout(view)
        from .statusbar import CadStatusBar

        self.status = CadStatusBar(self)
        self.setStatusBar(self.status)
        self.canvas = MeshCanvas()
        self.canvas.queried.connect(self.status.showMessage)
        self.canvas.mouse_world.connect(self.status.show_coords)
        right.addWidget(self.canvas, 1)
        self.legend = QLabel("")
        self.legend.setStyleSheet("padding:8px;color:#526677")
        right.addWidget(self.legend)
        split.addWidget(view)
        split.setSizes([1000, 1000])
        layout.addWidget(split, 1)
        tabs = QTabWidget()
        self.plot = ConvergencePlot()
        tabs.addTab(self.plot, "Yakınsama")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        tabs.addTab(self.log, "Çözüm günlüğü")
        tabs.setMaximumHeight(210)
        layout.addWidget(tabs)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)
        self.setCentralWidget(root)
        self.status.showMessage("Hazır · Birimler kN, m, kPa · Gerilmede çekme pozitif")
        self.set_model(None)

    def _build_dock(self):
        """Left dock: Belge Görüntüleyici (aşama listesi + özet) ve Görüntüleme
        Seçenekleri (alan, deformasyon ölçeği, kaplamalar) — LE modeler layout."""
        self.stages = QListWidget()
        self.stages.currentRowChanged.connect(self.draw)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("padding:12px;line-height:1.4;color:#526677")
        self.fields = QComboBox()
        self.fields.addItems(
            [
                "|u|", "ux", "uy", "sxx", "syy", "szz", "txy",
                "s1", "s3", "q", "plastic", "pore", "excess_pore",
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
            self.edit_materials,
            self.edit_structures,
            self.edit_boundaries,
            self.edit_stages,
        )[i]
        slot()

    def _actions(self):
        toolbar = QToolBar("Çalışma alanı")
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
        toolbar.addSeparator()
        for title, slot in [
            ("Geometri / CAD", self.edit_geometry),
            ("Malzemeler", self.edit_materials),
            ("Yapılar", self.edit_structures),
            ("Sınırlar", self.edit_boundaries),
            ("Aşamalar", self.edit_stages),
        ]:
            a = action(title, slot)
            toolbar.addAction(a)
            self.edit_actions.append(a)
        toolbar.addSeparator()
        self.run_action = action("▶ Çöz", self.start_solve, "F5")
        self.stop_action = action("■ Durdur", self.cancel_solve)
        self.stop_action.setEnabled(False)
        toolbar.addAction(self.run_action)
        toolbar.addAction(self.stop_action)
        toolbar.addAction(
            action("Görünüme sığdır", lambda: self.canvas.fit_model(), None, "zoom_all")
        )
        examples_menu = self.menuBar().addMenu("Örnekler")
        demo_action = action("Dört aşamalı tünel", self.open_tunnel_example)
        examples_menu.addAction(demo_action)
        self.edit_actions.append(demo_action)
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

    @property
    def busy(self):
        return self.worker is not None

    def set_model(self, model, result=None, path=None, dirty=False):
        if model is None:
            self._set_empty_state(path, dirty)
            return
        model.validate()
        self.model, self.result, self.path, self.dirty = model, result, path, dirty
        self.stages.blockSignals(True)
        self.stages.clear()
        self.stages.addItems(["Başlangıç", *[s.name for s in model.stages]])
        self.stages.setCurrentRow(len(model.stages) if result else 0)
        self.stages.blockSignals(False)
        self.summary.setText(
            f"{model.analysis.value}\n\n{model.mesh.nn} düğüm\n"
            f"{sum(b.ne for b in model.mesh.blocks)} eleman\n"
            f"{len(model.materials)} malzeme\n\n"
            "Düğüm sorgusu: çift tık\nYakınlaştırma: fare tekeri\n"
            "Kaydırma: sürükle"
        )
        for a in self.export_actions:
            a.setEnabled(result is not None)
        self.setWindowTitle(
            f"SlipSurfaceIQ-FEA · {Path(path).name if path else 'Yeni model'}"
            + (" *" if dirty else "")
        )
        self.plot.reset()
        if result is not None:
            for snapshot in [result.initial, *result.stages]:
                if snapshot.history:
                    self.plot.values.extend(
                        r for step in snapshot.history.steps for r in step.residuals
                    )
            self.plot.update()
            self.progress.setValue(100)
        else:
            self.progress.setValue(0)
        self.draw()

    def _set_empty_state(self, path=None, dirty=False):
        """No model yet: blank scene, clear stage list, hint at first steps."""
        self.model = self.result = None
        self.path = path
        self.dirty = dirty
        self.stages.blockSignals(True)
        self.stages.clear()
        self.stages.blockSignals(False)
        self.summary.setText(
            "Boş proje.\n\nBaşlamak için:\n"
            "· Dosya > Yeni ile dikdörtgen zemin modeli\n"
            "· Geometri / CAD ile çizimden ağ\n"
            "· Dosya > Aç ile mevcut proje"
        )
        for a in self.export_actions:
            a.setEnabled(False)
        self.setWindowTitle(f"SlipSurfaceIQ-FEA · {Path(path).name if path else 'Boş proje'}")
        self.plot.reset()
        self.progress.setValue(0)
        self.canvas.scene().clear()
        self.canvas.model = self.canvas.stage = None
        self.legend.setText("")
        self.statusBar().showMessage("Boş proje · Dosya > Yeni ya da Geometri / CAD ile başlayın")

    def _require_model(self):
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
        self.canvas.show_model(
            self.model,
            st,
            self.fields.currentText(),
            self.deform.value(),
            result=self.result,
            principal=self.principal.isChecked(),
            plastic_points=self.plastic_points.isChecked(),
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

    def beam_diagrams(self):
        if self.result is not None:
            from .result_tools import BeamDiagramDialog

            BeamDiagramDialog(self.result, self.selected_stage(), self).exec()

    def discard_changes(self):
        if not self.dirty:
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
            if Path(path).suffix.lower() == ".ssproj":
                project = api.load_project(path)
                self.set_model(project.model, project.results, path)
            else:
                self.set_model(api.load_model(path), path=path)
        except json.JSONDecodeError as exc:
            raise ModelFileError(Path(path).name, exc) from exc

    def save_path(self, path):
        if self.busy:
            raise RuntimeError("Çözüm sürerken kayıt yapılamaz.")
        api.save_project(self.model, path, self.result)
        self.set_model(self.model, self.result, path, False)
        self.statusBar().showMessage(f"Kaydedildi: {Path(path).name}")

    def save_dialog(self):
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

    def edit_boundaries(self):
        if self.busy or not self._require_model():
            return
        dialog = BoundaryDialog(self.model, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set_model(dialog.updated, path=self.path, dirty=True)

    def edit_materials(self):
        if self.busy or not self._require_model():
            return
        dialog = MaterialDialog(self.model, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set_model(dialog.updated, path=self.path, dirty=True)

    def edit_geometry(self):
        if self.busy or not self.discard_changes():
            return
        try:
            from .cad import CadDialog

            dialog = CadDialog(self.model, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.set_model(dialog.updated, dirty=True)
        except Exception as exc:
            self.show_error(str(exc))

    def edit_structures(self):
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
        self.result = None
        for a in self.export_actions:
            a.setEnabled(False)
        self.plot.reset()
        self.log.clear()
        self.progress.setValue(0)
        self.draw()
        try:
            worker = SolveWorker(self.model, self)
        except Exception as exc:
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

    @Slot(object)
    def on_progress(self, event):
        self.plot.add_progress(event)
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
        worker, self.worker = self.worker, None
        worker.deleteLater()
        for a in [*self.edit_actions, self.run_action]:
            a.setEnabled(True)
        self.stop_action.setEnabled(False)
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
        if self.busy:
            self._closing = True
            self.cancel_solve()
            event.ignore()
        elif self.discard_changes():
            event.accept()
        else:
            self._closing = False
            event.ignore()


def main(argv=None):
    parser = argparse.ArgumentParser(description="SlipSurfaceIQ native desktop")
    parser.add_argument("project", nargs="?", help=".ssproj or model JSON")
    parser.add_argument(
        "--smoke-test", metavar="DIRECTORY", help="run installed application checks"
    )
    args = parser.parse_args(argv)
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

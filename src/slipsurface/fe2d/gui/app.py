"""SlipSurfaceIQ native desktop entry point (Faz 5.1). No web runtime."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QSplitter,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .. import api
from ..io.report import export_beam_csv, export_csv, export_html
from .canvas import ConvergencePlot, MeshCanvas
from .dialogs import MaterialDialog, NewModelDialog, StageDialog, sample_model
from .worker import SolveWorker

_STYLE = """
QMainWindow,QDialog {background:#eef3f7;color:#213547}
QToolBar {background:#fff;border-bottom:1px solid #d4e0e9;padding:7px;spacing:10px}
QToolButton {padding:6px 10px;border-radius:4px}
QToolButton:hover {background:#dceef4}
QListWidget,QPlainTextEdit {background:#fff;border:1px solid #d7e1e9;padding:6px}
QListWidget::item {padding:10px}
QListWidget::item:selected {background:#d8edf4;color:#07566f}
QProgressBar {border:1px solid #d2dfe6;border-radius:3px;text-align:center;background:white}
QProgressBar::chunk {background:#1689a7}
QComboBox,QDoubleSpinBox,QLineEdit {padding:5px;background:white;color:#213547}
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SlipSurfaceIQ-FEA · Masaüstü")
        self.resize(1280, 840)
        self.model = self.result = None
        self.path = None
        self.worker = None
        self.dirty = False
        self._closing = False
        self.setStyleSheet(_STYLE)
        self._actions()
        root = QWidget()
        layout = QVBoxLayout(root)
        title = QLabel("SlipSurfaceIQ  /  SONLU ELEMANLAR")
        title.setStyleSheet("font-size:22px;font-weight:600;padding:12px;color:#124d65")
        layout.addWidget(title)
        split = QSplitter()
        sidebar = QWidget()
        left = QVBoxLayout(sidebar)
        left.addWidget(QLabel("ANALİZ AŞAMALARI"))
        self.stages = QListWidget()
        self.stages.currentRowChanged.connect(self.draw)
        left.addWidget(self.stages)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("padding:12px;line-height:1.4;color:#526677")
        left.addWidget(self.summary)
        split.addWidget(sidebar)
        view = QWidget()
        right = QVBoxLayout(view)
        selectors = QHBoxLayout()
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
        selectors.addWidget(QLabel("Alan"))
        selectors.addWidget(self.fields)
        selectors.addWidget(QLabel("Deformasyon ×"))
        selectors.addWidget(self.deform)
        selectors.addStretch()
        right.addLayout(selectors)
        self.canvas = MeshCanvas()
        self.canvas.queried.connect(self.statusBar().showMessage)
        right.addWidget(self.canvas, 1)
        self.legend = QLabel("")
        self.legend.setStyleSheet("padding:8px;color:#526677")
        right.addWidget(self.legend)
        split.addWidget(view)
        split.setSizes([250, 1000])
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
        self.statusBar().showMessage("Hazır · Birimler kN, m, kPa · Gerilmede çekme pozitif")
        self.set_model(sample_model())

    def _actions(self):
        toolbar = QToolBar("Çalışma alanı")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self.edit_actions = []
        self.export_actions = []

        def action(title, slot, shortcut=None):
            a = QAction(title, self)
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
        for title, slot in [("Geometri / CAD", self.edit_geometry),
                            ("Malzemeler", self.edit_materials), ("Aşamalar", self.edit_stages)]:
            a = action(title, slot)
            toolbar.addAction(a)
            self.edit_actions.append(a)
        toolbar.addSeparator()
        self.run_action = action("▶ Çöz", self.start_solve, "F5")
        self.stop_action = action("■ Durdur", self.cancel_solve)
        self.stop_action.setEnabled(False)
        toolbar.addAction(self.run_action)
        toolbar.addAction(self.stop_action)
        toolbar.addAction(action("Görünüme sığdır", lambda: self.canvas.fit_model()))
        export_menu = self.menuBar().addMenu("Sonuç aktar")
        for title, kind in [
            ("VTU / ParaView", "vtu"),
            ("Düğüm CSV", "csv"),
            ("Kiriş N–V–M CSV", "beam"),
            ("HTML rapor", "html"),
        ]:
            a = action(title, lambda checked=False, k=kind: self.export_dialog(k))
            export_menu.addAction(a)
            self.export_actions.append(a)

    @property
    def busy(self):
        return self.worker is not None

    def set_model(self, model, result=None, path=None, dirty=False):
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
                    self.plot.values.extend(r for step in snapshot.history.steps
                                            for r in step.residuals)
            self.plot.update()
            self.progress.setValue(100)
        else:
            self.progress.setValue(0)
        self.draw()

    def selected_stage(self):
        if self.result is None:
            return None
        index = self.stages.currentRow()
        return self.result.initial if index <= 0 else self.result.stages[index - 1]

    def draw(self, *_):
        if self.model is None:
            return
        st = self.selected_stage()
        self.canvas.show_model(self.model, st, self.fields.currentText(), self.deform.value())
        self.legend.setText(self.canvas.legend)
        if st is not None:
            self.statusBar().showMessage(f"{st.name} · kabul edilen λ={st.lam:.6g}")

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
        if Path(path).suffix.lower() == ".ssproj":
            project = api.load_project(path)
            self.set_model(project.model, project.results, path)
        else:
            self.set_model(api.load_model(path), path=path)

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

    def edit_materials(self):
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

    def edit_stages(self):
        dialog = StageDialog(self.model, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set_model(dialog.updated, path=self.path, dirty=True)

    def start_solve(self):
        if self.busy:
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
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("SlipSurfaceIQ-FEA")
    window = MainWindow()
    if args.project:
        try:
            window.open_path(args.project)
        except Exception as exc:
            window.show_error(str(exc))
    window.show()
    return app.exec()

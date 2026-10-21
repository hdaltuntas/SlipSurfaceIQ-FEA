"""Phase 5 desktop foundation. Run ``slipsurface [project.ssproj]``.

Qt is optional; the numerical API never imports this module. The worker uses the
same API as scripts. This first slice views existing projects; it is not a CAD editor.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from .. import api

try:
    from PySide6.QtCore import QPointF, Qt, QThread, Signal
    from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QDoubleSpinBox,
        QFileDialog,
        QGraphicsScene,
        QGraphicsView,
        QHBoxLayout,
        QLabel,
        QMainWindow,
        QMessageBox,
        QProgressBar,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:
    raise ImportError("Desktop requires: pip install 'slipsurface-fe2d[desktop]'") from exc


class SolveWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model

    def run(self):
        try:
            result = api.run(self.model)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.completed.emit(result)


class MeshView(QGraphicsView):
    """Element-constant contour preview; coordinates remain in model units."""

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setBackgroundBrush(QColor("#f5f7fa"))

    def draw(self, mesh, stage=None, values=None, deform=0.0):
        self.scene().clear()
        coords = mesh.coords.copy()
        if stage is not None:
            coords += deform * np.nan_to_num(stage.u)
        finite = np.asarray([]) if values is None else values[np.isfinite(values)]
        lo, hi = (float(finite.min()), float(finite.max())) if finite.size else (0.0, 0.0)
        orders = {
            api.ElemType.T3: [0, 1, 2], api.ElemType.T6: [0, 3, 1, 4, 2, 5],
            api.ElemType.Q4: [0, 1, 2, 3], api.ElemType.Q8: [0, 4, 1, 5, 2, 6, 3, 7],
        }
        pen = QPen(QColor("#425466"))
        pen.setCosmetic(True)
        for block in mesh.continuum_blocks():
            mask = (np.ones(block.ne, dtype=bool) if stage is None else
                    stage.active.get(block.tag, np.ones(block.ne, dtype=bool)))
            for conn in block.conn[mask]:
                xy = coords[conn[orders[block.etype]]]
                polygon = QPolygonF([QPointF(float(x), float(-y)) for x, y in xy])
                color = QColor("#cdd9e5")
                if values is not None and np.isfinite(values[conn]).any():
                    value = float(np.nanmean(values[conn]))
                    t = np.clip((value - lo) / (hi - lo), 0, 1) if hi > lo else 0.5
                    color = QColor.fromHsvF(float(0.66 * (1 - t)), 0.75, 0.95)
                self.scene().addPolygon(polygon, pen, color)
        self.fitInView(self.scene().itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio)
        return lo, hi


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SlipSurface 2D — Phase 5")
        self.resize(1100, 760)
        self.model = self.result = self.worker = None
        self.path = None
        self.view = MeshView()
        self.stage_box = QComboBox()
        self.field_box = QComboBox()
        self.field_box.addItems(["|u|", "sxx", "syy", "szz", "txy", "s1", "s3", "q"])
        self.deform = QDoubleSpinBox()
        self.deform.setRange(0, 1e6)
        self.deform.setPrefix("Deformation × ")
        self.info = QLabel("Open a .ssproj project to begin.")
        self.info.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.buttons = {}
        bar = QHBoxLayout()
        for label, action in [("Open", self.open_dialog), ("Save as", self.save_dialog),
                              ("Solve", self.start_solve), ("Export VTU", self.export_dialog)]:
            button = QPushButton(label)
            button.clicked.connect(action)
            self.buttons[label] = button
            bar.addWidget(button)
        bar.addWidget(self.stage_box)
        bar.addWidget(self.field_box)
        bar.addWidget(self.deform)
        layout = QVBoxLayout()
        layout.addLayout(bar)
        layout.addWidget(self.view, 1)
        layout.addWidget(self.info)
        layout.addWidget(self.progress)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)
        self.stage_box.currentIndexChanged.connect(self.refresh)
        self.field_box.currentIndexChanged.connect(self.refresh)
        self.deform.valueChanged.connect(self.refresh)
        self.set_busy(False)

    def set_busy(self, busy):
        self.buttons["Open"].setEnabled(not busy)
        for label in ("Save as", "Solve"):
            self.buttons[label].setEnabled(not busy and self.model is not None)
        self.buttons["Export VTU"].setEnabled(not busy and self.result is not None)
        self.progress.setRange(0, 0 if busy else 1)
        if not busy:
            self.progress.setValue(int(self.result is not None))

    def open_project(self, path):
        project = api.load_project(path)
        self.model, self.result, self.path = project.model, project.results, Path(path)
        self.setWindowTitle(f"SlipSurface 2D — {self.path.name}")
        self.populate_stages()
        self.set_busy(False)

    def populate_stages(self):
        self.stage_box.blockSignals(True)
        self.stage_box.clear()
        if self.result is not None:
            self.stage_box.addItems([s.name for s in self.result.stages] or ["Initial state"])
            self.stage_box.setCurrentIndex(self.stage_box.count() - 1)
        self.stage_box.blockSignals(False)
        self.refresh()

    def refresh(self):
        if self.model is None:
            return
        if self.result is None:
            self.view.draw(self.model.mesh)
            self.info.setText(
                f"{self.model.mesh.nn} nodes · {len(self.model.stages)} stages · unsolved"
            )
            return
        index = self.stage_box.currentIndex() if self.result.stages else None
        stage = self.result.last if index is None else self.result.stage(index)
        field = self.field_box.currentText()
        if field == "|u|":
            values = np.linalg.norm(stage.u, axis=1)
            unit = "m"
        else:
            from ..post.recovery import principal_stresses
            stress = api.nodal_stress(self.result, index)
            names = ["sxx", "syy", "szz", "txy"]
            values = (stress[:, names.index(field)] if field in names else
                      principal_stresses(stress)[field])
            unit = "kPa"
        lo, hi = self.view.draw(self.model.mesh, stage, values, self.deform.value())
        self.info.setText(
            f"{stage.name} · {field}: {lo:.6g} … {hi:.6g} {unit} · "
            "element-average preview; VTU retains nodal values. Structures are not drawn yet."
        )

    def start_solve(self):
        if self.model is None or (self.worker is not None and self.worker.isRunning()):
            return
        self.set_busy(True)
        self.info.setText("Solving in background…")
        self.worker = SolveWorker(self.model, self)
        self.worker.completed.connect(self.solved)
        self.worker.failed.connect(self.failed)
        self.worker.finished.connect(self.solve_finished)
        self.worker.start()

    def solved(self, result):
        self.result = result
        self.populate_stages()

    def failed(self, message):
        self.info.setText(
            f"Solve failed: {message}. Any displayed results are from the previous run."
        )

    def solve_finished(self):
        self.set_busy(False)
        self.worker.deleteLater()
        self.worker = None

    def open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open project", "", "SlipSurface (*.ssproj)")
        if path:
            self.file_action(lambda: self.open_project(path))

    def save_dialog(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save project", "", "SlipSurface (*.ssproj)")
        if path:
            self.file_action(lambda: api.save_project(Path(path).with_suffix(".ssproj"),
                                                     self.model, self.result))

    def export_dialog(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export results", "", "VTK (*.vtu)")
        if path:
            index = self.stage_box.currentIndex() if self.result.stages else None
            self.file_action(lambda: api.export_vtu(self.result, Path(path).with_suffix(".vtu"),
                                                   stage=index))

    def file_action(self, action):
        try:
            action()
        except Exception as exc:
            QMessageBox.critical(self, "Project error", str(exc))

    def closeEvent(self, event):
        # Never destroy a live QThread or terminate a solver in the middle of a commit.
        if self.worker is not None and self.worker.isRunning():
            self.info.setText("Wait for the current solve before closing.")
            event.ignore()
        else:
            event.accept()


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    if len(sys.argv) > 1:
        window.file_action(lambda: window.open_project(sys.argv[1]))
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

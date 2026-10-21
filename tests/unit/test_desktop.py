"""Optional Qt integration: real project, real worker, API parity and failure recovery."""

from dataclasses import replace

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from slipsurface.fe2d import api
from slipsurface.fe2d.gui.desktop import MainWindow
from slipsurface.fe2d.mesh import rectangle


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def model():
    return api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=rectangle(2, 1, 2, 1, api.ElemType.Q4),
        materials={"s": api.MaterialSpec.elastic("s", 1e4, 0.3)},
        region_material={1: "s"},
        fixities=(api.Fixity("bottom", True, True),),
        initial=api.InitialStress("none"),
        stages=[api.Stage("load", loads=(api.EdgeLoad("top", qn=10),))],
    )


def wait_worker(window):
    loop = QEventLoop()
    window.worker.finished.connect(loop.quit)
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(30000)
    loop.exec()
    assert timer.isActive(), "worker exceeded 30 seconds"
    timer.stop()
    QApplication.processEvents()
    assert window.worker is None


def test_project_worker_matches_script_and_renders(app, tmp_path):
    m = model()
    expected = api.run(m)
    path = api.save_project(tmp_path / "model.ssproj", m)
    window = MainWindow()
    window.open_project(path)
    window.show()
    app.processEvents()
    assert window.result is None
    assert len(window.view.scene().items()) == 2
    window.start_solve()
    assert not window.buttons["Open"].isEnabled()
    assert not window.buttons["Solve"].isEnabled()
    wait_worker(window)
    np.testing.assert_allclose(window.result.last.u, expected.last.u, rtol=0, atol=0)
    np.testing.assert_allclose(window.result.last.sig["soil"], expected.last.sig["soil"])
    assert window.stage_box.currentText() == "load"
    window.field_box.setCurrentText("syy")
    window.deform.setValue(10)
    assert "kPa" in window.info.text()
    assert window.grab().save(str(tmp_path / "desktop.png"))
    assert window.buttons["Export VTU"].isEnabled()
    window.close()


def test_failed_worker_restores_controls(app, tmp_path):
    window = MainWindow()
    window.model = replace(model(), region_material={1: "missing"})
    window.start_solve()
    wait_worker(window)
    assert "Solve failed:" in window.info.text()
    assert window.buttons["Open"].isEnabled()
    assert window.buttons["Solve"].isEnabled()
    assert not window.buttons["Export VTU"].isEnabled()
    window.close()


def test_excavated_cells_hidden_and_initial_only_project(app, tmp_path):
    m = replace(model(), stages=[])
    result = api.run(m)
    result.initial.active["soil"][:] = False
    path = api.save_project(tmp_path / "initial.ssproj", m, result)
    window = MainWindow()
    window.open_project(path)
    assert window.stage_box.currentText() == "Initial state"
    assert not window.view.scene().items()
    window.field_box.setCurrentText("sxx")
    window.close()

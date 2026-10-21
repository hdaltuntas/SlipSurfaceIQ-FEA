"""Real Qt events: author a polygon, undo/redo, worker equality and cancellation."""

import os
import time
from dataclasses import replace

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("shapely")
pytest.importorskip("ezdxf")
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from slipsurface.fe2d import api
from slipsurface.fe2d.cad.geometry import Drawing, Entity
from slipsurface.fe2d.gui.cad import CadDialog


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def finish(dialog, app):
    until = time.monotonic() + 30
    while dialog.worker is not None and time.monotonic() < until:
        app.processEvents()
        QTest.qWait(10)
    assert dialog.worker is None
    app.processEvents()


def test_mouse_polygon_undo_redo_and_invalid_edit(app):
    w = CadDialog()
    w.show()
    app.processEvents()
    w.canvas.fit_drawing()
    w.name.setText("drawn")
    w.begin_drawing()
    points = [(0, 0), (8, 0), (8, 4), (0, 4)]
    for x, y in points:
        QTest.mouseClick(
            w.canvas.viewport(),
            Qt.MouseButton.LeftButton,
            pos=w.canvas.mapFromScene(QPointF(x, -y)),
        )
    QTest.keyClick(w.canvas, Qt.Key.Key_Return)
    assert w.document.entities[0].points == tuple(points)
    w.undo()
    assert not w.document.entities
    w.redo()
    assert w.document.entities[0].name == "drawn"
    w.entities.setCurrentRow(0)
    w.coordinates.setPlainText("0 0\n8 4\n0 4\n8 0")
    w.update_entity()
    assert w.document.entities[0].points == tuple(points)
    assert "tamamlanamadı" in w.status.text()
    w.close()


def test_worker_build_solve_and_authoring_roundtrip(app, tmp_path):
    d = replace(Drawing.example(), h=2)
    w = CadDialog()
    w.commit(d)
    w.start_mesh()
    assert not w.editor.isEnabled()
    finish(w, app)
    assert w.result() == QDialog.DialogCode.Accepted, w.status.text()
    direct = api.run(d.build_model())
    gui = api.run(w.updated)
    assert np.array_equal(gui.last.u, direct.last.u)
    path = tmp_path / "drawing.ssproj"
    api.save_project(w.updated, path, gui)
    reopened = CadDialog(api.load_project(path).model)
    assert reopened.current_drawing() == d
    assert reopened.conditions.rowCount() == 4
    reopened.close()


def test_edit_clears_affected_edge_conditions_and_undo_restores(app):
    w = CadDialog()
    d = Drawing.example()
    w.commit(d)
    w.entities.setCurrentRow(0)
    w.name.setText("renamed")
    w.update_entity()
    assert not w.document.rules
    assert w.document.entities[0].name == "renamed"
    w.undo()
    assert w.document == d
    w.close()


def test_cancel_and_failure_preserve_input_and_restore_controls(app, monkeypatch):
    w = CadDialog()
    d = Drawing.example()
    w.commit(d)

    def slow(self, checkpoint=None):
        for _ in range(100):
            time.sleep(0.005)
            checkpoint()

    monkeypatch.setattr(Drawing, "build_model", slow)
    w.start_mesh()
    w.reject()
    finish(w, app)
    assert w.updated is None
    assert w.document == d
    assert w.result() == QDialog.DialogCode.Rejected

    def fail(*args, **kwargs):
        raise RuntimeError("mesh regression")

    monkeypatch.setattr(Drawing, "build_model", fail)
    other = CadDialog()
    other.commit(d)
    other.start_mesh()
    finish(other, app)
    assert other.updated is None
    assert "mesh regression" in other.status.text()
    assert other.editor.isEnabled() and other.build_button.isEnabled()
    other.close()


def test_geometry_draft_is_independent_of_source_model(app):
    d = replace(Drawing.example(), h=2)
    model = d.build_model()
    w = CadDialog(model)
    w.add_entity(Entity("extra", "line", ((1, 1), (2, 1))))
    assert len(w.document.entities) == 2
    assert Drawing.from_dict(model.geometry) == d
    w.reject()

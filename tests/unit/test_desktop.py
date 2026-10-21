"""Offscreen native desktop acceptance: identical engine, saved data and safe cancellation."""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from slipsurface.fe2d import api
from slipsurface.fe2d.gui.app import MainWindow
from slipsurface.fe2d.gui.dialogs import StageDialog, sample_model


@pytest.fixture(scope="module")
def application():
    return QApplication.instance() or QApplication([])


def finish(window, application, timeout=30):
    end = time.monotonic() + timeout
    while window.busy and time.monotonic() < end:
        application.processEvents()
        QTest.qWait(10)
    assert not window.busy, "worker did not stop"
    application.processEvents()


def test_native_solve_equals_script_and_project_roundtrip(application, tmp_path):
    window = MainWindow()
    window.set_model(sample_model(nx=2, ny=2))
    window.show()
    expected = api.run(window.model)
    window.start_solve()
    assert not window.run_action.isEnabled()
    finish(window, application)
    assert window.result is not None, window.log.toPlainText()
    assert np.array_equal(window.result.last.u, expected.last.u)
    assert np.array_equal(window.result.last.sig["soil"], expected.last.sig["soil"])
    window.fields.setCurrentText("syy")
    assert window.canvas.constant_field  # roundoff must not become a false contour
    assert window.progress.value() == 100
    assert window.plot.values
    assert window.canvas.cell_count == sum(b.ne for b in expected.model.mesh.continuum_blocks())
    path = tmp_path / "desktop.ssproj"
    window.save_path(path)
    other = MainWindow()
    other.open_path(path)
    assert np.array_equal(other.result.last.u, expected.last.u)
    assert other.selected_stage().name == expected.last.name
    assert other.plot.values
    assert other.progress.value() == 100
    window.close()
    other.close()


def test_cancel_never_becomes_success_or_retains_previous_result(application, monkeypatch):
    from slipsurface.fe2d.gui import worker

    real_run = worker.api.run

    def cancellable(model, *, progress, cancel):
        for _ in range(200):
            if cancel():
                raise api.SolveCancelled("cancelled")
            time.sleep(0.005)
        return real_run(model, progress=progress, cancel=cancel)

    window = MainWindow()
    window.set_model(sample_model(nx=1, ny=1))
    monkeypatch.setattr(worker.api, "run", cancellable)
    window.start_solve()
    window.cancel_solve()
    finish(window, application)
    assert window.result is None
    assert "iptal" in window.log.toPlainText().lower()
    assert not any(a.isEnabled() for a in window.export_actions)
    window.close()


def test_failure_restores_controls_without_result(application, monkeypatch):
    from slipsurface.fe2d.gui import worker

    def fail(*args, **kwargs):
        raise RuntimeError("regression failure")

    monkeypatch.setattr(worker.api, "run", fail)
    window = MainWindow()
    window.start_solve()
    finish(window, application)
    assert window.result is None
    assert "regression failure" in window.log.toPlainText()
    assert window.run_action.isEnabled()
    window.close()


def test_stage_editor_preserves_loads_and_water(application):
    model = sample_model(nx=1, ny=1)
    dialog = StageDialog(model)
    dialog.table.item(0, 0).setText("Updated")
    dialog.table.item(0, 1).setText(".4")
    dialog.apply()
    assert dialog.updated.stages[0].load_split == 0.4
    assert dialog.updated.stages[0].loads == model.stages[0].loads
    assert dialog.updated.stages[0].water == model.stages[0].water
    assert model.stages[0].name == "Yükleme"
    dialog.close()

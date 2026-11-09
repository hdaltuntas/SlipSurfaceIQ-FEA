"""Real Qt tables/markers, stage selection, persistence and native-contact export."""

from __future__ import annotations

import copy
import csv
import os
import runpy
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("shapely")
from PySide6.QtWidgets import QFileDialog, QMessageBox

from slipsurface.fe2d import api
from slipsurface.fe2d.gui.app import MainWindow
from slipsurface.fe2d.gui.canvas import MeshCanvas
from slipsurface.fe2d.gui.contact_results import ContactResultsDialog
from slipsurface.fe2d.post.contact_results import CONTACT_FIELDS, contact_points

_BUILD = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts"
                           / "f7_contact_static_benchmark.py"))["build_model"]


@pytest.fixture(scope="module", params=["IFACE4", "IFACE6"])
def native(request):
    model, _ = _BUILD(element_type=request.param)
    return api.run(model)


@pytest.fixture(autouse=True)
def no_blocking_dialogs(monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Discard)


def test_canvas_gap_is_stored_mm_not_deformation_scale(qt_app, native):
    canvas = MeshCanvas()
    for deform in (0.0, 50.0):
        canvas.show_model(native.model, native.stages[0], "contact_gap", deform,
                          result=native, selection=("structure", "contact"))
        assert canvas.field_range == pytest.approx((6.0, 6.0))
        assert canvas.colorbar_visible and canvas.field_unit == "mm"
        assert canvas.contact_point_count == native.model.mesh.block("contact").etype.nen // 2
        assert "display only" in canvas.legend
        markers = [item for item in canvas.scene().items() if item.data(1) is not None]
        assert len(markers) == canvas.contact_point_count
        assert {tuple(item.data(1)) for item in markers} == {
            (p.tag, p.element, p.point) for p in canvas.contact_points}


def test_categorical_states_have_no_continuous_colorbar(qt_app, native):
    st = copy.deepcopy(native.last)
    n = st.contact_gap["contact"].shape[1]
    st.contact_gap["contact"][0] = [0.006, 0.0, -0.001][:n]
    st.contact_status["contact"][0] = [0, 1, 2][:n]
    st.interfaces["contact"][:] = 0
    st.interfaces["contact"][0, :, 1] = [0, 0, -2][:n]
    canvas = MeshCanvas()
    canvas.show_model(native.model, st, "contact_status", result=native)
    assert not canvas.colorbar_visible
    assert canvas.contact_point_count == n
    assert "OPEN=1" in canvas.legend and "TOUCHING=1" in canvas.legend
    assert "plastic" not in canvas.legend.lower()
    assert len({item.brush().color().name() for item in canvas.scene().items()
                if item.data(1) is not None}) == n


def test_unavailable_snapshot_has_no_zero_scalar_map(qt_app, native):
    st = copy.deepcopy(native.last)
    st.contact_gap = {}
    canvas = MeshCanvas()
    canvas.show_model(native.model, st, "contact_pressure", result=native)
    assert not canvas.colorbar_visible
    assert "UNAVAILABLE" in canvas.legend
    assert all(p.pressure_kpa is None for p in canvas.contact_points)


def test_inactive_snapshot_remains_inactive(qt_app, native):
    st = copy.deepcopy(native.last)
    st.active["contact"][:] = False
    st.contact_gap["contact"][:] = np.nan
    st.contact_status["contact"][:] = 255
    st.interfaces["contact"][:] = np.nan
    canvas = MeshCanvas()
    canvas.show_model(native.model, st, "contact_status", result=native)
    assert not canvas.colorbar_visible and "INACTIVE" in canvas.legend
    assert all(p.display_value("contact_gap") is None for p in canvas.contact_points)


def test_invalid_canvas_data_does_not_leave_stale_markers(qt_app, native):
    canvas = MeshCanvas()
    canvas.show_model(native.model, native.last, "contact_gap", result=native)
    st = copy.deepcopy(native.last)
    st.contact_status["contact"][:] = 99
    canvas.show_model(native.model, st, "contact_gap", result=native)
    assert canvas.contact_point_count == 0
    assert not canvas.colorbar_visible
    assert "rejected" in canvas.legend


def test_table_changes_stage_and_preserves_point_identity(qt_app, native):
    dialog = ContactResultsDialog(native, 1, "contact")
    assert dialog.table.item(0, 7).text() == "6"
    assert dialog.table.item(0, 9).text() == "OPEN"
    dialog.stage.setCurrentIndex(2)
    assert dialog.table.item(0, 7).text() == "5"
    dialog.stage.setCurrentIndex(5)
    assert dialog.table.item(0, 9).text() == "COMPRESSED"
    assert float(dialog.table.item(0, 7).text()) < 0
    assert float(dialog.table.item(0, 8).text()) > 0
    assert int(dialog.table.item(0, 3).text()) == native.model.mesh.block("contact").conn[0, 0]


def test_table_handles_missing_and_rejects_invalid_state(qt_app, native):
    result = copy.deepcopy(native)
    result.last.contact_gap.clear()
    dialog = ContactResultsDialog(result, len(result.stages), "contact")
    assert dialog.table.item(0, 7).text() == "—"
    assert dialog.table.item(0, 9).text() == "UNAVAILABLE"
    result.last.contact_status["contact"][:] = 99
    dialog.refresh()
    assert dialog.table.rowCount() == 0 and dialog.points == ()
    assert not dialog.csv_button.isEnabled()
    assert "rejected" in dialog.status.text()


def test_dialog_csv_selected_stage_and_all_stages(qt_app, native, tmp_path, monkeypatch):
    dialog = ContactResultsDialog(native, 2, "contact")
    path = tmp_path / "contact.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: (str(path), "CSV"))
    dialog.csv_button.click()
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert {row["stage"] for row in rows} == {native.stages[1].name}
    assert all(float(row["gap_m"]) == pytest.approx(0.005) for row in rows)
    dialog.all_csv_button.click()
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == len(contact_points(native)) * (len(native.stages) + 1)


def test_dialog_cancel_export_preserves_existing_file(qt_app, native, tmp_path, monkeypatch):
    path = tmp_path / "existing.csv"
    path.write_text("unchanged", encoding="utf-8")
    dialog = ContactResultsDialog(native, 1)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: ("", ""))
    dialog.csv_button.click()
    assert path.read_text(encoding="utf-8") == "unchanged"


def test_mainwindow_contact_fields_and_click_routing(qt_app, native, monkeypatch):
    window = MainWindow()
    window.set_model(native.model, native)
    for field in CONTACT_FIELDS:
        window.fields.setCurrentText(field)
        assert window.canvas.contact_point_count == len(contact_points(native))
    window.result_objects.setCurrentIndex(window.result_objects.findData("structure:contact"))
    assert window.chart_button.isEnabled()
    opened = []
    monkeypatch.setattr(window, "show_contact_results", opened.append)
    window.chart_button.click()
    assert opened == ["contact"]
    window.result_objects.setCurrentIndex(window.result_objects.findData("region:1"))
    for field in CONTACT_FIELDS:
        assert not window.fields.model().item(window.fields.findText(field)).isEnabled()
    assert window.fields.currentText() == "|u|"
    window.close()


def test_goodman_cannot_be_selected_as_contact_results(qt_app, native):
    result = copy.deepcopy(native)
    result.model.interfaces["contact"] = api.InterfaceSpec("legacy", 2000, 0)
    window = MainWindow()
    window.set_model(result.model, result)
    window.result_objects.setCurrentIndex(window.result_objects.findData("structure:contact"))
    assert not window.chart_button.isEnabled()
    for field in CONTACT_FIELDS:
        assert not window.fields.model().item(window.fields.findText(field)).isEnabled()
    dialog = ContactResultsDialog(result, 1)
    assert dialog.table.rowCount() == 0
    assert "Goodman" in dialog.status.text()
    window.close()


def test_restored_project_view_and_actual_evidence(qt_app, native, tmp_path):
    path = tmp_path / "contact.ssproj"
    api.save_project(native.model, path, native)
    restored = api.load_project(path).results
    dialog = ContactResultsDialog(restored, 2, "contact")
    assert dialog.table.item(0, 7).text() == "5"
    assert dialog.table.item(0, 9).text() == "OPEN"
    # Actual Qt captures and a working solved project, not a generated mock-up.
    output = os.environ.get("CONTACT_RESULTS_EVIDENCE_DIR")
    if output and restored.model.mesh.block("contact").etype is api.ElemType.IFACE6:
        from slipsurface.fe2d.io.report import export_contact_csv

        root = Path(output)
        root.mkdir(parents=True, exist_ok=True)
        dialog.show()
        qt_app.processEvents()
        assert dialog.grab().save(str(root / "contact-table-open.png"))
        dialog.stage.setCurrentIndex(5)
        qt_app.processEvents()
        assert dialog.grab().save(str(root / "contact-table-closed.png"))
        canvas = MeshCanvas()
        canvas.resize(900, 600)
        canvas.show_model(restored.model, restored.last, "contact_status", result=restored,
                          selection=("structure", "contact"))
        canvas.show()
        canvas.fit_model()
        qt_app.processEvents()
        assert canvas.grab().save(str(root / "contact-status-canvas.png"))
        api.save_project(restored.model, root / "normal-contact-results.ssproj", restored)
        export_contact_csv(restored, root / "all-contact-stages.csv", all_stages=True)


def test_independent_interpret_window_uses_its_own_stage_and_contact_data(qt_app, native):
    window = MainWindow()
    window.set_model(native.model, native)
    window.open_interpret()
    dialog = window._interpret_window
    tabs, fields, canvas, legend, deform, principal = dialog.viewer
    fields.setCurrentText("contact_gap")
    tabs.setCurrentIndex(2)
    assert canvas.field_range == pytest.approx((5.0, 5.0))
    assert not principal.isEnabled()
    deform.setValue(25.0)
    assert canvas.field_range == pytest.approx((5.0, 5.0))
    dialog.query_button.click()
    assert dialog.contact_dialog.stage.currentIndex() == 2
    assert dialog.contact_dialog.table.item(0, 7).text() == "5"
    assert "stored interface points" in legend.text()
    dialog.close()
    window.close()

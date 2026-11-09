"""Actual Qt history plots, selection, missing-stage breaks and native persistence."""

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
from PySide6.QtWidgets import QFileDialog

from slipsurface.fe2d import api
from slipsurface.fe2d.gui.contact_history import ContactHistoryDialog
from slipsurface.fe2d.gui.contact_results import ContactResultsDialog
from slipsurface.fe2d.io.contact_history_csv import export_contact_history_csv

_BUILD = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts"
                           / "f7_contact_static_benchmark.py"))["build_model"]


@pytest.fixture(scope="module", params=["IFACE4", "IFACE6"])
def native(request):
    model, _ = _BUILD(element_type=request.param)
    return api.run(model)


def test_table_routes_exact_point_and_current_stage_to_history(qt_app, native):
    dialog = ContactResultsDialog(native, 2, "contact")
    dialog.table.setCurrentCell(1, 0)
    assert dialog.history_button.isEnabled()
    dialog.history_button.click()
    history = dialog._history_window
    assert history.identity == ("contact", 0, 1)
    assert history.table.currentRow() == 2
    assert history.table.rowCount() == 8
    assert history.table.item(1, 3).text() == "6"
    assert history.table.item(2, 3).text() == "5"
    assert history.table.item(2, 4).text() in ("0", "-0")
    assert "face nodes" in history.identity_label.text()
    history.table.setCurrentCell(5, 0)
    assert history.gap_plot.selected_stage == history.pressure_plot.selected_stage == 5
    assert dialog.stage.currentIndex() == 2  # history inspection cannot switch owner stage
    assert history.table.item(5, 5).text() == "COMPRESSED"
    assert float(history.table.item(5, 3).text()) < 0
    assert float(history.table.item(5, 4).text()) > 0


def test_stage_change_keeps_selected_mesh_point(qt_app, native):
    dialog = ContactResultsDialog(native, 1, "contact")
    dialog.table.setCurrentCell(1, 0)
    dialog.stage.setCurrentIndex(5)
    assert dialog.selected_point().point == 1
    dialog.history_button.click()
    assert dialog._history_window.identity == ("contact", 0, 1)
    assert dialog._history_window.table.currentRow() == 5


def test_unavailable_and_inactive_history_samples_are_graph_breaks(qt_app, native):
    result = copy.deepcopy(native)
    result.stages[1].contact_gap.clear()
    st = result.stages[3]
    st.active["contact"][:] = False
    st.contact_gap["contact"][:] = np.nan
    st.contact_status["contact"][:] = 255
    st.interfaces["contact"][:] = np.nan
    history = ContactHistoryDialog(result, "contact", 0, 0)
    assert history.table.item(2, 3).text() == "—"
    assert history.table.item(2, 5).text() == "UNAVAILABLE"
    assert history.table.item(4, 5).text() == "INACTIVE"
    assert [[i for i, _ in part] for part in history.gap_plot.segments] == [
        [0, 1], [3], [5, 6, 7]]
    history.show()
    qt_app.processEvents()
    assert not history.grab().isNull()


def test_all_missing_points_show_empty_graph_not_zero(qt_app, native):
    result = copy.deepcopy(native)
    for st in [result.initial, *result.stages]:
        st.contact_gap.clear()
    history = ContactHistoryDialog(result, "contact", 0, 0)
    assert history.gap_plot.segments == history.pressure_plot.segments == ()
    assert history.table.rowCount() == 8
    assert "0/8" in history.status.text()
    history.show()
    qt_app.processEvents()
    assert not history.grab().isNull()


def test_invalid_late_stage_clears_previous_graph_and_disables_export(qt_app, native):
    result = copy.deepcopy(native)
    history = ContactHistoryDialog(result, "contact", 0, 0)
    result.last.contact_status["contact"][:] = 99
    history.refresh()
    assert history.table.rowCount() == 0
    assert history.history == ()
    assert history.gap_plot.segments == history.pressure_plot.segments == ()
    assert not history.csv_button.isEnabled()
    assert "rejected" in history.status.text()


def test_repeated_stage_names_remain_distinct_table_rows(qt_app, native):
    result = copy.deepcopy(native)
    for st in [result.initial, *result.stages]:
        st.name = "same <stage>"
        st.lam = 0.5
    history = ContactHistoryDialog(result, "contact", 0, 0)
    assert [history.table.item(i, 0).text() for i in range(8)] == list(map(str, range(8)))
    assert all(history.table.item(i, 1).text() == "same <stage>" for i in range(8))
    assert all(history.table.item(i, 2).text() == "0.5" for i in range(8))


def test_csv_button_writes_single_point_history_in_metres(qt_app, native, monkeypatch, tmp_path):
    dialog = ContactHistoryDialog(native, "contact", 0, 1)
    path = tmp_path / "history.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: (str(path), "CSV"))
    dialog.csv_button.click()
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 8
    assert all(row["point"] == "1" for row in rows)
    assert float(rows[1]["gap_m"]) == pytest.approx(0.006)
    assert "Exported" in dialog.status.text()
    path.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: ("", ""))
    dialog.csv_button.click()
    assert path.read_text(encoding="utf-8") == "keep"


def test_invalid_history_export_preserves_existing_destination(
    qt_app, native, monkeypatch, tmp_path,
):
    result = copy.deepcopy(native)
    dialog = ContactHistoryDialog(result, "contact", 0, 0)
    path = tmp_path / "history.csv"
    path.write_bytes(b"keep")
    result.last.contact_gap["contact"][:] = np.nan
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: (str(path), "CSV"))
    dialog.csv_button.click()
    assert path.read_bytes() == b"keep"
    assert "rejected" in dialog.status.text()


def test_goodman_history_is_not_fabricated(qt_app, native):
    result = copy.deepcopy(native)
    result.model.interfaces["contact"] = api.InterfaceSpec("goodman", 2000, 0)
    dialog = ContactResultsDialog(result)
    assert not dialog.history_button.isEnabled()
    history = ContactHistoryDialog(result, "contact", 0, 0)
    assert history.table.rowCount() == 0
    assert not history.csv_button.isEnabled()


def test_restored_native_history_and_actual_dialog_evidence(qt_app, native, tmp_path):
    project = tmp_path / "history.ssproj"
    api.save_project(native.model, project, native)
    restored = api.load_project(project).results
    dialog = ContactHistoryDialog(restored, "contact", 0, 0, 5)
    assert dialog.table.item(2, 3).text() == "5"
    assert dialog.table.item(5, 5).text() == "COMPRESSED"
    output = os.environ.get("CONTACT_RESULTS_EVIDENCE_DIR")
    if output and restored.model.mesh.block("contact").etype is api.ElemType.IFACE6:
        root = Path(output)
        root.mkdir(parents=True, exist_ok=True)
        dialog.show()
        qt_app.processEvents()
        assert dialog.grab().save(str(root / "contact-point-history.png"))
        export_contact_history_csv(restored, root / "contact-point-history.csv", "contact", 0, 0)
        broken = copy.deepcopy(restored)
        broken.stages[1].contact_gap.clear()
        missing = ContactHistoryDialog(broken, "contact", 0, 0, 2)
        missing.show()
        qt_app.processEvents()
        assert missing.grab().save(str(root / "contact-history-missing.png"))

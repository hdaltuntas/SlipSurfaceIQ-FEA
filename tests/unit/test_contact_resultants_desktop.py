"""Actual Qt interface totals, moment origin, selection, CSV and missing evidence."""

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
from slipsurface.fe2d.gui.contact_resultants import ContactResultantsDialog
from slipsurface.fe2d.gui.contact_results import ContactResultsDialog
from slipsurface.fe2d.io.contact_resultants_csv import export_contact_resultants_csv

_BUILD = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts"
                           / "f7_contact_static_benchmark.py"))["build_model"]


@pytest.fixture(scope="module", params=["IFACE4", "IFACE6"])
def native(request):
    model, _ = _BUILD(element_type=request.param)
    return api.run(model)


def test_parent_routes_tag_and_exact_stage_without_changing_parent(qt_app, native):
    parent = ContactResultsDialog(native, 2, "contact")
    assert parent.resultants_button.isEnabled()
    parent.resultants_button.click()
    summary = parent._resultants_window
    assert summary.stage.currentIndex() == 2
    assert summary.interface.currentData() == "contact"
    assert summary.table.rowCount() == 1
    assert float(summary.table.item(0, 5).text()) == 0
    summary.stage.setCurrentIndex(5)
    assert parent.stage.currentIndex() == 2
    assert float(summary.table.item(0, 10).text()) > 0
    assert summary.table.item(0, 1).text() == "available"


def test_origin_edits_clear_stale_values_and_change_only_moment(qt_app, native):
    dialog = ContactResultantsDialog(native, 5)
    before = dialog.summaries[0]
    dialog.origin_x.setText("3")
    assert dialog.table.rowCount() == 0
    assert not dialog.csv_button.isEnabled()
    dialog.apply_button.click()
    after = dialog.summaries[0]
    assert after.face2.fy == before.face2.fy
    assert after.face2.moment == pytest.approx(before.face2.moment - 3*before.face2.fy)
    assert dialog.csv_button.isEnabled()
    assert "(3, 0)" in dialog.status.text()


@pytest.mark.parametrize("value", ["", "not a number", "nan", "inf"])
def test_invalid_origin_rejects_display_and_export(qt_app, native, value):
    dialog = ContactResultantsDialog(native, 5)
    dialog.origin_y.setText(value)
    dialog.apply_button.click()
    assert "rejected" in dialog.status.text()
    assert dialog.table.rowCount() == 0
    assert not dialog.csv_button.isEnabled()
    assert not dialog.all_csv_button.isEnabled()


def test_missing_active_evidence_is_visible_not_false_zero(qt_app, native):
    result = copy.deepcopy(native)
    result.last.contact_gap.clear()
    dialog = ContactResultantsDialog(result, 7)
    assert dialog.table.item(0, 1).text() == "unavailable"
    assert dialog.table.item(0, 10).text() == "—"
    assert dialog.table.item(0, 5).text() == "—"
    assert dialog.all_csv_button.isEnabled()  # deliberate export of blank evidence


def test_bad_data_rejects_totals_instead_of_showing_stale_stage(qt_app, native):
    result = copy.deepcopy(native)
    dialog = ContactResultantsDialog(result, 2)
    result.last.interfaces["contact"][:] = np.nan
    dialog.stage.setCurrentIndex(7)
    assert dialog.table.rowCount() == 0
    assert not dialog.csv_button.isEnabled()
    assert "rejected" in dialog.status.text()


def test_csv_selects_exact_stage_and_both_force_signs(qt_app, native, tmp_path, monkeypatch):
    dialog = ContactResultantsDialog(native, 5)
    path = tmp_path / "resultants.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: (str(path), "CSV"))
    dialog.csv_button.click()
    with path.open(newline="", encoding="utf-8") as stream:
        row, = list(csv.DictReader(stream))
    assert row["stage_index"] == "5"
    assert float(row["face2_action_Fy_kN_per_m"]) > 0
    assert float(row["face2_internal_Fy_kN_per_m"]) < 0
    dialog.all_csv_button.click()
    with path.open(newline="", encoding="utf-8") as stream:
        assert len(list(csv.DictReader(stream))) == 8


def test_export_failure_preserves_old_file(qt_app, native, tmp_path, monkeypatch):
    result = copy.deepcopy(native)
    dialog = ContactResultantsDialog(result, 2)
    path = tmp_path / "keep.csv"
    path.write_bytes(b"keep original")
    result.last.contact_status["contact"][:] = 42
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: (str(path), "CSV"))
    dialog.all_csv_button.click()
    assert path.read_bytes() == b"keep original"
    assert "rejected" in dialog.status.text()


def test_cancel_export_does_not_modify_model_or_file(qt_app, native, monkeypatch):
    before = native.last.contact_gap["contact"].copy()
    dialog = ContactResultantsDialog(native, 5)
    text = dialog.status.text()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: ("", "CSV"))
    dialog.all_csv_button.click()
    assert dialog.status.text() == text
    np.testing.assert_array_equal(native.last.contact_gap["contact"], before)


def test_goodman_has_no_fabricated_totals(qt_app, native):
    result = copy.deepcopy(native)
    result.model.interfaces["contact"] = api.InterfaceSpec("legacy", 2000, 0)
    parent = ContactResultsDialog(result)
    assert not parent.resultants_button.isEnabled()
    dialog = ContactResultantsDialog(result)
    assert dialog.table.rowCount() == 0
    assert not dialog.csv_button.isEnabled()


def test_actual_resultant_dialog_artifacts_from_restored_native_model(qt_app, native, tmp_path):
    path = tmp_path / "resultants.ssproj"
    api.save_project(native.model, path, native)
    restored = api.load_project(path).results
    dialog = ContactResultantsDialog(restored, 5, "contact")
    row = dialog.summaries[0]
    assert row.face2.fy > 0 > row.face1.fy
    assert float(dialog.table.item(0, 11).text()) == pytest.approx(row.face2.moment)
    output = os.environ.get("CONTACT_RESULTS_EVIDENCE_DIR")
    if output and restored.model.mesh.block("contact").etype is api.ElemType.IFACE6:
        root = Path(output)
        root.mkdir(parents=True, exist_ok=True)
        dialog.show()
        qt_app.processEvents()
        assert dialog.grab().save(str(root / "contact-resultants.png"))
        export_contact_resultants_csv(restored, root / "contact-resultants.csv")
        broken = copy.deepcopy(restored)
        broken.last.contact_gap.clear()
        missing = ContactResultantsDialog(broken, 7, "contact")
        missing.show()
        qt_app.processEvents()
        assert missing.grab().save(str(root / "contact-resultants-missing.png"))

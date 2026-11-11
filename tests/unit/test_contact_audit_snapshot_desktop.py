"""Actual Qt snapshot resource limits, memory release and unchanged verdicts."""

from __future__ import annotations

import copy
import json
import os
import pickle
import runpy
import threading
import time
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from slipsurface.fe2d import api
from slipsurface.fe2d.gui import contact_audit as gui
from slipsurface.fe2d.post import contact_audit_snapshot as snapshots
from slipsurface.fe2d.post.contact_audit_control import ContactAuditCancelled
from slipsurface.fe2d.post.contact_audit_report import prepare_contact_audit

_B = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts"
                       / "f7_contact_topology_benchmark.py"))


@pytest.fixture(scope="module", params=["IFACE4", "IFACE6"])
def native(request):
    return api.run(_B["asymmetric_model"](element_type=request.param))


def until(app, predicate):
    deadline = time.monotonic() + 10
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.002)
    app.processEvents()
    assert predicate(), "Qt snapshot/resource lifecycle timed out"


def test_native_worker_omits_cache_and_releases_input_after_success(qt_app, native):
    before = pickle.dumps(native)
    worker = gui.ContactAuditWorker(native, (0., 0.), qt_app)
    assert worker.snapshot is not native and worker.snapshot.geom == {}
    assert worker.snapshot_plan == snapshots.plan_contact_audit_snapshot(native)
    worker.start()
    assert worker.wait(10000)
    assert worker.document == prepare_contact_audit(native)
    assert worker.snapshot is None and not worker.cancelled and worker.error is None
    assert pickle.dumps(native) == before
    worker.deleteLater()


@pytest.mark.parametrize("outcome", ["pre_cancel", "cancel", "error"])
def test_every_worker_exit_releases_detached_input(qt_app, native, monkeypatch, outcome):
    def stop(*args, **kwargs):
        if outcome == "cancel":
            raise ContactAuditCancelled("test checkpoint")
        raise RuntimeError("test execution failure")

    monkeypatch.setattr(gui, "prepare_contact_audit", stop)
    worker = gui.ContactAuditWorker(native, (0., 0.), qt_app)
    if outcome == "pre_cancel":
        worker.cancel_event.set()
    worker.start()
    assert worker.wait(10000)
    assert worker.snapshot is None and worker.document is None
    assert worker.cancelled is (outcome != "error")
    assert bool(worker.error) is (outcome == "error")
    worker.deleteLater()


def test_gui_refuses_large_copy_then_allows_explicit_higher_limit(qt_app, native):
    result = copy.deepcopy(native)
    # Numeric authoring metadata is preserved by the input copier but not read by
    # the FEM audit. A small 2 MiB allocation exercises a real 1 MiB refusal.
    result.model.geometry = {"native_test_metadata": np.zeros(262144, dtype=np.float64)}
    before = pickle.dumps(result)
    dialog = gui.ContactAuditDialog(result)
    dialog.show()
    assert dialog.array_limit.value() == 512
    dialog.array_limit.setValue(1)
    dialog.run_button.click()
    assert dialog.worker is None and dialog.document is None and not gui._PENDING
    assert dialog.table.rowCount() == 0 and not dialog.export_button.isEnabled()
    assert "No input copy was allocated" in dialog.status.text()
    assert dialog.run_button.isEnabled() and dialog.array_limit.isEnabled()
    root = os.environ.get("CONTACT_AUDIT_EVIDENCE_DIR")
    evidence = (Path(root) if root and
                native.model.mesh.block("contact").etype.name == "IFACE6" else None)
    if evidence:
        evidence.mkdir(parents=True, exist_ok=True)
        qt_app.processEvents()
        assert dialog.grab().save(str(evidence / "contact-audit-copy-limit.png"))
    dialog.array_limit.setValue(4)
    dialog.run_button.click()
    worker = dialog.worker
    assert worker is not None and not dialog.array_limit.isEnabled()
    until(qt_app, lambda: dialog.worker is None)
    assert dialog.document == prepare_contact_audit(result)
    assert dialog.array_limit.isEnabled() and dialog.export_button.isEnabled()
    assert worker.snapshot is None
    assert "not total RAM" in dialog.snapshot_info.text()
    assert pickle.dumps(result) == before
    if evidence:
        assert dialog.grab().save(str(evidence / "contact-audit-copy-ready.png"))
        full = snapshots._array_inventory(result)
        plan = worker.snapshot_plan
        (evidence / "contact-audit-copy.json").write_text(json.dumps({
            "limit_rejection_before_worker": True,
            "explicit_higher_limit_completed": dialog.document["audit"]["status"] == "passed",
            "source_unchanged": pickle.dumps(result) == before,
            "worker_input_released": worker.snapshot is None,
            "input_array_count": plan.array_count,
            "input_array_bytes": plan.array_bytes,
            "full_copy_array_bytes": full.array_bytes,
            "geometry_cache_array_bytes_avoided": full.array_bytes - plan.array_bytes,
            "total_ram_estimate": False,
        }, indent=2), encoding="utf-8")
    dialog.close()


def test_gui_preflight_refuses_before_deepcopy(qt_app, native, monkeypatch):
    result = copy.deepcopy(native)
    result.model.geometry = {"large_metadata": np.zeros(262144)}
    dialog = gui.ContactAuditDialog(result)
    dialog.array_limit.setValue(1)
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(1)
        raise AssertionError("Limit must be checked before deepcopy")

    monkeypatch.setattr(snapshots.copy, "deepcopy", forbidden)
    dialog.run_button.click()
    assert not calls and dialog.worker is None
    assert "No input copy was allocated" in dialog.status.text()
    assert not dialog.export_button.isEnabled()


def test_copy_failure_clears_old_report_and_can_retry(qt_app, native, monkeypatch):
    dialog = gui.ContactAuditDialog(native)
    dialog.run_button.click()
    until(qt_app, lambda: dialog.worker is None)
    assert dialog.document is not None
    original = snapshots.copy.deepcopy

    def exhausted(*args, **kwargs):
        raise MemoryError("simulated allocation refusal")

    monkeypatch.setattr(snapshots.copy, "deepcopy", exhausted)
    dialog.run_button.click()
    assert dialog.worker is None and dialog.document is None and not gui._PENDING
    assert dialog.table.rowCount() == 0 and not dialog.export_button.isEnabled()
    assert "allocation refusal" in dialog.status.text()
    monkeypatch.setattr(snapshots.copy, "deepcopy", original)
    dialog.run_button.click()
    until(qt_app, lambda: dialog.worker is None)
    assert dialog.document is not None


def test_resource_control_does_not_change_running_input(qt_app, native, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = gui.prepare_contact_audit

    def paused(result, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(result, **kwargs)

    monkeypatch.setattr(gui, "prepare_contact_audit", paused)
    source = copy.deepcopy(native)
    expected = prepare_contact_audit(source)
    dialog = gui.ContactAuditDialog(source)
    dialog.run_button.click()
    worker = dialog.worker
    try:
        until(qt_app, entered.is_set)
        assert not dialog.array_limit.isEnabled()
        assert worker.snapshot.geom == {}
        source.last.contact_gap.clear()
        source.geom.clear()
        dialog.array_limit.setValue(1)  # a programmatic edit cannot rewrite the input
    finally:
        release.set()
    until(qt_app, lambda: dialog.worker is None)
    assert dialog.document == expected and worker.snapshot is None

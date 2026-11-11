"""Real Qt simultaneous-window admission, explicit retry and worker cleanup."""

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
from PySide6.QtCore import QCoreApplication, QEvent

from slipsurface.fe2d import api
from slipsurface.fe2d.gui import contact_audit as gui
from slipsurface.fe2d.post import contact_audit_snapshot as snapshots
from slipsurface.fe2d.post.contact_audit_budget import ContactAuditCopyBudget
from slipsurface.fe2d.post.contact_audit_control import ContactAuditCancelled
from slipsurface.fe2d.post.contact_audit_report import prepare_contact_audit

_B = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts"
                       / "f7_contact_topology_benchmark.py"))
MIB = 1048576


@pytest.fixture(scope="module", params=["IFACE4", "IFACE6"])
def native(request):
    return api.run(_B["asymmetric_model"](element_type=request.param))


@pytest.fixture
def budget(qt_app, monkeypatch):
    assert not gui._PENDING
    pool = ContactAuditCopyBudget(MIB)
    monkeypatch.setattr(gui, "_COPY_BUDGET", pool)
    yield pool
    gui._wait_on_exit()
    qt_app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert pool.state.reserved_bytes == 0 and pool.state.reservation_count == 0


def until(app, predicate):
    deadline = time.monotonic() + 10
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.002)
    app.processEvents()
    assert predicate(), "Qt shared-budget lifecycle timed out"


def larger(native):
    result = copy.deepcopy(native)
    result.model.geometry = {"native_metadata": np.zeros(75000, dtype=np.float64)}
    plan = snapshots.plan_contact_audit_snapshot(result)
    assert MIB // 2 < plan.array_bytes < MIB
    return result, plan


def pause_first(monkeypatch):
    entered, resume = threading.Event(), threading.Event()
    original = gui.prepare_contact_audit
    calls = []

    def paused(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            entered.set()
            assert resume.wait(10), "test did not release audit checkpoint"
        return original(*args, **kwargs)

    monkeypatch.setattr(gui, "prepare_contact_audit", paused)
    return entered, resume, calls


def test_two_windows_refuse_before_copy_then_retry_after_release(qt_app, budget, native,
                                                               monkeypatch):
    result, plan = larger(native)
    before = pickle.dumps(result)
    expected = prepare_contact_audit(result)
    first, second = gui.ContactAuditDialog(result), gui.ContactAuditDialog(result)
    first.show()
    second.show()
    entered, resume, calls = pause_first(monkeypatch)
    first.run_button.click()
    worker1 = first.worker
    try:
        until(qt_app, entered.is_set)
        assert budget.state.reserved_bytes == plan.array_bytes
        with monkeypatch.context() as patch:
            def forbidden(*args):
                raise AssertionError("The second input must not be copied")
            patch.setattr(snapshots.copy, "deepcopy", forbidden)
            second.run_button.click()
        assert second.worker is None and second.document is None
        assert "Shared audit array budget exceeded" in second.status.text()
        assert not second.export_button.isEnabled() and second.table.rowCount() == 0
        assert len(calls) == 1 and budget.state.reservation_count == 1
        root = os.environ.get("CONTACT_AUDIT_EVIDENCE_DIR")
        evidence = Path(root) if root and native.model.mesh.block("contact").etype.name == (
            "IFACE6") else None
        if evidence:
            evidence.mkdir(parents=True, exist_ok=True)
            qt_app.processEvents()
            assert second.grab().save(str(evidence / "contact-audit-shared-limit.png"))
    finally:
        resume.set()
    until(qt_app, lambda: first.worker is None)
    assert budget.state.reserved_bytes == 0 and worker1.snapshot is None
    assert first.document == expected
    # No automatic retry occurred after capacity became available.
    assert second.worker is None and len(calls) == 1
    second.run_button.click()
    worker2 = second.worker
    until(qt_app, lambda: second.worker is None)
    assert second.document == expected and second.export_button.isEnabled()
    assert worker2.snapshot is None and budget.state.reservation_count == 0
    assert pickle.dumps(result) == before
    if evidence:
        second.refresh_shared_budget()
        assert second.grab().save(str(evidence / "contact-audit-shared-retry.png"))
        (evidence / "contact-audit-shared-budget.json").write_text(json.dumps({
            "per_input_array_bytes": plan.array_bytes,
            "shared_limit_bytes": MIB,
            "each_input_fits": plan.array_bytes <= MIB,
            "combined_inputs_exceed_limit": 2 * plan.array_bytes > MIB,
            "refused_before_deepcopy": True,
            "no_automatic_retry": True,
            "explicit_retry_completed": second.document == expected,
            "source_unchanged": pickle.dumps(result) == before,
            "final_reserved_bytes": budget.state.reserved_bytes,
            "final_reservations": budget.state.reservation_count,
            "total_ram_limit": False,
        }, indent=2), encoding="utf-8")
    first.close()
    second.close()


def test_explicit_shared_limit_update_is_synchronized_not_silently_reset(qt_app, budget, native,
                                                                       monkeypatch):
    result, plan = larger(native)
    first, second = gui.ContactAuditDialog(result), gui.ContactAuditDialog(result)
    entered, resume, _ = pause_first(monkeypatch)
    first.start_audit()
    try:
        until(qt_app, entered.is_set)
        second.shared_array_limit.setValue(2)
        second.shared_apply.click()
        until(qt_app, lambda: first.shared_array_limit.value() == 2)
        assert budget.state.limit_bytes == 2 * MIB
        # A new window reads the current session limit, not the default.
        third = gui.ContactAuditDialog(result)
        assert third.shared_array_limit.value() == 2
        second.start_audit()
        until(qt_app, lambda: second.worker is None)
        assert second.document is not None
        assert budget.state.reserved_bytes == plan.array_bytes
        third.close()
    finally:
        resume.set()
    until(qt_app, lambda: first.worker is None)
    assert budget.state.reserved_bytes == 0
    first.close()
    second.close()


def test_lower_limit_refusal_preserves_active_audit_and_existing_report(qt_app, budget, native,
                                                                     monkeypatch):
    budget.set_limit(4 * MIB)
    result, plan = larger(native)
    # Two pending leases alone can exceed the requested 1 MiB reduction.
    first = gui.ContactAuditWorker(result, (0., 0.), qt_app)
    second = gui.ContactAuditWorker(result, (0., 0.), qt_app)
    dialog = gui.ContactAuditDialog(native)
    expected = prepare_contact_audit(native)
    dialog.document = expected
    dialog.present()
    dialog.shared_array_limit.setValue(1)
    dialog.shared_apply.click()
    assert "Shared limit unchanged" in dialog.shared_status.text()
    assert budget.state.reserved_bytes == 2 * plan.array_bytes
    assert budget.state.limit_bytes == 4 * MIB
    assert dialog.shared_array_limit.value() == 4
    assert dialog.document == expected and dialog.export_button.isEnabled()
    for worker in (first, second):
        worker.cancel_event.set()
        worker.start()
        assert worker.wait(10000)
        worker.deleteLater()
    assert budget.state.reserved_bytes == 0
    dialog.close()


@pytest.mark.parametrize("outcome", ["success", "pre_cancel", "cancel", "error"])
def test_all_terminal_paths_release_input_and_lease(qt_app, budget, native, monkeypatch, outcome):
    if outcome in ("cancel", "error"):
        def fail(*args, **kwargs):
            if outcome == "cancel":
                raise ContactAuditCancelled("checkpoint")
            raise RuntimeError("execution failed")
        monkeypatch.setattr(gui, "prepare_contact_audit", fail)
    worker = gui.ContactAuditWorker(native, (0., 0.), qt_app)
    assert budget.state.reservation_count == 1
    if outcome == "pre_cancel":
        worker.cancel_event.set()
    worker.start()
    assert worker.wait(10000)
    assert worker.snapshot is None and budget.state.reserved_bytes == 0
    assert budget.state.reservation_count == 0
    assert (worker.document is not None) is (outcome == "success")
    assert worker.cancelled is (outcome in ("pre_cancel", "cancel"))
    worker.deleteLater()


def test_unstarted_worker_qobject_deletion_releases_with_retained_wrapper(qt_app, budget, native):
    worker = gui.ContactAuditWorker(native, (0., 0.), qt_app)
    assert worker.snapshot is not None and budget.state.reservation_count == 1
    worker.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert worker.snapshot is None  # property is Python-only; wrapper still exists
    assert budget.state.reserved_bytes == 0 and budget.state.reservation_count == 0


def test_allocation_error_returns_shared_capacity_and_clears_old_report(qt_app, budget, native,
                                                                    monkeypatch):
    dialog = gui.ContactAuditDialog(native)
    dialog.document = prepare_contact_audit(native)
    dialog.present()

    def fail(*args):
        assert budget.state.reservation_count == 1
        raise MemoryError("detached input allocation failed")

    monkeypatch.setattr(snapshots.copy, "deepcopy", fail)
    dialog.start_audit()
    assert budget.state.reserved_bytes == 0 and budget.state.reservation_count == 0
    assert dialog.worker is None and dialog.document is None
    assert not dialog.export_button.isEnabled()
    assert "allocation failed" in dialog.status.text()
    assert dialog.run_button.isEnabled()
    dialog.close()


def test_launch_failure_releases_budget_and_restores_retry(qt_app, budget, native, monkeypatch):
    def fail(self):
        raise RuntimeError("thread start rejected")

    monkeypatch.setattr(gui.ContactAuditWorker, "start", fail)
    dialog = gui.ContactAuditDialog(native)
    dialog.start_audit()
    assert budget.state.reservation_count == 0 and not gui._PENDING
    assert dialog.worker is None and dialog.document is None
    assert "thread start rejected" in dialog.status.text()
    assert dialog.run_button.isEnabled() and dialog.array_limit.isEnabled()
    assert not dialog.export_button.isEnabled()
    dialog.close()


def test_cancel_request_keeps_reservation_until_actual_checkpoint(qt_app, budget, native,
                                                               monkeypatch):
    result, plan = larger(native)
    first, second = gui.ContactAuditDialog(result), gui.ContactAuditDialog(result)
    entered, resume, _ = pause_first(monkeypatch)
    first.start_audit()
    worker = first.worker
    try:
        until(qt_app, entered.is_set)
        first.discard()
        assert budget.state.reserved_bytes == plan.array_bytes
        second.start_audit()
        assert second.worker is None and second.document is None
        assert "Shared audit" in second.status.text()
    finally:
        resume.set()
    until(qt_app, lambda: first.worker is None)
    assert worker.cancelled and worker.snapshot is None
    assert budget.state.reservation_count == 0
    second.start_audit()
    until(qt_app, lambda: second.worker is None)
    assert second.document == prepare_contact_audit(result)
    first.close()
    second.close()


def test_shutdown_requests_all_workers_before_returning_all_reservations(qt_app, budget, native,
                                                                      monkeypatch):
    both_entered = threading.Barrier(3)
    original = gui.prepare_contact_audit

    def until_cancelled(*args, **kwargs):
        both_entered.wait(timeout=10)
        deadline = time.monotonic() + 10
        while not kwargs["cancelled"]() and time.monotonic() < deadline:
            time.sleep(.002)
        assert kwargs["cancelled"](), "worker was not asked to stop"
        return original(*args, **kwargs)

    monkeypatch.setattr(gui, "prepare_contact_audit", until_cancelled)
    first, second = gui.ContactAuditDialog(native), gui.ContactAuditDialog(native)
    first.start_audit()
    second.start_audit()
    workers = (first.worker, second.worker)
    both_entered.wait(timeout=10)
    assert budget.state.reservation_count == 2
    gui._wait_on_exit()
    assert budget.state.reservation_count == 0
    assert all(w.cancelled and w.snapshot is None and w.document is None for w in workers)
    until(qt_app, lambda: first.worker is None and second.worker is None)
    first.close()
    second.close()

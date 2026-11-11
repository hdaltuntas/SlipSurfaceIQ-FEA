"""Actual Qt cooperative cancellation with real snapshot reconstruction checkpoints."""

from __future__ import annotations

import json
import os
import pickle
import runpy
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtCore import QCoreApplication, QEvent, QTimer

from slipsurface.fe2d import api
from slipsurface.fe2d.gui import contact_audit as gui
from slipsurface.fe2d.post import contact_audit_report as reports
from slipsurface.fe2d.post.contact_topology import _Context

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
    assert predicate(), "Qt cancellation/event completion timed out"


def test_completion_percent_is_not_physical_balance(qt_app, native):
    dialog = gui.ContactAuditDialog(native)
    assert dialog.progress.value() == 0
    dialog.run_button.click()
    until(qt_app, lambda: dialog.worker is None)
    assert dialog.progress.value() == 100
    assert "separate audit verdicts" in dialog.progress.format()
    assert dialog.document["audit"]["status"] == "passed"
    assert reports.audit_summary(dialog.document)["physical_not_balanced"] > 0
    dialog.origin_x.setText("3")
    assert dialog.progress.value() == 0 and dialog.document is None


def test_no_100_percent_or_export_before_document_validation(qt_app, native, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = reports.validate_document

    def pause(document):
        entered.set()
        assert release.wait(5)
        return original(document)

    monkeypatch.setattr(reports, "validate_document", pause)
    dialog = gui.ContactAuditDialog(native)
    dialog.run_button.click()
    try:
        until(qt_app, entered.is_set)
        assert dialog.progress.value() == 99
        assert dialog.document is None and not dialog.export_button.isEnabled()
    finally:
        release.set()
    until(qt_app, lambda: dialog.worker is None)
    assert dialog.progress.value() == 100 and dialog.export_button.isEnabled()


def test_cancel_inside_real_audit_stops_later_stages_and_can_restart(qt_app, native, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = _Context.elastic_prediction
    calls, completed = [], []

    def paused(ctx, *args):
        calls.append(1)
        if len(calls) == 3:
            entered.set()
            assert release.wait(5)
        value = original(ctx, *args)  # real first block checkpoint observes cancellation
        completed.append(1)
        return value

    monkeypatch.setattr(_Context, "elastic_prediction", paused)
    before = pickle.dumps(native)
    dialog = gui.ContactAuditDialog(native)
    dialog.show()
    dialog.run_button.click()
    worker = dialog.worker
    output = os.environ.get("CONTACT_AUDIT_EVIDENCE_DIR")
    root = Path(output) if output and native.model.mesh.block("contact").etype is api.ElemType.IFACE6 \
        else None
    try:
        until(qt_app, entered.is_set)
        assert 0 < dialog.progress.value() < 100
        assert dialog.document is None
        assert not dialog.export_button.isEnabled()
        responsive = []
        QTimer.singleShot(0, lambda: responsive.append(True))
        until(qt_app, lambda: bool(responsive))
        if root:
            root.mkdir(parents=True, exist_ok=True)
            assert dialog.grab().save(str(root / "contact-audit-progress.png"))
        dialog.discard_button.click()
        assert "Cancellation requested" in dialog.status.text()
        assert not dialog.discard_button.isEnabled()
    finally:
        release.set()
    until(qt_app, lambda: dialog.worker is None)
    assert worker.cancelled and worker.error is None and worker.document is None
    assert len(calls) == 3 and len(completed) == 2  # not merely a suppressed completed report
    assert dialog.document is None and dialog.table.rowCount() == 0
    assert not dialog.export_button.isEnabled() and dialog.run_button.isEnabled()
    assert pickle.dumps(native) == before
    assert not gui._PENDING
    if root:
        assert dialog.grab().save(str(root / "contact-audit-cancelled.png"))
        (root / "contact-audit-cancellation.json").write_text(json.dumps({
            "cancelled": worker.cancelled,
            "completed_stage_reconstructions": len(completed),
            "entered_stage_reconstructions": len(calls),
            "complete_report_published": dialog.document is not None,
            "export_enabled": dialog.export_button.isEnabled(),
            "source_unchanged": pickle.dumps(native) == before,
        }, indent=2), encoding="utf-8")
    dialog.run_button.click()
    until(qt_app, lambda: dialog.worker is None)
    assert dialog.document == reports.prepare_contact_audit(native)
    assert dialog.progress.value() == 100


@pytest.mark.parametrize("operation", ["close", "escape", "delete"])
def test_destruction_requests_real_cancellation(qt_app, native, monkeypatch, operation):
    entered, release = threading.Event(), threading.Event()
    original = _Context.elastic_prediction
    completed = []

    def paused(ctx, *args):
        entered.set()
        assert release.wait(5)
        value = original(ctx, *args)
        completed.append(1)
        return value

    monkeypatch.setattr(_Context, "elastic_prediction", paused)
    dialog = gui.ContactAuditDialog(native)
    dialog.show()
    dialog.run_button.click()
    worker = dialog.worker
    try:
        until(qt_app, entered.is_set)
        if operation == "close":
            dialog.close()
        elif operation == "escape":
            dialog.reject()
        else:
            dialog.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert worker.cancel_event.is_set()
    finally:
        release.set()
    until(qt_app, lambda: worker not in gui._PENDING)
    assert worker.cancelled and worker.document is None and not completed
    if operation != "delete":
        assert dialog.document is None and not dialog.isVisible()


def test_cancel_during_envelope_validation_suppresses_complete_numeric_result(qt_app, native,
                                                                           monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = reports.validate_document

    def pause(document):
        entered.set()
        assert release.wait(5)
        return original(document)

    monkeypatch.setattr(reports, "validate_document", pause)
    dialog = gui.ContactAuditDialog(native)
    dialog.run_button.click()
    worker = dialog.worker
    try:
        until(qt_app, entered.is_set)
        dialog.discard_button.click()
    finally:
        release.set()
    until(qt_app, lambda: dialog.worker is None)
    assert worker.cancelled and dialog.document is None
    assert dialog.progress.value() < 100 and not dialog.export_button.isEnabled()


def test_cancelled_worker_does_not_enter_audit(qt_app, native, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("pre-cancelled worker executed")

    monkeypatch.setattr(gui, "prepare_contact_audit", forbidden)
    worker = gui.ContactAuditWorker(native, (0., 0.), qt_app)
    worker.cancel_event.set()
    worker.start()
    assert worker.wait(5000)
    assert worker.cancelled and worker.document is None and worker.error is None
    worker.deleteLater()


def test_application_exit_cancels_every_worker_safely(qt_app, native, monkeypatch):
    lock = threading.Lock()
    entered = []

    def cancellable_work(ctx, *args):
        with lock:
            entered.append(1)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            ctx.checkpoint()
            time.sleep(.002)
        raise AssertionError("shutdown did not request cancellation")

    monkeypatch.setattr(_Context, "elastic_prediction", cancellable_work)
    dialogs = [gui.ContactAuditDialog(native), gui.ContactAuditDialog(native)]
    for dialog in dialogs:
        dialog.run_button.click()
    workers = [d.worker for d in dialogs]
    until(qt_app, lambda: len(entered) == 2)
    gui._wait_on_exit()
    until(qt_app, lambda: not gui._PENDING)
    assert all(w.cancelled and w.document is None for w in workers)
    assert all(d.document is None for d in dialogs)

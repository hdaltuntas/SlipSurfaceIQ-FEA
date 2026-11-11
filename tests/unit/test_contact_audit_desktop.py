"""Real Qt read-only audit, thread lifecycle, unsupported states and atomic export."""

from __future__ import annotations

import copy
import json
import os
import pickle
import runpy
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
pytest.importorskip('PySide6')
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QFileDialog

from slipsurface.fe2d import api
from slipsurface.fe2d.gui import contact_audit as gui
from slipsurface.fe2d.gui.contact_results import ContactResultsDialog
from slipsurface.fe2d.io.contact_audit_json import export_contact_audit_json
from slipsurface.fe2d.post.contact_audit_report import audit_rows, audit_summary

_B = runpy.run_path(str(Path(__file__).resolve().parents[2] / 'scripts'
                       / 'f7_contact_topology_benchmark.py'))


@pytest.fixture(scope='module', params=['IFACE4', 'IFACE6'])
def native(request):
    return api.run(_B['asymmetric_model'](element_type=request.param))


def until(app, predicate):
    deadline = time.monotonic() + 10
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.002)
    app.processEvents()
    assert predicate(), 'Qt worker/event completion timed out'


def run(app, dialog):
    dialog.run_button.click()
    until(app, lambda: dialog.worker is None)
    assert dialog.document is not None, dialog.status.text()


def test_parent_routes_exact_snapshot_and_whole_history(qt_app, native):
    parent = ContactResultsDialog(native, 2, 'contact')
    parent.audit_button.click()
    dialog = parent._audit_window
    assert dialog.selected_snapshot == 2
    assert dialog.document is None
    assert not dialog.export_button.isEnabled()
    run(qt_app, dialog)
    assert dialog.table.rowCount() == len(native.stages) + 1
    assert dialog.table.currentRow() == 2
    dialog.table.setCurrentCell(4, 0)
    assert parent.stage.currentIndex() == 2
    parent.audit_button.click()
    assert parent._audit_window is dialog


def test_real_thread_audits_without_solver_and_without_mutation(qt_app, native, monkeypatch):
    from slipsurface.fe2d.fem.static import StaticSolver

    def forbidden(*a, **kw):
        raise AssertionError('no solve during inspection')
    monkeypatch.setattr(api, 'run', forbidden)
    monkeypatch.setattr(StaticSolver, 'run', forbidden)
    before = pickle.dumps(native)
    dialog = gui.ContactAuditDialog(native)
    run(qt_app, dialog)
    assert pickle.dumps(native) == before
    assert dialog.document['audit']['status'] == 'passed'
    assert not gui._PENDING


def test_valid_transition_and_physical_failure_have_distinct_cells(qt_app, native):
    dialog = gui.ContactAuditDialog(native)
    run(qt_app, dialog)
    rows = audit_rows(dialog.document)
    i = next(i for i, r in enumerate(rows) if r.physical == 'failed')
    assert dialog.table.item(i, 3).text() == 'passed'
    assert dialog.table.item(i, 4).text() == 'not balanced'
    assert float(dialog.table.item(i, 9).text()) > 0
    dialog.table.setCurrentCell(i, 0)
    details = json.loads(dialog.details.toPlainText())
    assert details['physical_equilibrium']['status'] == 'failed'
    assert details['status'] == 'passed'
    assert 'not balanced' in dialog.status.text()


def test_corruption_and_blocked_successors_have_no_false_zeros(qt_app, native):
    result = copy.deepcopy(native)
    result.stages[1].contact_gap.clear()
    dialog = gui.ContactAuditDialog(result, 2)
    run(qt_app, dialog)
    assert dialog.table.item(2, 3).text() == 'invalid'
    assert dialog.table.item(3, 3).text() == 'blocked'
    for i in (2, 3):
        assert dialog.table.item(i, 4).text() == 'not assessed'
        assert dialog.table.item(i, 5).text() == '—'
    assert dialog.export_button.isEnabled()  # invalid outcomes are exportable evidence
    assert 'reason' in dialog.details.toPlainText()


def test_unsupported_model_reason_and_export_available(qt_app, native):
    result = copy.deepcopy(native)
    tag = next(iter(result.model.materials))
    result.model.materials[tag] = api.MaterialSpec.mohr_coulomb(tag, 2000, .25, 10, 30)
    dialog = gui.ContactAuditDialog(result)
    run(qt_app, dialog)
    assert dialog.table.item(0, 3).text() == 'unsupported'
    assert 'elastic' in dialog.details.toPlainText()
    assert audit_summary(dialog.document)['physical_passed'] == 0


def test_origin_change_discards_old_report_and_invalid_input_does_not_start(qt_app, native):
    dialog = gui.ContactAuditDialog(native)
    run(qt_app, dialog)
    dialog.origin_x.setText('nan')
    assert dialog.document is None and dialog.table.rowCount() == 0
    assert not dialog.export_button.isEnabled()
    dialog.run_button.click()
    assert dialog.worker is None
    assert 'could not start' in dialog.status.text()
    dialog.origin_x.setText('2.5')
    run(qt_app, dialog)
    assert dialog.document['origin_m'] == [2.5, 0.0]


def test_export_is_exact_displayed_report_not_source_recalculation(qt_app, native, monkeypatch,
                                                                 tmp_path):
    result = copy.deepcopy(native)
    dialog = gui.ContactAuditDialog(result)
    run(qt_app, dialog)
    displayed = copy.deepcopy(dialog.document)
    result.last.contact_gap.clear()
    path = tmp_path / 'audit.json'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(path), 'JSON'))
    dialog.export_button.click()
    assert json.loads(path.read_text()) == displayed


def test_export_cancel_and_failure(qt_app, native, monkeypatch):
    dialog = gui.ContactAuditDialog(native)
    run(qt_app, dialog)
    status = dialog.status.text()
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: ('', ''))
    dialog.export_button.click()
    assert dialog.status.text() == status
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: ('a.json', 'JSON'))
    def fail(*a, **kw):
        raise OSError('intentional write failure')
    monkeypatch.setattr(gui, 'export_contact_audit_json', fail)
    dialog.export_button.click()
    assert 'Export rejected' in dialog.status.text()


def test_worker_failure_has_no_export_or_stale_success(qt_app, native, monkeypatch):
    dialog = gui.ContactAuditDialog(native)
    run(qt_app, dialog)
    def fail(*a, **kw):
        raise RuntimeError('intentional worker failure')
    monkeypatch.setattr(gui, 'prepare_contact_audit', fail)
    dialog.run_button.click()
    until(qt_app, lambda: dialog.worker is None)
    assert dialog.document is None and dialog.table.rowCount() == 0
    assert not dialog.export_button.isEnabled()
    assert 'intentional worker failure' in dialog.status.text()
    assert dialog.run_button.isEnabled()


@pytest.mark.parametrize('operation', ['discard', 'close', 'escape', 'delete'])
def test_inflight_lifecycle_never_publishes_partial_report(qt_app, native, monkeypatch, operation):
    entered, release = threading.Event(), threading.Event()
    original = gui.prepare_contact_audit
    def slow(result, **kw):
        entered.set()
        assert release.wait(5)
        return original(result, **kw)
    monkeypatch.setattr(gui, 'prepare_contact_audit', slow)
    dialog = gui.ContactAuditDialog(native)
    dialog.show()
    dialog.run_button.click()
    until(qt_app, entered.is_set)
    assert not dialog.run_button.isEnabled()
    assert not dialog.origin_x.isEnabled()
    worker = dialog.worker
    assert worker in gui._PENDING
    processed = []
    QTimer.singleShot(0, lambda: processed.append(True))
    until(qt_app, lambda: bool(processed))  # GUI event loop remains responsive
    if operation == 'discard':
        dialog.discard_button.click()
    elif operation == 'close':
        dialog.close()
    elif operation == 'escape':
        dialog.reject()
    else:
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    release.set()
    until(qt_app, lambda: worker not in gui._PENDING)
    if operation != 'delete':
        assert dialog.document is None and not dialog.export_button.isEnabled()
        if operation in ('close', 'escape'):
            assert not dialog.isVisible()


def test_worker_uses_detached_input(qt_app, native, monkeypatch):
    result = copy.deepcopy(native)
    entered, release = threading.Event(), threading.Event()
    original = gui.prepare_contact_audit
    def slow(snapshot, **kw):
        entered.set()
        assert release.wait(5)
        return original(snapshot, **kw)
    monkeypatch.setattr(gui, 'prepare_contact_audit', slow)
    dialog = gui.ContactAuditDialog(result)
    dialog.run_button.click()
    until(qt_app, entered.is_set)
    result.last.contact_gap.clear()
    release.set()
    until(qt_app, lambda: dialog.worker is None)
    assert dialog.document['audit']['status'] == 'passed'


def test_interpret_table_stage_does_not_change_main_selection(qt_app, native):
    pytest.importorskip('shapely')
    from slipsurface.fe2d.gui.app import MainWindow

    window = MainWindow()
    window.model, window.result = native.model, native
    window.stages.clear()
    window.stages.addItems([native.initial.name, *(s.name for s in native.stages)])
    window.stages.setCurrentRow(1)
    window.open_interpret()
    interpret = window._interpret_window
    tabs, fields, *_ = interpret.viewer
    tabs.setCurrentIndex(3)
    fields.setCurrentText('contact_gap')
    window._query_interpret()
    table = interpret.contact_dialog
    table.audit_button.click()
    audit = table._audit_window
    assert audit.selected_snapshot == 3
    run(qt_app, audit)
    assert window.stages.currentRow() == 1
    assert tabs.currentIndex() == 3


def test_real_saved_project_gui_evidence(qt_app, native, tmp_path):
    path = tmp_path / 'native.ssproj'
    api.save_project(native.model, path, native)
    result = api.load_project(path).results
    dialog = gui.ContactAuditDialog(result, 2)
    run(qt_app, dialog)
    output = os.environ.get('CONTACT_AUDIT_EVIDENCE_DIR')
    if output and result.model.mesh.block('contact').etype is api.ElemType.IFACE6:
        root = Path(output)
        root.mkdir(parents=True, exist_ok=True)
        dialog.show()
        qt_app.processEvents()
        assert dialog.grab().save(str(root / 'contact-audit.png'))
        export_contact_audit_json(dialog.document, root / 'contact-audit.json')
        api.save_project(result.model, root / 'contact-audit.ssproj', result)
        result.stages[1].contact_gap.clear()
        invalid = gui.ContactAuditDialog(result, 2)
        run(qt_app, invalid)
        invalid.show()
        qt_app.processEvents()
        assert invalid.grab().save(str(root / 'contact-audit-invalid.png'))
        export_contact_audit_json(invalid.document, root / 'contact-audit-invalid.json')

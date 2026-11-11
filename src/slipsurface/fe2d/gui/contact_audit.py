"""Read-only, threaded elastic contact equilibrium inspection of saved snapshots."""

from __future__ import annotations

import json
import threading

from PySide6.QtCore import QCoreApplication, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..io.contact_audit_json import export_contact_audit_json
from ..post.contact_audit_control import ContactAuditCancelled
from ..post.contact_audit_report import audit_rows, audit_summary, prepare_contact_audit
from ..post.contact_audit_snapshot import DEFAULT_ARRAY_LIMIT, copy_contact_audit_snapshot
from ..post.contact_resultants import moment_origin

_PENDING = set()
_SHUTDOWN_CONNECTED = False


def _wait_on_exit():
    # Request every cancellation before waiting for any worker. A current bulk
    # operation may finish first; never terminate a thread or expose partial data.
    workers = tuple(_PENDING)
    for worker in workers:
        worker.cancel_event.set()
        worker.requestInterruption()
    for worker in workers:
        worker.wait()


def _release_worker(worker):
    _PENDING.discard(worker)
    worker.deleteLater()


class ContactAuditWorker(QThread):
    progressed = Signal(object)

    def __init__(self, result, origin, parent=None, *, max_array_bytes=DEFAULT_ARRAY_LIMIT):
        super().__init__(parent)
        # Keep the synchronous detached-input boundary. The unused geometry cache
        # is omitted and the array limit is checked BEFORE allocating the copy.
        self.snapshot, self.snapshot_plan = copy_contact_audit_snapshot(
            result, max_array_bytes=max_array_bytes,
        )
        self.origin = origin
        self.document = None
        self.error = None
        self.cancelled = False
        self.cancel_event = threading.Event()

    def cancellation_requested(self):
        return self.cancel_event.is_set() or self.isInterruptionRequested()

    def run(self):
        if self.cancellation_requested():
            self.cancelled = True
            self.snapshot = None
            return
        try:
            document = prepare_contact_audit(
                self.snapshot, origin=self.origin,
                progress=self.progressed.emit, cancelled=self.cancellation_requested,
            )
        except ContactAuditCancelled:
            self.cancelled = True
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
        else:
            if self.cancellation_requested():
                self.cancelled = True
            else:
                self.document = document
        finally:
            # Completed/cancelled/error workers may remain referenced by clients.
            # Keep the compact report/plan, not a second full input history.
            self.snapshot = None


class ContactAuditDialog(QDialog):
    def __init__(self, result, stage_index=0, parent=None):
        super().__init__(parent)
        self.result = result
        self.selected_snapshot = stage_index
        self.document = None
        self.worker = None
        self._discard = False
        self._closing = False
        self.setWindowTitle("Normal contact · elastic history equilibrium audit")
        self.resize(1260, 760)
        layout = QVBoxLayout(self)
        note = QLabel(
            "Read-only audit of ALL accepted snapshots, not a new solve. Dry, drained, "
            "zero-gravity, stress-free elastic plane-strain continuum + normal contact only. "
            "Transition PASS does not imply physical-only balance: a partial stage can retain "
            "numerical release forces. Neither status certifies design capacity or safety. "
            "No water, frictional contact, nonlinear soil, beams/anchors or restart. "
            "The selected interface filter does not restrict this whole-model audit."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        controls = QHBoxLayout()
        self.origin_x, self.origin_y = QLineEdit("0"), QLineEdit("0")
        self.run_button = QPushButton("Run complete history audit")
        self.discard_button = QPushButton("Cancel audit")
        self.discard_button.setEnabled(False)
        for widget in (QLabel("Moment origin x (m)"), self.origin_x, QLabel("y (m)"),
                       self.origin_y, self.run_button, self.discard_button):
            controls.addWidget(widget)
        layout.addLayout(controls)
        resources = QHBoxLayout()
        self.array_limit = QSpinBox()
        self.array_limit.setRange(1, 65536)
        self.array_limit.setValue(DEFAULT_ARRAY_LIMIT // 1048576)
        self.array_limit.setSuffix(" MiB")
        self.array_limit.setToolTip(
            "Per-run copied NumPy payload limit, NOT total memory. "
            "Python metadata and audit workspace need additional RAM. "
            "The input copy is synchronous; this is not a latency guarantee."
        )
        resources.addWidget(QLabel("Input array copy limit"))
        resources.addWidget(self.array_limit)
        resources.addStretch(1)
        layout.addLayout(resources)
        self.snapshot_info = QLabel(
            "Unused solver geometry cache is not copied; audit geometry is rebuilt. "
            "Array limit excludes Python metadata and audit workspace."
        )
        self.snapshot_info.setWordWrap(True)
        layout.addWidget(self.snapshot_info)
        self.status = QLabel(
            "Not run. The audit uses a detached copy; source results are unchanged."
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Not run")
        layout.addWidget(self.progress)
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels([
            "Snapshot", "Stage", "Fraction", "Transition", "Physical only",
            "Max nodal\nresidual (kN/m)", "Residual Fx\n(kN/m)",
            "Residual Fy\n(kN/m)", "Residual Mz\n(kN·m/m)",
            "Max retained\nnodal (kN/m)",
        ])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, 2)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        layout.addWidget(self.details, 1)
        bottom = QHBoxLayout()
        self.export_button = QPushButton("Export complete audit JSON…")
        self.export_button.setEnabled(False)
        close = QPushButton("Close")
        bottom.addWidget(self.export_button)
        bottom.addStretch(1)
        bottom.addWidget(close)
        layout.addLayout(bottom)
        self.run_button.clicked.connect(self.start_audit)
        self.discard_button.clicked.connect(self.discard)
        self.origin_x.textChanged.connect(self.invalidate)
        self.origin_y.textChanged.connect(self.invalidate)
        self.table.itemSelectionChanged.connect(self.show_details)
        self.export_button.clicked.connect(self.export_report)
        close.clicked.connect(self.reject)

    def invalidate(self, *_):
        self.document = None
        self.table.setRowCount(0)
        self.details.clear()
        self.export_button.setEnabled(False)
        if self.worker is None:
            self.progress.setValue(0)
            self.progress.setFormat("Not run")
        if self.worker is not None:
            self.discard()
        else:
            self.status.setText("Inputs changed; previous report cleared. Run the audit again.")

    def start_audit(self):
        if self.worker is not None:
            return
        self.invalidate()
        self.snapshot_info.setText(
            "Checking input array payload before copying; unused geometry cache excluded. "
            "No total-memory or latency guarantee."
        )
        try:
            origin = moment_origin((float(self.origin_x.text()), float(self.origin_y.text())))
            self.worker = ContactAuditWorker(
                self.result, origin, QCoreApplication.instance(),
                max_array_bytes=self.array_limit.value() * 1048576,
            )
        except Exception as exc:
            self.status.setText(f"Audit could not start: {exc}")
            return
        plan = self.worker.snapshot_plan
        self.snapshot_info.setText(
            f"Detached input: {plan.array_count} arrays, "
            f"{plan.array_bytes / 1048576:.2f} MiB payload. Solver geometry cache omitted. "
            "Python metadata and audit workspace are additional; not total RAM."
        )
        self._discard, self._closing = False, False
        self.array_limit.setEnabled(False)
        self.run_button.setEnabled(False)
        self.origin_x.setEnabled(False)
        self.origin_y.setEnabled(False)
        self.discard_button.setEnabled(True)
        self.status.setText("Auditing a detached snapshot history; no FEM solve is running.")
        self.progress.setValue(0)
        self.progress.setFormat("Starting…")
        # Consume worker data only after QThread finishes. This avoids queued-result
        # races with discard/close and keeps the thread alive through every exit path.
        self.worker.progressed.connect(self.show_progress)
        self.worker.finished.connect(self.finish_audit)
        # Capture only a thread-safe Event, NOT the dialog or a possibly deleted
        # QThread wrapper. Even direct parent/dialog deletion requests cancellation.
        cancel_event = self.worker.cancel_event
        self.destroyed.connect(lambda *_: cancel_event.set())
        global _SHUTDOWN_CONNECTED
        if not _SHUTDOWN_CONNECTED:
            QCoreApplication.instance().aboutToQuit.connect(_wait_on_exit)
            _SHUTDOWN_CONNECTED = True
        worker = self.worker
        _PENDING.add(worker)
        worker.finished.connect(lambda: _release_worker(worker))
        worker.start()

    def discard(self):
        if self.worker is None:
            return
        self._discard = True
        self.worker.cancel_event.set()
        self.worker.requestInterruption()
        self.discard_button.setEnabled(False)
        self.status.setText(
            "Cancellation requested; waiting for the next safe checkpoint. "
            "No partial report will be shown or exported."
        )
        self.progress.setFormat("Cancelling…")

    @Slot(object)
    def show_progress(self, event):
        # Ignore late queued events after discard/close or from an earlier run.
        if self.worker is None or self._discard or self.sender() is not self.worker:
            return
        percent = min(99, 100 * event.completed_snapshots // max(1, event.total_snapshots))
        self.progress.setValue(percent)
        self.progress.setFormat(
            f"{event.completed_snapshots}/{event.total_snapshots} snapshots processed · %p%"
        )
        self.status.setText(
            f"Snapshot {event.snapshot_index}: {event.stage_name} · {event.phase}. "
            "Progress counts processed snapshots, NOT passing checks. "
            "Completion requires validation of the full report."
        )

    def finish_audit(self):
        worker = self.worker
        self.worker = None
        self.run_button.setEnabled(True)
        self.array_limit.setEnabled(True)
        self.origin_x.setEnabled(True)
        self.origin_y.setEnabled(True)
        self.discard_button.setEnabled(False)
        if self._discard or worker.cancelled:
            self.document = None
            self.table.setRowCount(0)
            self.details.clear()
            self.export_button.setEnabled(False)
            self.progress.setFormat("Cancelled — no report")
            self.status.setText("Audit cancelled or result discarded. No partial report retained.")
        elif worker.document is not None:
            self.document = worker.document
            self.progress.setValue(100)
            self.progress.setFormat("Complete — see separate audit verdicts")
            self.present()
        else:
            self.progress.setFormat("Execution failed — no report")
            self.status.setText(f"Audit failed to execute: {worker.error or 'No complete report'}")
        if self._closing:
            self._closing = False
            self.reject()

    def present(self):
        rows = audit_rows(self.document)
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            residual = row.global_residual or (None, None, None)
            values = [row.snapshot_index, row.name, row.fraction, row.transition,
                      "not balanced" if row.physical == "failed" else row.physical,
                      row.nodal_residual, *residual, row.retained_max]
            for j, value in enumerate(values):
                text = ("—" if value is None else f"{value:.6g}"
                        if isinstance(value, float) else str(value))
                item = QTableWidgetItem(text)
                item.setToolTip(row.reason)
                self.table.setItem(i, j, item)
        counts = audit_summary(self.document)
        self.status.setText(
            f"Initial: {self.document['audit']['initial_status']} · "
            f"Transition: {counts['transition_passed']}/{counts['stage_count']} passed · "
            f"Physical only: {counts['physical_passed']} passed, "
            f"{counts['physical_not_balanced']} not balanced, "
            f"{counts['physical_not_assessed']} not assessed. "
            "Incomplete/failed predecessors never become physical passes. "
            "Global cancellation alone is not sufficient; nodal checks remain decisive."
        )
        self.export_button.setEnabled(True)  # Failed/unsupported reports are useful evidence.
        self.table.setCurrentCell(max(0, min(self.selected_snapshot, len(rows)-1)), 0)
        self.show_details()

    def show_details(self):
        if self.document is None:
            return
        index = self.table.currentRow()
        if index < 0:
            return
        audit = self.document["audit"]
        value = ({k: v for k, v in audit.items() if k != "stages"}
                 if index == 0 else audit["stages"][index-1])
        self.details.setPlainText(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False))

    def export_report(self):
        if self.document is None or self.worker is not None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export complete contact audit",
                                             "contact-audit.json", "JSON (*.json)")
        if not path:
            return
        try:
            export_contact_audit_json(self.document, path)
        except (OSError, ValueError, TypeError) as exc:
            self.status.setText(f"Export rejected: {exc}")
            return
        self.status.setText(f"Exported complete audit, including failure states: {path}")

    def done(self, result):
        # Escape, Close and window-manager close must never destroy a running QThread.
        if self.worker is not None:
            self._closing = True
            self.discard()
            self.hide()
            return
        super().done(result)

    def closeEvent(self, event):
        if self.worker is not None:
            self._closing = True
            self.discard()
            event.ignore()
            self.hide()
        else:
            super().closeEvent(event)

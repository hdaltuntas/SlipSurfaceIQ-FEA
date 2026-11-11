"""Qt-free execution hooks for the read-only elastic contact audit.

Cancellation is a control-flow outcome, never a numerical verdict. Checkpoints
cannot interrupt a single NumPy operation, model validation or serialization.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


class ContactAuditCancelled(RuntimeError):
    """The caller requested cancellation; no complete audit report is returned."""


class ContactAuditCallbackError(RuntimeError):
    """An execution callback failed; do not mislabel this as invalid FEM data."""


@dataclass(frozen=True)
class ContactAuditProgress:
    """Processing progress, NOT passed checks, elapsed time or solver progress.

    Snapshot 0 is the initial state. A blocked snapshot is processed but is not
    evaluated. ``total_snapshots`` includes the initial snapshot. The completed
    count does not include the current snapshot until its completion event.
    """

    completed_snapshots: int
    total_snapshots: int
    snapshot_index: int
    stage_name: str
    phase: str


class _AuditControl:
    """Synchronous caller-thread callbacks; GUI clients must marshal their events."""

    def __init__(
        self,
        progress: Callable[[ContactAuditProgress], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ):
        for name, callback in (("progress", progress), ("cancelled", cancelled)):
            if callback is not None and not callable(callback):
                raise TypeError(f"{name} must be callable or None")
        self.progress = progress
        self.cancelled = cancelled

    def checkpoint(self):
        if self.cancelled is None:
            return
        try:
            requested = self.cancelled()
        except ContactAuditCancelled:
            raise
        except Exception as exc:
            raise ContactAuditCallbackError("Cancellation callback failed") from exc
        if type(requested) is not bool:
            raise ContactAuditCallbackError("Cancellation callback must return a bool")
        if requested:
            raise ContactAuditCancelled("Contact history audit cancelled")

    def emit(self, completed, total, index, name, phase):
        self.checkpoint()
        if self.progress is not None:
            try:
                self.progress(ContactAuditProgress(completed, total, index, name, phase))
            except ContactAuditCancelled:
                raise
            except Exception as exc:
                raise ContactAuditCallbackError("Progress callback failed") from exc
        # A callback may itself request cancellation. Honor it before more work.
        self.checkpoint()

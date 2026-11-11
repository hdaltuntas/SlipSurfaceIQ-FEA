"""Thread-safe admission for concurrent detached audit-array payloads, not RAM.

Reservations are made before copying, shared by the desktop's audit windows,
then released only when their owned input is dropped. No waiting, queue, silent
limit increases or automatic retries are introduced. This is not an RSS limit.
"""

from __future__ import annotations

import threading
import weakref
from dataclasses import dataclass

from .contact_audit_snapshot import ContactAuditSnapshotLimitError

DEFAULT_SHARED_ARRAY_LIMIT = 1024 * 1024 * 1024


class ContactAuditSharedLimitError(ContactAuditSnapshotLimitError):
    """The concurrent input-copy budget refused admission, not a FEM verdict."""


@dataclass(frozen=True)
class ContactAuditBudgetState:
    limit_bytes: int
    reserved_bytes: int
    reservation_count: int


def _positive_limit(value):
    if type(value) is not int or value <= 0:
        raise ValueError("Shared array limit must be a positive integer number of bytes")


class ContactAuditCopyReservation:
    """An idempotent resource lease; abandonment also returns its reservation."""

    def __init__(self, budget, key, array_bytes):
        self.array_bytes = array_bytes
        self._finalizer = weakref.finalize(self, budget._release, key)

    def release(self):
        self._finalizer()

    @property
    def released(self):
        return not self._finalizer.alive


class ContactAuditCopyBudget:
    """Count pending copies and owned detached inputs across cooperating callers.

    The accounting is atomic, but it does NOT lock mutable FEM input. Callers
    must keep the source stable through preflight/copy as before. Python object
    overhead, original results, reports and numerical workspace are unbudgeted.
    """

    def __init__(self, limit_bytes=DEFAULT_SHARED_ARRAY_LIMIT):
        _positive_limit(limit_bytes)
        self._limit = limit_bytes
        self._lock = threading.RLock()
        self._reservations = {}
        self._next_key = 0

    def _state(self):
        return ContactAuditBudgetState(
            self._limit, sum(self._reservations.values()), len(self._reservations),
        )

    @property
    def state(self):
        with self._lock:
            return self._state()

    def set_limit(self, limit_bytes):
        """Apply an explicit session limit, rejecting reductions below live use."""
        _positive_limit(limit_bytes)
        with self._lock:
            used = sum(self._reservations.values())
            if limit_bytes < used:
                raise ContactAuditSharedLimitError(
                    f"Cannot lower shared limit below {used / 1048576:.2f} MiB "
                    "of reserved input arrays. Existing audits were not cancelled; "
                    "the previous shared limit is unchanged."
                )
            self._limit = limit_bytes
            return self._state()

    def reserve(self, array_bytes):
        """Refuse over-budget admission before any input allocation is attempted."""
        if type(array_bytes) is not int or array_bytes < 0:
            raise ValueError("Reserved array payload must be a nonnegative integer")
        with self._lock:
            used = sum(self._reservations.values())
            if array_bytes > self._limit - used:
                raise ContactAuditSharedLimitError(
                    f"Shared audit array budget exceeded: {used / 1048576:.2f} MiB "
                    f"already reserved + {array_bytes / 1048576:.2f} MiB requested; "
                    f"shared limit {self._limit / 1048576:.2f} MiB. "
                    "No input copy was allocated. Finish/cancel another audit or explicitly "
                    "raise the shared limit, then retry. This is not a total-RAM limit."
                )
            key = self._next_key
            self._next_key += 1
            self._reservations[key] = array_bytes
            try:
                return ContactAuditCopyReservation(self, key, array_bytes)
            except BaseException:
                del self._reservations[key]
                raise

    def _release(self, key):
        with self._lock:
            self._reservations.pop(key, None)

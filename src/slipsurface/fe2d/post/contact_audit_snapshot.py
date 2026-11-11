"""Bound the NumPy payload of a detached, read-only contact-audit input.

The audit rebuilds geometry from the model, so SolveResult.geom is deliberately
not cloned. Every other field is retained, including unsupported/invalid evidence.
The limit covers copied array payload only, NOT process RAM or audit workspace.
Copying stays synchronous to preserve the existing GUI-thread snapshot boundary.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, fields, is_dataclass, replace
from enum import Enum

import numpy as np

from ..fem.static import SolveResult

DEFAULT_ARRAY_LIMIT = 512 * 1024 * 1024


class ContactAuditSnapshotLimitError(MemoryError):
    """Input copy was refused before allocation; this is not a FEM verdict."""


@dataclass(frozen=True)
class ContactAuditSnapshotPlan:
    array_count: int
    array_bytes: int


def _audit_input(result):
    if type(result) is not SolveResult:
        raise TypeError("A native SolveResult is required for an audit snapshot")
    # Do not inspect, deepcopy, mutate or reuse the solver's geometry cache.
    # The read-only numerical audit computes its own geometry from model.mesh.
    return replace(result, geom={})


def _array_inventory(value):
    """Visit metadata/array identities, never array values or view backing buffers.

    deepcopy preserves repeated references to the same ndarray object but copies
    distinct ndarray views separately. Count each such object once, not each
    backing allocation once. Object arrays/custom objects cannot be safely sized
    by this native-data estimator and are explicitly refused, not guessed.
    """
    pending, seen = [value], set()
    count = size = 0
    while pending:
        item = pending.pop()
        if item is None or isinstance(item, (str, bytes, int, float, complex, bool, Enum)):
            continue
        if id(item) in seen:
            continue
        seen.add(id(item))
        if type(item) is np.ndarray:
            if item.dtype.hasobject:
                raise TypeError("Object arrays cannot be budgeted for a contact audit copy")
            count += 1
            size += int(item.nbytes)
        elif isinstance(item, np.generic):
            if item.dtype.hasobject:
                raise TypeError("Object scalars cannot be budgeted for a contact audit copy")
        elif type(item) is dict:
            pending.extend(item.keys())
            pending.extend(item.values())
        elif type(item) in (list, tuple, set, frozenset):
            pending.extend(item)
        elif is_dataclass(item) and not isinstance(item, type):
            # Include dynamic metadata too: deepcopy copies __dict__, not merely
            # declared fields. Slots-only dataclasses still expose field values.
            pending.extend(getattr(item, "__dict__", {}).values())
            pending.extend(getattr(item, field.name) for field in fields(item))
        else:
            raise TypeError(f"Cannot budget audit input type: {type(item).__name__}")
    return ContactAuditSnapshotPlan(count, size)


def plan_contact_audit_snapshot(result):
    """Estimate copied numeric-array payload without allocating array copies."""
    return _array_inventory(_audit_input(result))


def copy_contact_audit_snapshot(result, *, max_array_bytes=DEFAULT_ARRAY_LIMIT):
    """Return (detached input, plan), refusing an oversized copy before deepcopy.

    Call on the GUI thread while its source is stable; this is not a lock against
    arbitrary concurrent writers. Python metadata, output JSON, allocator costs
    and the audit's reconstructed matrices are additional, unbudgeted memory.
    """
    if type(max_array_bytes) is not int or max_array_bytes <= 0:
        raise ValueError("Input array limit must be a positive integer number of bytes")
    view = _audit_input(result)
    plan = _array_inventory(view)
    if plan.array_bytes > max_array_bytes:
        raise ContactAuditSnapshotLimitError(
            f"Audit input needs {plan.array_bytes / 1048576:.2f} MiB of copied array payload; "
            f"limit is {max_array_bytes / 1048576:.2f} MiB. No input copy was allocated. "
            "Raise the input array limit explicitly only with sufficient memory. "
            "This limit excludes Python metadata and audit workspace."
        )
    return copy.deepcopy(view), plan

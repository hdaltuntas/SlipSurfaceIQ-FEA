"""Concurrent payload admission, allocation rollback and native report identity."""

from __future__ import annotations

import gc
import pickle
import runpy
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.post import contact_audit_budget as budgets
from slipsurface.fe2d.post import contact_audit_snapshot as snapshots
from slipsurface.fe2d.post.contact_audit_control import ContactAuditCancelled
from slipsurface.fe2d.post.contact_audit_report import prepare_contact_audit

_B = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts"
                       / "f7_contact_topology_benchmark.py"))


@pytest.fixture(scope="module", params=["IFACE4", "IFACE6"])
def native(request):
    return api.run(_B["asymmetric_model"](element_type=request.param))


def test_default_and_immutable_budget_state():
    pool = budgets.ContactAuditCopyBudget()
    assert pool.state == budgets.ContactAuditBudgetState(1024**3, 0, 0)
    with pytest.raises(FrozenInstanceError):
        pool.state.reserved_bytes = 1


@pytest.mark.parametrize("bad", [0, -1, True, False, 1.5, "1", None, float("inf")])
def test_invalid_shared_limits_cannot_change_existing_budget(bad):
    with pytest.raises(ValueError, match="positive integer"):
        budgets.ContactAuditCopyBudget(bad)
    pool = budgets.ContactAuditCopyBudget(10)
    before = pool.state
    with pytest.raises(ValueError, match="positive integer"):
        pool.set_limit(bad)
    assert pool.state == before


@pytest.mark.parametrize("bad", [-1, True, False, 1.5, "1", None, float("nan")])
def test_invalid_reservations_cannot_change_budget(bad):
    pool = budgets.ContactAuditCopyBudget(10)
    before = pool.state
    with pytest.raises(ValueError, match="nonnegative integer"):
        pool.reserve(bad)
    assert pool.state == before


def test_exact_combined_limit_and_refusal_are_atomic():
    pool = budgets.ContactAuditCopyBudget(10)
    first, second = pool.reserve(6), pool.reserve(4)
    assert pool.state == budgets.ContactAuditBudgetState(10, 10, 2)
    before = pool.state
    with pytest.raises(budgets.ContactAuditSharedLimitError, match="No input copy"):
        pool.reserve(1)
    assert pool.state == before
    first.release()
    assert first.released and pool.state.reserved_bytes == 4
    second.release()
    assert pool.state == budgets.ContactAuditBudgetState(10, 0, 0)
    first.release()
    second.release()
    assert pool.state.reserved_bytes == 0


def test_zero_payload_lease_and_abandoned_lease_cleanup():
    pool = budgets.ContactAuditCopyBudget(10)
    lease = pool.reserve(0)
    assert pool.state.reservation_count == 1 and pool.state.reserved_bytes == 0
    del lease
    gc.collect()
    assert pool.state.reservation_count == 0
    lease = pool.reserve(10)
    del lease
    gc.collect()
    assert pool.state == budgets.ContactAuditBudgetState(10, 0, 0)


def test_limit_change_cannot_evict_active_input_or_silently_retry():
    pool = budgets.ContactAuditCopyBudget(10)
    lease = pool.reserve(6)
    with pytest.raises(budgets.ContactAuditSharedLimitError, match="unchanged"):
        pool.set_limit(5)
    assert pool.state == budgets.ContactAuditBudgetState(10, 6, 1)
    pool.set_limit(6)  # exactly live payload is permitted
    with pytest.raises(budgets.ContactAuditSharedLimitError):
        pool.reserve(1)
    pool.set_limit(12)
    assert pool.state == budgets.ContactAuditBudgetState(12, 6, 1)
    other = pool.reserve(6)
    lease.release()
    other.release()
    pool.set_limit(1)
    assert pool.state == budgets.ContactAuditBudgetState(1, 0, 0)


def test_parallel_admission_and_double_release_never_oversubscribe():
    pool = budgets.ContactAuditCopyBudget(1000)
    gate = threading.Barrier(16)

    def attempt():
        gate.wait(timeout=5)
        try:
            return pool.reserve(300)
        except budgets.ContactAuditSharedLimitError:
            return None

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(attempt) for _ in range(16)]
        leases = [f.result(timeout=10) for f in futures]
    admitted = [lease for lease in leases if lease is not None]
    assert len(admitted) == 3
    assert pool.state == budgets.ContactAuditBudgetState(1000, 900, 3)
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda lease: lease.release(), admitted * 8))
    assert pool.state == budgets.ContactAuditBudgetState(1000, 0, 0)


def test_reservation_construction_failure_rolls_back(monkeypatch):
    pool = budgets.ContactAuditCopyBudget(10)

    def fail(*args):
        raise MemoryError("lease allocation")

    monkeypatch.setattr(budgets, "ContactAuditCopyReservation", fail)
    with pytest.raises(MemoryError, match="lease allocation"):
        pool.reserve(10)
    assert pool.state == budgets.ContactAuditBudgetState(10, 0, 0)


def test_native_lease_preserves_report_and_detaches_input(native):
    before = pickle.dumps(native)
    plan = snapshots.plan_contact_audit_snapshot(native)
    pool = budgets.ContactAuditCopyBudget(plan.array_bytes)
    copied, observed, lease = snapshots.acquire_contact_audit_snapshot(native, pool)
    try:
        assert observed == plan and lease.array_bytes == plan.array_bytes
        assert pool.state.reserved_bytes == plan.array_bytes
        assert copied is not native and copied.model is not native.model and copied.geom == {}
        assert prepare_contact_audit(copied) == prepare_contact_audit(native)
        assert pickle.dumps(native) == before
    finally:
        del copied
        lease.release()
    assert pool.state.reserved_bytes == 0


def test_shared_refusal_precedes_deepcopy_without_releasing_others(native, monkeypatch):
    plan = snapshots.plan_contact_audit_snapshot(native)
    pool = budgets.ContactAuditCopyBudget(2 * plan.array_bytes - 1)
    busy = pool.reserve(plan.array_bytes)
    before = pool.state

    def forbidden(*args):
        raise AssertionError("Shared refusal must precede deepcopy")

    monkeypatch.setattr(snapshots.copy, "deepcopy", forbidden)
    try:
        with pytest.raises(budgets.ContactAuditSharedLimitError, match="Shared audit"):
            snapshots.acquire_contact_audit_snapshot(native, pool)
        assert pool.state == before
    finally:
        busy.release()


def test_per_run_limit_precedes_shared_admission(native, monkeypatch):
    plan = snapshots.plan_contact_audit_snapshot(native)
    pool = budgets.ContactAuditCopyBudget(plan.array_bytes * 2)

    def forbidden(*args):
        raise AssertionError("Per-run rejection must precede reservation")

    monkeypatch.setattr(pool, "reserve", forbidden)
    with pytest.raises(snapshots.ContactAuditSnapshotLimitError, match="No input copy"):
        snapshots.acquire_contact_audit_snapshot(
            native, pool, max_array_bytes=plan.array_bytes - 1,
        )
    assert pool.state.reservation_count == 0


@pytest.mark.parametrize("error", [MemoryError, RuntimeError, ContactAuditCancelled,
                                   KeyboardInterrupt])
def test_copy_failure_returns_its_reservation_only(native, monkeypatch, error):
    plan = snapshots.plan_contact_audit_snapshot(native)
    pool = budgets.ContactAuditCopyBudget(3 * plan.array_bytes)
    earlier = pool.reserve(plan.array_bytes)

    def fail(*args):
        # The whole planned input is already charged while copying.
        assert pool.state.reserved_bytes == 2 * plan.array_bytes
        raise error("copy failed")

    monkeypatch.setattr(snapshots.copy, "deepcopy", fail)
    try:
        with pytest.raises(error, match="copy failed"):
            snapshots.acquire_contact_audit_snapshot(native, pool)
        assert pool.state.reserved_bytes == plan.array_bytes
        assert pool.state.reservation_count == 1
    finally:
        earlier.release()


def test_existing_standalone_per_run_copy_contract_is_unchanged(native):
    copied, plan = snapshots.copy_contact_audit_snapshot(native)
    assert plan == snapshots.plan_contact_audit_snapshot(native)
    assert prepare_contact_audit(copied) == prepare_contact_audit(native)

"""Detached native audit inputs: cache elision, array budgets and evidence retention."""

from __future__ import annotations

import copy
import pickle
import runpy
from dataclasses import FrozenInstanceError
from pathlib import Path

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.post import contact_audit_snapshot as snapshots
from slipsurface.fe2d.post.contact_audit_report import prepare_contact_audit

_B = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts"
                       / "f7_contact_topology_benchmark.py"))


@pytest.fixture(scope="module", params=["IFACE4", "IFACE6"])
def native(request):
    return api.run(_B["asymmetric_model"](element_type=request.param))


def test_snapshot_omits_only_cache_and_preserves_report(native):
    before = pickle.dumps(native)
    detached, plan = snapshots.copy_contact_audit_snapshot(native)
    assert detached.geom == {} and native.geom
    assert plan == snapshots.plan_contact_audit_snapshot(native)
    assert plan.array_count > 0 and plan.array_bytes > 0
    assert prepare_contact_audit(detached) == prepare_contact_audit(native)
    assert pickle.dumps(native) == before
    assert detached is not native and detached.model is not native.model
    assert detached.stages is not native.stages
    for a, b in zip([native.initial, *native.stages], [detached.initial, *detached.stages]):
        assert not np.shares_memory(a.u, b.u)
        assert not np.shares_memory(a.reactions, b.reactions)
        for name in a.sig:
            assert not np.shares_memory(a.sig[name], b.sig[name])


def test_source_edit_after_copy_cannot_change_snapshot(native):
    source = copy.deepcopy(native)
    detached, _ = snapshots.copy_contact_audit_snapshot(source)
    expected = prepare_contact_audit(detached)
    source.last.contact_gap.clear()
    source.model.mesh.coords[:] = 0
    source.model.materials.clear()
    assert prepare_contact_audit(detached) == expected


def test_unused_cache_is_neither_inspected_nor_copied(native):
    class ForbiddenCache:
        def __deepcopy__(self, memo):
            raise AssertionError("Unused cache was copied")

    source = copy.copy(native)
    source.geom = ForbiddenCache()
    plan = snapshots.plan_contact_audit_snapshot(source)
    detached, observed = snapshots.copy_contact_audit_snapshot(source)
    assert detached.geom == {} and plan == observed
    assert prepare_contact_audit(detached) == prepare_contact_audit(native)


def test_budget_rejects_before_any_deepcopy_and_preserves_source(native, monkeypatch):
    before = pickle.dumps(native)
    plan = snapshots.plan_contact_audit_snapshot(native)

    def forbidden(*args, **kwargs):
        raise AssertionError("Budget rejection must precede copying")

    monkeypatch.setattr(snapshots.copy, "deepcopy", forbidden)
    with pytest.raises(snapshots.ContactAuditSnapshotLimitError, match="No input copy"):
        snapshots.copy_contact_audit_snapshot(native, max_array_bytes=plan.array_bytes - 1)
    assert pickle.dumps(native) == before


def test_exact_limit_is_inclusive_and_plan_is_immutable(native):
    plan = snapshots.plan_contact_audit_snapshot(native)
    detached, observed = snapshots.copy_contact_audit_snapshot(
        native, max_array_bytes=plan.array_bytes,
    )
    assert observed == plan and detached.geom == {}
    with pytest.raises(FrozenInstanceError):
        plan.array_bytes = 0


@pytest.mark.parametrize("bad", [0, -1, True, False, 1.5, "512", None, float("inf")])
def test_invalid_limit_does_not_allocate(native, bad, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid limit cannot allocate")

    monkeypatch.setattr(snapshots.copy, "deepcopy", forbidden)
    with pytest.raises(ValueError, match="positive integer"):
        snapshots.copy_contact_audit_snapshot(native, max_array_bytes=bad)


def test_shared_object_counted_once_but_distinct_views_count_separately(native):
    source = copy.deepcopy(native)
    base = snapshots.plan_contact_audit_snapshot(source)
    data = np.arange(240, dtype=np.float64)
    view = data[::2]
    transposed = data.reshape(20, 12).T
    source.model.geometry = {"a": data, "alias": data, "view": view, "T": transposed}
    plan = snapshots.plan_contact_audit_snapshot(source)
    assert plan.array_count == base.array_count + 3
    assert plan.array_bytes == base.array_bytes + data.nbytes + view.nbytes + transposed.nbytes
    detached, _ = snapshots.copy_contact_audit_snapshot(source)
    geometry = detached.model.geometry
    assert geometry["a"] is geometry["alias"]
    assert not np.shares_memory(geometry["a"], geometry["view"])
    assert not np.shares_memory(geometry["T"], transposed)
    np.testing.assert_array_equal(geometry["view"], view)
    np.testing.assert_array_equal(geometry["T"], transposed)


def test_cycles_and_dynamic_dataclass_arrays_do_not_escape_budget(native):
    source = copy.deepcopy(native)
    base = snapshots.plan_contact_audit_snapshot(source)
    source.model.geometry = {}
    source.model.geometry["cycle"] = source.model.geometry
    source.last.extra_snapshot_array = np.arange(23, dtype=np.int32)
    plan = snapshots.plan_contact_audit_snapshot(source)
    assert plan.array_count == base.array_count + 1
    assert plan.array_bytes == base.array_bytes + 92
    detached, _ = snapshots.copy_contact_audit_snapshot(source)
    assert detached.model.geometry["cycle"] is detached.model.geometry
    assert not np.shares_memory(detached.last.extra_snapshot_array,
                                source.last.extra_snapshot_array)


@pytest.mark.parametrize("kind", ["object_array", "subclass", "opaque"])
def test_unbudgetable_metadata_fails_before_copy(native, kind, monkeypatch):
    source = copy.deepcopy(native)
    if kind == "object_array":
        value = np.array([np.ones(100)], dtype=object)
    elif kind == "subclass":
        class ExtraArray(np.ndarray):
            pass
        value = np.ones(3).view(ExtraArray)
    else:
        value = object()
    source.model.geometry = {"extra": value}

    def forbidden(*args, **kwargs):
        raise AssertionError("Cannot copy unbudgetable metadata")

    monkeypatch.setattr(snapshots.copy, "deepcopy", forbidden)
    with pytest.raises(TypeError, match="budget"):
        snapshots.copy_contact_audit_snapshot(source)


@pytest.mark.parametrize("damage", ["gap", "pressure", "stress", "activity", "unsupported"])
def test_invalid_or_unsupported_evidence_is_not_pruned_into_pass(native, damage):
    source = copy.deepcopy(native)
    if damage == "gap":
        source.stages[1].contact_gap.clear()
    elif damage == "pressure":
        source.stages[1].interfaces["contact"][:] = np.nan
    elif damage == "stress":
        next(iter(source.stages[1].sig.values()))[:] = np.nan
    elif damage == "activity":
        source.stages[1].active.clear()
    else:
        tag = next(iter(source.model.materials))
        source.model.materials[tag] = api.MaterialSpec.mohr_coulomb(tag, 2000, .25, 10, 30)
    expected = prepare_contact_audit(source)
    detached, _ = snapshots.copy_contact_audit_snapshot(source)
    assert expected["audit"]["status"] == "failed"
    assert prepare_contact_audit(detached) == expected


def test_unused_cache_payload_is_substantial_but_not_counted(native):
    full = snapshots._array_inventory(native)
    plan = snapshots.plan_contact_audit_snapshot(native)
    caches = snapshots._array_inventory(native.geom)
    assert caches.array_bytes > 0
    assert full.array_bytes - plan.array_bytes == caches.array_bytes


def test_non_native_input_is_rejected():
    with pytest.raises(TypeError, match="SolveResult"):
        snapshots.copy_contact_audit_snapshot(None)

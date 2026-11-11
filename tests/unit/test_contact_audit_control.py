"""Execution hooks must interrupt work without altering a numerical verdict."""

from __future__ import annotations

import copy
import pickle
import runpy
import threading
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.post import contact_audit_report as reports
from slipsurface.fe2d.post import contact_topology_equilibrium as topology
from slipsurface.fe2d.post.contact_audit_control import (
    ContactAuditCallbackError,
    ContactAuditCancelled,
    ContactAuditProgress,
    _AuditControl,
)
from slipsurface.fe2d.post.contact_results import contact_points
from slipsurface.fe2d.post.contact_topology import _Context

_B = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts"
                       / "f7_contact_topology_benchmark.py"))


@pytest.fixture(scope="module", params=["IFACE4", "IFACE6"])
def native(request):
    return api.run(_B["asymmetric_model"](element_type=request.param))


def test_observed_and_plain_documents_are_identical(native):
    events = []
    before = pickle.dumps(native)
    expected = reports.prepare_contact_audit(native)
    observed = reports.prepare_contact_audit(
        native, progress=events.append, cancelled=lambda: False,
    )
    assert observed == expected
    assert pickle.dumps(native) == before
    assert events[0].completed_snapshots == 0 and events[0].phase == "initial"
    assert events[-1].completed_snapshots == len(native.stages) + 1
    assert events[-1].phase == "complete"
    assert all(isinstance(e, ContactAuditProgress) for e in events)
    assert [e.completed_snapshots for e in events] == sorted(e.completed_snapshots for e in events)
    assert {e.total_snapshots for e in events} == {len(native.stages) + 1}
    assert {e.snapshot_index for e in events} == set(range(len(native.stages) + 1))
    assert any(s["physical_equilibrium"]["status"] == "failed" for s in observed["audit"]["stages"])
    with pytest.raises(FrozenInstanceError):
        events[0].phase = "passed"


@pytest.mark.parametrize("phase,index", [
    ("initial", 0), ("initial_complete", 0), ("stage", 1), ("evidence", 1),
    ("reconstruction", 2), ("balance", 3), ("stage_complete", 4), ("complete", 6),
])
def test_cancel_at_phase_never_returns_report_or_visits_later_phase(native, phase, index):
    stop = threading.Event()
    events = []
    before = pickle.dumps(native)

    def progress(event):
        events.append(event)
        if event.phase == phase and event.snapshot_index == index:
            stop.set()

    with pytest.raises(ContactAuditCancelled):
        reports.prepare_contact_audit(native, progress=progress, cancelled=stop.is_set)
    assert events[-1].phase == phase and events[-1].snapshot_index == index
    assert pickle.dumps(native) == before


@pytest.mark.parametrize("budget", [1, 2, 4, 8, 16, 32, 64, 100])
def test_checkpoint_budgets_cancel_within_native_audit(native, budget):
    calls = 0
    before = pickle.dumps(native)

    def cancelled():
        nonlocal calls
        calls += 1
        return calls >= budget

    with pytest.raises(ContactAuditCancelled):
        topology.contact_topology_equilibrium_by_stage(native, cancelled=cancelled)
    assert calls == budget
    assert pickle.dumps(native) == before


def test_pre_cancel_does_not_construct_context_or_solve(native, monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError("cancelled work must not start")

    monkeypatch.setattr(topology, "_Context", forbidden)
    monkeypatch.setattr(api, "run", forbidden)
    with pytest.raises(ContactAuditCancelled):
        reports.prepare_contact_audit(native, cancelled=lambda: True)


@pytest.mark.parametrize("hook", ["progress", "cancelled"])
def test_callback_error_is_not_an_invalid_fem_snapshot(native, hook):
    def fail(*args):
        raise ValueError("observer failed")

    with pytest.raises(ContactAuditCallbackError) as caught:
        reports.prepare_contact_audit(native, **{hook: fail})
    assert isinstance(caught.value.__cause__, ValueError)


@pytest.mark.parametrize("hook", ["progress", "cancelled"])
@pytest.mark.parametrize("value", [False, 1, "callback"])
def test_non_callable_hooks_rejected(native, hook, value):
    with pytest.raises(TypeError, match="callable"):
        reports.prepare_contact_audit(native, **{hook: value})


@pytest.mark.parametrize("value", [None, 1, [], "false"])
def test_non_boolean_cancel_response_rejected(native, value):
    with pytest.raises(ContactAuditCallbackError, match="bool"):
        reports.prepare_contact_audit(native, cancelled=lambda: value)


@pytest.mark.parametrize("damage", ["initial", "stage", "unsupported", "incomplete"])
def test_progress_preserves_failed_unsupported_and_blocked_evidence(native, damage):
    result = copy.deepcopy(native)
    if damage == "initial":
        result.initial.contact_gap.clear()
    elif damage == "stage":
        result.stages[1].contact_gap.clear()
    elif damage == "unsupported":
        key = next(iter(result.model.materials))
        result.model.materials[key] = api.MaterialSpec.mohr_coulomb(key, 2000, .25, 10, 30)
    else:
        result.stages.pop()
    events = []
    baseline = topology.contact_topology_equilibrium_by_stage(result)
    actual = topology.contact_topology_equilibrium_by_stage(result, progress=events.append)
    assert actual == baseline and actual["status"] == "failed"
    assert events[-1].phase == "complete"
    assert events[-1].completed_snapshots == len(result.stages) + 1
    assert any(e.phase == "blocked" for e in events)


def test_cancel_can_interrupt_blocked_predecessor_sequence(native):
    result = copy.deepcopy(native)
    result.stages[0].contact_gap.clear()
    stop = threading.Event()

    def progress(event):
        if event.phase == "blocked":
            stop.set()

    with pytest.raises(ContactAuditCancelled):
        reports.prepare_contact_audit(result, progress=progress, cancelled=stop.is_set)


def test_duplicate_names_still_have_distinct_progress_indices(native):
    result = copy.deepcopy(native)
    result.model.stages = [replace(s, name="repeated") for s in result.model.stages]
    for s in result.stages:
        s.name = "repeated"
    events = []
    reports.prepare_contact_audit(result, progress=events.append)
    stages = [e for e in events if e.phase == "stage"]
    assert [e.snapshot_index for e in stages] == list(range(1, len(result.stages) + 1))
    assert all(e.stage_name == "repeated" for e in stages)


def test_cancel_during_serialization_never_publishes_envelope(native, monkeypatch):
    stop = threading.Event()
    original = reports.validate_document

    def cancelled_validation(document):
        value = original(document)
        stop.set()
        return value

    monkeypatch.setattr(reports, "validate_document", cancelled_validation)
    with pytest.raises(ContactAuditCancelled):
        reports.prepare_contact_audit(native, cancelled=stop.is_set)


def test_cancel_is_not_swallowed_inside_context_force_or_body_loops(native):
    stop = threading.Event()
    ctx = _Context(native.model, checkpoint=_AuditControl(cancelled=stop.is_set).checkpoint)
    active, used = ctx.activity(native.model.stages[0])
    stop.set()
    with pytest.raises(ContactAuditCancelled):
        ctx.soil_force(native.stages[0].sig, active)
    with pytest.raises(ContactAuditCancelled):
        ctx.bodies(active, used)


def test_point_reader_checkpoints_do_not_modify_existing_results(native):
    expected = contact_points(native, native.stages[0])
    calls = []
    assert contact_points(native, native.stages[0], checkpoint=lambda: calls.append(1)) == expected
    assert len(calls) >= 4

    def cancel():
        raise ContactAuditCancelled()

    with pytest.raises(ContactAuditCancelled):
        contact_points(native, native.stages[0], checkpoint=cancel)
    with pytest.raises(TypeError, match="callable"):
        contact_points(native, checkpoint=1)

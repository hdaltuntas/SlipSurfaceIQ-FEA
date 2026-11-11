"""Native removal/rebirth: stress-free activation is NOT a reset of physical position."""

from __future__ import annotations

import copy
import runpy
from pathlib import Path

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.post.contact_support_equilibrium import contact_support_equilibrium_by_stage

_B = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "scripts" / "f7_contact_reactivation_benchmark.py")
)
build_model, reference, evaluate, run_case = (
    _B[k] for k in ("build_model", "reference", "evaluate", "run_case")
)


@pytest.fixture(scope="module")
def specimen():
    model, fixture = build_model(element_type="IFACE6", initial_gap=0.002)
    return model, fixture, api.run(model)


@pytest.mark.parametrize("element_type", ["IFACE4", "IFACE6"])
@pytest.mark.parametrize("initial_gap", [0.0, 0.002])
@pytest.mark.parametrize("quarter_turn", [False, True])
@pytest.mark.parametrize("mode", ["force", "displacement", "mixed"])
def test_independent_rebirth_reference(element_type, initial_gap, quarter_turn, mode):
    out = run_case(
        element_type=element_type, initial_gap=initial_gap, quarter_turn=quarter_turn, mode=mode
    )
    assert out["status"] == "passed", out
    assert out["stage_count"] == 14
    for row in out["stages"]:
        assert all(c["status"] == "passed" for c in row["checks"].values())
        if row["stage_index"] in (0, 6, 9, 13):
            assert row["physical_only_equilibrium"]


@pytest.mark.parametrize("etype", ["IFACE4", "IFACE6"])
@pytest.mark.parametrize("columns", [1, 4])
def test_refined_mesh_and_midpoint_order(etype, columns):
    assert run_case(element_type=etype, columns=columns)["status"] == "passed"


def test_rational_birth_reference_and_no_resurrected_load():
    _, fixture = build_model()
    targets = reference(0.0, fixture["targets"])
    assert targets[1]["stress"][0] == pytest.approx(-389 / 42)
    # After three fractional releases (3/4,1/2,1/2), the lower displacement
    # freezes at (-389/224)/2400 even when that layer is subsequently reborn.
    assert targets[7]["levels"][0] == pytest.approx(-389 / 537600)
    assert targets[7]["stress"][0] == pytest.approx(0.0)
    assert targets[7]["levels"][1] == pytest.approx(-389 / 50400)
    assert targets[8]["start_stress"][1] == 0.0
    assert targets[8]["physical"][1] == pytest.approx(-0.25)  # total lower load -0.5
    assert 2 * targets[8]["physical"].sum() == pytest.approx(2.0)


def test_second_rebirth_does_not_restore_deleted_stress(specimen):
    model, fixture, result = specimen
    targets = reference(0.002, fixture["targets"])
    lower = model.mesh.block("lower")
    assert targets[11]["start_stress"][1] == 0.0
    assert abs(targets[11]["start_stress"][0]) > 1.0
    assert np.max(np.abs(result.stages[11].sig["lower"][lower.region == 2])) < 1e-10
    assert np.max(np.abs(result.stages[11].sig["lower"][lower.region == 1])) > 1.0


def test_native_reactivation_is_automatic_and_fresh_nodes_have_a_new_reporting_datum(specimen):
    model, _, result = specimen
    assert all("contact" in s.active_structures for s in model.stages)
    face = model.mesh.nodes("lower_contact")
    assert np.isnan(result.stages[7].u[face]).all()
    assert not result.stages[7].active["contact"].any()
    assert result.stages[8].active["contact"].all()
    assert np.isfinite(result.stages[8].u[face]).all()
    assert not result.stages[10].active["contact"].any()
    assert result.stages[11].active["contact"].all()


@pytest.mark.parametrize("etype", ["IFACE4", "IFACE6"])
def test_reporting_resets_do_not_change_physical_gap_stress_or_reactions(etype):
    a, af = build_model(element_type=etype, initial_gap=0.002)
    b, bf = build_model(element_type=etype, initial_gap=0.002, reporting_resets=False)
    ra, rb = api.run(a), api.run(b)
    assert evaluate(ra, a, af)["status"] == evaluate(rb, b, bf)["status"] == "passed"
    assert not np.allclose(ra.last.u, rb.last.u, equal_nan=True)
    for sa, sb in zip(ra.stages, rb.stages):
        np.testing.assert_allclose(sa.contact_gap["contact"], sb.contact_gap["contact"], atol=1e-12)
        np.testing.assert_allclose(sa.reactions, sb.reactions, atol=1e-8)
        for tag in sa.sig:
            np.testing.assert_allclose(sa.sig[tag], sb.sig[tag], atol=1e-8)


def test_old_general_audit_still_rejects_reactivation(specimen):
    out = contact_support_equilibrium_by_stage(specimen[2])
    assert out["status"] == "failed"
    assert any(r["status"] == "unsupported" for r in out["stages"])


@pytest.mark.parametrize(
    "error",
    [
        "old_stress",
        "survivor_stress",
        "inactive_stress",
        "balanced_reactions",
        "free_reaction",
        "missing_reaction",
        "nonfinite_reaction",
        "rotation",
        "wrong_u",
        "inactive_u_zero",
        "active_u_nan",
        "reported_gap",
        "wrong_pressure",
        "shear",
        "inactive_gap",
        "inactive_traction",
        "inactive_status",
        "wrong_status",
        "contact_active",
        "continuum_active",
        "mask_type",
        "fraction",
        "boolean_fraction",
        "missing_map",
        "missing_stage",
        "extra_stage",
        "name",
        "shape",
        "status_type",
        "initial_stress",
        "initial_u",
        "initial_fraction",
        "initial_activity",
        "initial_gap",
    ],
)
def test_bad_evidence_fails_closed(specimen, error):
    model, fixture, original = specimen
    result = copy.deepcopy(original)
    stage = result.stages[11]
    removed = result.stages[5]
    face = model.mesh.nodes("lower_contact")
    if error == "old_stress":
        stage.sig["lower"][model.mesh.block("lower").region == 2] = original.stages[9].sig["lower"][
            model.mesh.block("lower").region == 2
        ]
    elif error == "survivor_stress":
        stage.sig["upper"][:] = 0.0
    elif error == "inactive_stress":
        removed.sig["lower"][:] = 1.0
    elif error == "balanced_reactions":
        a, b = model.mesh.nodes("top")[:2]
        stage.reactions[a, 1] += 1
        stage.reactions[b, 1] -= 1
    elif error == "free_reaction":
        stage.reactions[face[0], 1] += 1
    elif error == "missing_reaction":
        result.stages[9].reactions[:] = 0.0
    elif error == "nonfinite_reaction":
        stage.reactions[0, 0] = float("nan")
    elif error == "rotation":
        stage.reactions[0, 2] = 1.0
    elif error == "wrong_u":
        stage.u[face[0], 1] += 0.001
    elif error == "inactive_u_zero":
        removed.u[face] = 0.0
    elif error == "active_u_nan":
        stage.u[face[0]] = np.nan
    elif error == "reported_gap":
        stage.contact_gap["contact"][:] = 0.002  # incorrect birth reset
    elif error == "wrong_pressure":
        result.stages[9].interfaces["contact"][..., 1] = 0.0
    elif error == "shear":
        stage.interfaces["contact"][..., 0] = 1.0
    elif error == "inactive_gap":
        removed.contact_gap["contact"][:] = 0.0
    elif error == "inactive_traction":
        removed.interfaces["contact"][:] = 0.0
    elif error == "inactive_status":
        removed.contact_status["contact"][:] = 0
    elif error == "wrong_status":
        stage.contact_status["contact"][:] = 2
    elif error == "contact_active":
        stage.active["contact"][:] = False
    elif error == "continuum_active":
        stage.active["lower"][:] = False
    elif error == "mask_type":
        stage.active["lower"] = stage.active["lower"].astype(int)
    elif error == "fraction":
        stage.lam = 1.0
    elif error == "boolean_fraction":
        result.stages[0].lam = True
    elif error == "missing_map":
        del stage.contact_gap["contact"]
    elif error == "missing_stage":
        result.stages.pop()
    elif error == "extra_stage":
        result.stages.append(copy.deepcopy(result.last))
    elif error == "name":
        stage.name = "not this snapshot"
    elif error == "shape":
        stage.sig["lower"] = stage.sig["lower"][:, :1]
    elif error == "status_type":
        stage.contact_status["contact"] = stage.contact_status["contact"].astype(float)
    elif error == "initial_stress":
        result.initial.sig["upper"][:] = 1.0
    elif error == "initial_u":
        result.initial.u[:] = 1.0
    elif error == "initial_fraction":
        result.initial.lam = 0.5
    elif error == "initial_activity":
        result.initial.active["contact"][:] = False
    elif error == "initial_gap":
        result.initial.contact_gap["contact"][:] = 0.0
    else:
        raise AssertionError(error)
    try:
        report = evaluate(result, model, fixture)
    except (ValueError, KeyError, TypeError):
        return
    assert report["status"] == "failed", error


@pytest.mark.parametrize("fmt", ["json", "h5", "ssproj"])
def test_roundtrip_re_solve_and_nonmutation(specimen, tmp_path, fmt):
    model, fixture, result = specimen
    original = copy.deepcopy(result)
    path = tmp_path / f"rebirth.{fmt}"
    if fmt == "json":
        api.save_model(model, path)
        restored_model = api.load_model(path)
        restored = api.run(restored_model)
    elif fmt == "h5":
        api.save_results(result, path)
        restored = api.load_results(path)
        restored_model = restored.model
    else:
        api.save_project(model, path, result)
        project = api.load_project(path)
        restored_model, restored = project.model, project.results
    assert evaluate(restored, restored_model, fixture)["status"] == "passed"
    assert evaluate(result, model, fixture)["status"] == "passed"
    for a, b in zip(result.stages, original.stages):
        np.testing.assert_array_equal(a.u, b.u)
        np.testing.assert_array_equal(a.sig["lower"], b.sig["lower"])
        np.testing.assert_array_equal(a.contact_gap["contact"], b.contact_gap["contact"])


@pytest.mark.parametrize("gap", [-1.0, True, float("nan")])
def test_invalid_initial_clearance_is_not_silently_accepted(gap):
    _, fixture = build_model()
    with pytest.raises(ValueError):
        reference(gap, fixture["targets"])


def test_missing_and_nonfinite_targets_rejected():
    _, fixture = build_model()
    with pytest.raises(ValueError):
        reference(0.0, fixture["targets"][:-1])
    targets = list(fixture["targets"])
    targets[0] = (0.0, float("nan"), 0.0)
    with pytest.raises(ValueError):
        reference(0.0, targets)


def test_cli_failure_is_not_a_success(monkeypatch, tmp_path):
    import sys

    module = _B["main"].__globals__
    monkeypatch.setitem(module, "run_benchmark", lambda: {"status": "failed", "cases": []})
    path = tmp_path / "failed.json"
    example = tmp_path / "must-not-exist.ssproj"
    monkeypatch.setattr(
        sys, "argv", ["benchmark", "--output", str(path), "--example", str(example)]
    )
    assert _B["main"]() == 1
    assert path.exists() and not example.exists()

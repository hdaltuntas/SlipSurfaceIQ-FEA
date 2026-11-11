"""Native restraint release, independent scalar targets and falsification tests."""

from __future__ import annotations

import copy
import json
import pickle
import runpy
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.errors import NonConvergence, SingularSystemError
from slipsurface.fe2d.post import contact_activation_equilibrium as history
from slipsurface.fe2d.post.contact_partial_equilibrium import contact_partial_equilibrium_by_stage
from slipsurface.fe2d.post.contact_support_equilibrium import contact_support_equilibrium_by_stage

_BENCH = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts"
                            / "f7_contact_support_benchmark.py"))
audit = contact_support_equilibrium_by_stage


@lru_cache(maxsize=8)
def solved(etype="IFACE4", gap=0.0, variant="support_only"):
    model, _ = _BENCH["build_model"](element_type=etype, initial_gap=gap, variant=variant)
    return api.run(model)


@pytest.fixture
def result():
    return copy.deepcopy(solved())


@pytest.mark.parametrize("etype", ["IFACE4", "IFACE6"])
@pytest.mark.parametrize("gap", [0.0, 0.002])
@pytest.mark.parametrize("rotation", [False, True])
@pytest.mark.parametrize("variant", _BENCH["VARIANTS"])
def test_actual_native_history_matches_independent_targets(etype, gap, rotation, variant):
    report = _BENCH["run_case"](element_type=etype, initial_gap=gap, quarter_turn=rotation,
                              variant=variant)
    assert report["status"] == "passed", report
    assert report["stage_count"] == 9
    assert len(report["independent_reference_checks"]) == 9
    assert all(row["status"] == "passed" for row in report["independent_reference_checks"])
    json.dumps(report, allow_nan=False)


def test_rational_hand_values_for_removed_reaction_and_retained_force(result):
    # k=2400, kn=2000, W=2, b=-.006, v=-.008, F=-16.
    # t=-72/11 kPa; Rclamp=2*(24/5 -72/11 +8)=688/55 kN/m.
    top_nodes = result.model.mesh.nodes("temporary")
    assert result.stages[0].reactions[top_nodes, 1].sum() == pytest.approx(688/55)
    first, held = audit(result)["stages"][1:3]
    assert first["physical_external_resultant"][1] == pytest.approx(-17)
    assert sum(first["support_changes"]["released_previous_reactions"]) == pytest.approx(688/55)
    assert sum(first["support_changes"]["released_retained_force"]) == pytest.approx(516/55)
    assert first["physical_global_residual"][1] == pytest.approx(-516/55)
    assert held["physical_global_residual"][1] == pytest.approx(-258/55)
    assert np.all(result.stages[1].reactions[top_nodes, 1] == 0)
    assert first["physical_equilibrium"]["status"] == "failed"  # not hidden by overall pass
    assert first["status"] == "passed"  # transition equilibrium, not physical equilibrium


def test_full_release_clears_pseudo_load_and_does_not_retain_a_reaction(result):
    rows = audit(result)["stages"]
    for index in (3, 6, 8):
        assert rows[index]["physical_equilibrium"]["status"] == "passed"
        np.testing.assert_array_equal(rows[index]["history"]["retained_release_nodal"], 0)
    assert rows[8]["support_changes"]["released_dofs"]
    assert rows[8]["support_changes"]["released_retained_force"] == [0.0]*3


def test_reintroduced_support_interpolates_previous_free_displacement(result):
    row = audit(result)["stages"][4]
    assert row["support_changes"]["added_dofs"]
    assert row["checks"]["prescribed_displacement_history_m"]["status"] == "passed"
    nodes = result.model.mesh.nodes("temporary")
    # Reporting was reset on stage 4; difference equals alpha*(target-previous TOTAL u).
    previous_total = result.stages[3].u[nodes, 1]+result.stages[0].u[nodes, 1]
    np.testing.assert_allclose(result.stages[4].u[nodes, 1], .6*(.006-previous_total), atol=1e-12)


def test_original_fixed_support_audits_still_reject_changed_membership(result):
    old = history.contact_activation_equilibrium_by_stage(result)
    assert old["status"] == "failed"
    assert old["stages"][0]["status"] == "unsupported"
    assert "membership" in old["stages"][0]["reason"]
    assert contact_partial_equilibrium_by_stage(result)["status"] == "failed"


def test_unchanged_support_histories_produce_identical_old_outputs():
    old_bench = _BENCH["_BASE"]
    model, _ = old_bench["build_model"](element_type="IFACE6", initial_gap=.002, mode="mixed")
    result = api.run(model)
    original = history.contact_activation_equilibrium_by_stage(result)
    extended = audit(result)
    assert original["status"] == extended["status"] == "passed"
    for before, after in zip(original["stages"], extended["stages"]):
        assert before["history"] == after["history"]
        assert before["partitions"] == after["partitions"]
        assert all(after["checks"][key] == value for key, value in before["checks"].items())


@pytest.mark.parametrize("corruption", [
    "released_reaction", "balanced_reactions", "stress", "pressure", "gap", "status",
    "prescribed_u", "missing_release", "missing_reclamp", "reset", "activity",
])
def test_false_evidence_is_detected_and_later_full_stages_are_blocked(result, corruption):
    mesh = result.model.mesh
    stage = result.stages[1]
    if corruption == "released_reaction":
        stage.reactions[mesh.nodes("temporary")[0], 1] = 1
    elif corruption == "balanced_reactions":
        stage.reactions[mesh.nodes("bottom")[0], 1] += 1
        stage.reactions[mesh.nodes("top")[0], 1] -= 1
    elif corruption == "stress":
        stage.sig["upper"][..., 1] += 1
    elif corruption == "pressure":
        stage.interfaces["contact"][..., 1] -= 1
    elif corruption == "gap":
        stage.contact_gap["contact"] -= .001
    elif corruption == "status":
        stage.contact_status["contact"][:] = 255
    elif corruption == "prescribed_u":
        result.stages[4].u[mesh.nodes("temporary"), 1] += .001
    elif corruption == "missing_release":
        definition = result.model.stages[1]
        result.model.stages[1] = replace(definition, displacements=(
            *definition.displacements, api.Displacement("temporary", uy=-.006)))
    elif corruption == "missing_reclamp":
        definition = result.model.stages[4]
        result.model.stages[4] = replace(definition, displacements=definition.displacements[:1])
    elif corruption == "reset":
        result.model.stages[1] = replace(result.model.stages[1], reset_displacements=False)
    else:
        stage.active["contact"][:] = False
    report = audit(result)
    assert report["status"] == "failed"
    failed = next(i for i, row in enumerate(report["stages"]) if row["status"] != "passed")
    assert report["stages"][failed]["status"] in ("failed", "invalid")
    assert all(row["status"] == "blocked" for row in report["stages"][failed+1:])
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("mapping", [
    "sig", "contact_gap", "contact_status", "active", "interfaces",
])
def test_missing_stage_evidence_is_not_a_zero_load(result, mapping):
    getattr(result.stages[1], mapping).clear()
    report = audit(result)
    assert report["stages"][1]["status"] == "invalid"
    assert report["stages"][-1]["status"] == "blocked"


@pytest.mark.parametrize("field", ["u", "reactions", "sig"])
def test_nonfinite_initial_evidence_blocks_all_support_release_claims(result, field):
    if field == "sig":
        result.initial.sig["upper"][0, 0, 1] = np.nan
    else:
        getattr(result.initial, field)[0, 0] = np.nan
    report = audit(result)
    assert report["initial_status"] == "invalid"
    assert all(row["status"] == "blocked" for row in report["stages"])


@pytest.mark.parametrize("bad", [0, -.5, 1.5, True, np.nan, np.inf])
def test_invalid_fraction_cannot_hide_released_force(result, bad):
    result.stages[1].lam = bad
    assert audit(result)["stages"][1]["status"] == "invalid"


@pytest.mark.parametrize("name", ["force_atol", "moment_atol", "gap_atol", "traction_atol", "rtol"])
@pytest.mark.parametrize("value", [0, np.nan, True])
def test_invalid_tolerance_is_rejected(result, name, value):
    with pytest.raises(ValueError, match="positive finite"):
        audit(result, **{name: value})


@pytest.mark.parametrize("kind", ["water", "seismic", "excavation", "material", "gravity"])
def test_unrelated_model_scope_is_not_silently_widened(result, kind):
    definition = result.model.stages[1]
    if kind == "water":
        definition = replace(definition, water=api.WaterCondition(
            "piezo_line", piezo_polyline=np.array([[0., 5.], [10., 5.]])))
    elif kind == "seismic":
        definition = replace(definition, seismic_kh=.1)
    elif kind == "excavation":
        definition = replace(definition, active_regions=set())
    elif kind == "material":
        definition = replace(definition, material_override={1: "soil"})
    else:
        result.model.initial = replace(result.model.initial, gravity=True)
    result.model.stages[1] = definition
    report = audit(result)
    assert report["status"] == "failed"
    assert report["initial_status"] != "passed" or report["stages"][1]["status"] == "unsupported"


def test_releasing_the_last_real_support_does_not_invent_stabilizing_stiffness():
    model, _ = _BENCH["build_model"]()
    # First load with stage restraints; then release the upper body into open contact.
    model.fixities = model.fixities[:2]  # tangential restraint and lower-body base
    model.stages = [model.stages[0], replace(
        model.stages[1], active_structures=set(), displacements=(),
    )]
    with pytest.raises((NonConvergence, SingularSystemError)):
        api.run(model)


def test_audit_does_not_use_previous_reaction_as_external_load(result):
    bad = copy.deepcopy(result)
    bad.stages[0].reactions[bad.model.mesh.nodes("temporary"), 1] *= 2
    assert audit(bad)["stages"][1]["status"] == "blocked"
    assert audit(result)["stages"][1]["physical_external_resultant"][1] == pytest.approx(-17)


def test_moment_origin_translation_duplicate_names_and_nonmutation(result):
    original = pickle.dumps(result)
    first, second = audit(result), audit(result, origin=(4.0, -7.0))
    assert first["status"] == second["status"] == "passed"
    assert pickle.dumps(result) == original
    for a, b in zip(first["stages"], second["stages"]):
        fx, fy, moment = a["retained_release_resultant"]
        assert b["retained_release_resultant"][2] == pytest.approx(moment-4*fy-7*fx, abs=1e-12)
    assert first["stages"][1]["stage"] == first["stages"][2]["stage"]
    assert first["stages"][1]["stage_index"] != first["stages"][2]["stage_index"]


@pytest.mark.parametrize("fmt", ["h5", "ssproj", "json"])
def test_native_persistence_and_resolve_preserve_support_history(tmp_path, fmt):
    result = copy.deepcopy(solved("IFACE6", .002, "support_and_contact"))
    path = tmp_path / ("support."+fmt)
    if fmt == "h5":
        api.save_results(result, path)
        restored = api.load_results(path)
    elif fmt == "ssproj":
        api.save_project(result.model, path, result)
        restored = api.load_project(path).results
    else:
        api.save_model(result.model, path)
        restored = api.run(api.load_model(path))
    assert audit(restored) == audit(result)


def test_cli_preserves_evidence_and_fails_for_a_corrupted_report(tmp_path, monkeypatch):
    main = _BENCH["main"]
    monkeypatch.setitem(main.__globals__, "run_benchmark", lambda: {"status": "failed"})
    path = tmp_path / "failed.json"
    monkeypatch.setattr("sys.argv", ["benchmark", "--output", str(path)])
    assert main() == 1
    assert json.loads(path.read_text()) == {"status": "failed"}

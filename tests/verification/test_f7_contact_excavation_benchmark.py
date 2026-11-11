"""Native layered removal: independent fields, lost nodes and falsified evidence."""

from __future__ import annotations

import copy
import runpy
from pathlib import Path

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.post.contact_support_equilibrium import contact_support_equilibrium_by_stage

_B = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "scripts" / "f7_contact_excavation_benchmark.py")
)
build_model, reference, evaluate, run_case = (
    _B[k]
    for k in (
        "build_model",
        "reference",
        "evaluate",
        "run_case",
    )
)


@pytest.fixture(scope="module")
def specimen():
    model, fixture = build_model(element_type="IFACE6", initial_gap=0.002)
    return model, fixture, api.run(model)


@pytest.mark.parametrize("element_type", ["IFACE4", "IFACE6"])
@pytest.mark.parametrize("initial_gap", [0.0, 0.002])
@pytest.mark.parametrize("quarter_turn", [False, True])
@pytest.mark.parametrize("mode", ["force", "displacement", "mixed"])
def test_native_excavation_matches_closed_form(element_type, initial_gap, quarter_turn, mode):
    report = run_case(
        element_type=element_type, initial_gap=initial_gap, quarter_turn=quarter_turn, mode=mode
    )
    assert report["status"] == "passed", report
    assert report["stage_count"] == 8
    for row in report["stages"]:
        assert all(c["status"] == "passed" for c in row["checks"].values())
        if row["stage_index"] in (0, 4, 7):
            assert row["physical_only_equilibrium"]


@pytest.mark.parametrize("element_type", ["IFACE4", "IFACE6"])
@pytest.mark.parametrize("columns", [1, 4])
def test_mesh_refinement_keeps_exact_layer_response(element_type, columns):
    assert run_case(element_type=element_type, columns=columns)["status"] == "passed"


def test_hand_rational_excavation_release_and_disappearing_applied_load():
    _, fixture = build_model()
    targets = reference(0.0, fixture["targets"])
    before, removed, next_stage = targets[1:4]
    assert before["lower_stress"] == pytest.approx(-389 / 42)
    assert before["traction"] == pytest.approx(-142 / 21)
    assert removed["lower_release"] == pytest.approx(-389 / 28)
    assert removed["upper_release"] == pytest.approx(71 / 7)
    # Previous upper load -14, target -10, alpha=1/4 -> -13.
    # Previous LOWER load -5 was on removed nodes; its -3.75 remainder is NOT applied.
    assert removed["physical_load"] == pytest.approx(-13)
    assert removed["lower_release"] + removed["upper_release"] == pytest.approx(-3.75)
    assert next_stage["lower_release"] == pytest.approx(-389 / 56)
    assert next_stage["upper_release"] == pytest.approx(71 / 14)
    assert targets[4]["lower_release"] == targets[4]["upper_release"] == 0


def test_global_cancellation_does_not_hide_body_retained_release():
    r = run_case(mode="displacement")
    row = r["stages"][2]
    assert abs(row["physical_force_residual_kn_per_m"]) < 1e-8
    assert not row["physical_only_equilibrium"]
    assert row["physical_nodal_residual_max"] > 0.1


def test_automatic_contact_deactivation_even_though_tag_stays_requested(specimen):
    model, _, r = specimen
    assert all("contact" in stage.active_structures for stage in model.stages)
    assert r.stages[1].active["contact"].all()
    for stage in r.stages[2:]:
        assert not stage.active["contact"].any()
        assert np.all(stage.contact_status["contact"] == 255)
        assert np.isnan(stage.interfaces["contact"]).all()
        assert np.isnan(stage.contact_gap["contact"]).all()


def test_removed_nodes_never_become_fictitious_zero_displacements(specimen):
    model, _, r = specimen
    removed = model.mesh.nodes("lower_contact")
    assert np.isnan(r.stages[2].u[removed]).all()
    assert np.all(r.stages[2].reactions[removed] == 0)
    assert r.stages[2].active["lower"].sum() > 0  # the shared block is only partly removed
    assert not r.stages[5].active["lower"].any()


def test_previous_general_audit_still_rejects_excavation(specimen):
    # This PR verifies an exact fixture; it must not pretend #86's API became general.
    r = contact_support_equilibrium_by_stage(specimen[2])
    assert r["status"] == "failed"
    assert any(s["status"] == "unsupported" for s in r["stages"])


@pytest.mark.parametrize(
    "corruption",
    [
        "balanced_reactions",
        "released_reaction",
        "inactive_reaction",
        "stress",
        "removed_stress",
        "traction",
        "gap",
        "status",
        "contact_active",
        "bulk_active",
        "zero_inactive_u",
        "active_nan_u",
        "wrong_displacement",
        "rotational_reaction",
        "nan_reaction",
        "inactive_gap",
        "inactive_traction",
        "inactive_status",
        "fraction",
        "boolean_fraction",
        "missing_map",
        "missing_stage",
        "extra_stage",
        "wrong_name",
        "bad_shape",
        "initial_gap",
        "initial_stress",
        "initial_status",
        "initial_fraction",
        "mask_dtype",
    ],
)
def test_corrupted_native_evidence_cannot_pass(specimen, corruption):
    model, fixture, original = specimen
    result = copy.deepcopy(original)
    st = result.stages[2]
    first = result.stages[0]
    if corruption == "balanced_reactions":
        a, b = model.mesh.nodes("top")[:2]
        st.reactions[a, 1] += 1
        st.reactions[b, 1] -= 1
    elif corruption == "released_reaction":
        st.reactions[model.mesh.nodes("upper_contact")[0], 1] += 1
    elif corruption == "inactive_reaction":
        st.reactions[model.mesh.nodes("lower_contact")[0], 1] += 1
    elif corruption == "stress":
        st.sig["upper"][0, 0, 0] += 1
    elif corruption == "removed_stress":
        st.sig["lower"][~st.active["lower"]] = 1
    elif corruption == "traction":
        first.interfaces["contact"][0, 0, 1] -= 1
    elif corruption == "gap":
        first.contact_gap["contact"][0, 0] += 0.001
    elif corruption == "status":
        first.contact_status["contact"][:] = 0
    elif corruption == "contact_active":
        st.active["contact"][:] = True
    elif corruption == "bulk_active":
        st.active["lower"][:] = True
    elif corruption == "zero_inactive_u":
        st.u[model.mesh.nodes("lower_contact")] = 0
    elif corruption == "active_nan_u":
        st.u[model.mesh.nodes("upper_contact")[0], 1] = np.nan
    elif corruption == "wrong_displacement":
        st.u[model.mesh.nodes("upper_contact")[0], 1] += 0.001
    elif corruption == "rotational_reaction":
        st.reactions[0, 2] = 1
    elif corruption == "nan_reaction":
        st.reactions[0, 1] = np.nan
    elif corruption == "inactive_gap":
        st.contact_gap["contact"][:] = 0
    elif corruption == "inactive_traction":
        st.interfaces["contact"][:] = 0
    elif corruption == "inactive_status":
        st.contact_status["contact"][:] = 0
    elif corruption == "fraction":
        st.lam = 0.9
    elif corruption == "boolean_fraction":
        result.stages[0].lam = True
    elif corruption == "missing_map":
        del st.sig["lower"]
    elif corruption == "missing_stage":
        result.stages.pop()
    elif corruption == "extra_stage":
        result.stages.append(copy.deepcopy(result.last))
    elif corruption == "wrong_name":
        st.name = "wrong"
    elif corruption == "bad_shape":
        st.contact_status["contact"] = np.empty((0,))
    elif corruption == "initial_gap":
        result.initial.contact_gap["contact"][:] += 1
    elif corruption == "initial_stress":
        result.initial.sig["lower"][:] = 1
    elif corruption == "initial_status":
        result.initial.contact_status["contact"][:] = 2
    elif corruption == "initial_fraction":
        result.initial.lam = 0.5
    elif corruption == "mask_dtype":
        st.active["lower"] = st.active["lower"].astype(int)
    else:
        raise AssertionError(corruption)
    try:
        report = evaluate(result, model, fixture)
    except (ValueError, KeyError, TypeError):
        return
    assert report["status"] == "failed", corruption


@pytest.mark.parametrize("fmt", ["json", "h5", "ssproj"])
def test_roundtrip_and_resolve(specimen, tmp_path, fmt):
    model, fixture, r = specimen
    path = tmp_path / f"excavation.{fmt}"
    if fmt == "json":
        api.save_model(model, path)
        other_model = api.load_model(path)
        other = api.run(other_model)
    elif fmt == "h5":
        api.save_results(r, path)
        other = api.load_results(path)
        other_model = other.model
    else:
        api.save_project(model, path, r)
        data = api.load_project(path)
        other_model, other = data.model, data.results
    assert evaluate(other, other_model, fixture)["status"] == "passed"
    for a, b in zip(r.stages, other.stages):
        np.testing.assert_allclose(a.u, b.u, atol=1e-12, equal_nan=True)
        np.testing.assert_allclose(a.reactions, b.reactions, atol=1e-9)


def test_evaluation_leaves_snapshots_unmodified(specimen):
    model, fixture, r = specimen
    before = copy.deepcopy(r)
    assert evaluate(r, model, fixture)["status"] == "passed"
    for a, b in zip(r.stages, before.stages):
        np.testing.assert_array_equal(a.u, b.u)
        np.testing.assert_array_equal(a.reactions, b.reactions)
        for k in a.sig:
            np.testing.assert_array_equal(a.sig[k], b.sig[k])


@pytest.mark.parametrize(
    "bad",
    [
        {"columns": 0},
        {"columns": True},
        {"element_type": "T3"},
        {"mode": "unknown"},
        {"initial_gap": -0.1},
        {"initial_gap": np.nan},
        {"quarter_turn": 2},
    ],
)
def test_invalid_fixture_settings_rejected(bad):
    with pytest.raises(ValueError):
        build_model(**bad)

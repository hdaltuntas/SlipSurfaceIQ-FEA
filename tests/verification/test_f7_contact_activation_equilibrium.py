"""Native contact switching, retained release, reference reconstruction and failure tests."""

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
from slipsurface.fe2d.core.errors import NonConvergence
from slipsurface.fe2d.fem.nonlinear import Problem, solve_stage
from slipsurface.fe2d.post import contact_activation_equilibrium as audit
from slipsurface.fe2d.post.contact_equilibrium import contact_equilibrium_by_stage
from slipsurface.fe2d.post.contact_partial_equilibrium import contact_partial_equilibrium_by_stage

_BENCH = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts"
                            / "f7_contact_activation_benchmark.py"))


@lru_cache(maxsize=8)
def _solved(etype="IFACE4", gap=0.0, mode="force"):
    model, _ = _BENCH["build_model"](element_type=etype, initial_gap=gap, mode=mode)
    return api.run(model)


@pytest.fixture
def result():
    return copy.deepcopy(_solved())


@pytest.mark.parametrize("etype", ["IFACE4", "IFACE6"])
@pytest.mark.parametrize("gap", [0.0, 0.002])
@pytest.mark.parametrize("mode", ["force", "displacement", "mixed"])
@pytest.mark.parametrize("rotated", [False, True])
def test_native_switching_histories_match_independent_two_layer_solution(etype, gap, mode, rotated):
    report = _BENCH["run_case"](element_type=etype, initial_gap=gap, mode=mode,
                                quarter_turn=rotated)
    assert report["status"] == "passed", report
    assert report["stage_count"] == 9
    assert all(r["status"] == "passed" for r in report["independent_reference_checks"])
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("etype", ["IFACE4", "IFACE6"])
@pytest.mark.parametrize("gap", [0.0, 0.002])
@pytest.mark.parametrize("rotated", [False, True])
def test_native_eccentric_switching_retains_point_edge_load_moments(etype, gap, rotated):
    report = _BENCH["run_case"](element_type=etype, initial_gap=gap, mode="mixed",
                                quarter_turn=rotated, eccentric=True)
    assert report["status"] == "passed", report
    assert len(report["independent_reference_checks"]) == 9


def test_hand_calculated_release_is_not_another_physical_applied_load(result):
    report = audit.contact_activation_equilibrium_by_stage(result)
    first, removed, held, reactivated = report["stages"][:4]
    # Initial uniform closure: t=-2.5 kPa; two faces each have |F|=5 kN/m.
    np.testing.assert_allclose(result.stages[0].interfaces["contact"][..., 1], -2.5)
    assert first["physical_external_resultant"][1] == pytest.approx(-16)
    assert removed["physical_external_resultant"][1] == pytest.approx(-17)
    assert removed["partitions"][0]["retained_release"][1] == pytest.approx(-3.75)
    assert removed["partitions"][1]["retained_release"][1] == pytest.approx(3.75)
    # No second activation change: preceding unfinished release still decays, not zeroed.
    assert held["partitions"][0]["retained_release"][1] == pytest.approx(-1.875)
    assert max(abs(x) for x in removed["physical_global_residual"]) < 1e-10
    assert np.max(np.abs(removed["history"]["retained_release_nodal"])) > 1.0
    assert np.isnan(result.stages[2].contact_gap["contact"]).all()
    assert np.min(reactivated["history"]["start_geometric_gap_m"]["contact"]) < 0
    assert "external_resultant" not in removed  # do not mislabel effective pseudo-load


def test_full_stage_clears_retained_term_and_passes_existing_full_budget(result):
    report = audit.contact_activation_equilibrium_by_stage(result)
    np.testing.assert_array_equal(report["stages"][-1]["history"]["retained_release_nodal"], 0)
    view = replace(result, model=replace(result.model, stages=[result.model.stages[-1]]),
                   stages=[result.last])
    assert contact_equilibrium_by_stage(view)["status"] == "passed"


def test_previous_audit_contracts_are_not_weakened(result):
    assert contact_equilibrium_by_stage(result)["status"] == "failed"
    assert contact_partial_equilibrium_by_stage(result)["status"] == "failed"


def test_report_resets_do_not_reset_contact_geometry(result):
    row = audit.contact_activation_equilibrium_by_stage(result)
    assert row["status"] == "passed"
    assert row["stages"][2]["history"]["report_datum_reset"]
    assert row["stages"][3]["checks"]["stored_geometric_gap_m"]["status"] == "passed"
    result.model.stages[2] = replace(result.model.stages[2], reset_displacements=False)
    bad = audit.contact_activation_equilibrium_by_stage(result)
    assert bad["status"] == "failed"
    assert any(s["status"] in ("failed", "invalid") for s in bad["stages"])


def test_equal_opposite_false_reactions_fail_even_when_global_sum_passes(result):
    st, mesh = result.stages[1], result.model.mesh
    st.reactions[mesh.nodes("bottom")[0], 1] += 2
    st.reactions[mesh.nodes("top")[0], 1] -= 2
    report = audit.contact_activation_equilibrium_by_stage(result)
    row = report["stages"][1]
    assert row["checks"]["global_force_kn_per_m"]["status"] == "passed"
    assert row["checks"]["nodal_force_kn_per_m"]["status"] == "failed"
    assert all(r["status"] == "blocked" for r in report["stages"][2:])


@pytest.mark.parametrize("bad", ["pressure", "gap", "status", "stress", "reaction", "rotation",
                                 "u", "activity", "free_reaction", "inactive_measurement"])
def test_corruption_is_detected_and_dependent_claims_blocked(result, bad):
    st = result.stages[3]
    if bad == "pressure":
        st.interfaces["contact"][..., 1] -= 1
    elif bad == "gap":
        st.contact_gap["contact"] -= .001
    elif bad == "status":
        st.contact_status["contact"][:] = 0
    elif bad == "stress":
        st.sig["upper"][..., 1] += 1
    elif bad == "reaction":
        st.reactions[0, 0] = np.nan
    elif bad == "rotation":
        st.reactions[0, 2] = 1
    elif bad == "u":
        st.u[result.model.mesh.nodes("upper_contact"), 1] += .001
    elif bad == "activity":
        st.active["contact"][:] = False
    elif bad == "free_reaction":
        st.reactions[result.model.mesh.nodes("upper_contact")[0], 1] += 1
    else:
        result.stages[1].interfaces["contact"][:] = 0
    report = audit.contact_activation_equilibrium_by_stage(result)
    assert report["status"] == "failed"
    failed = next(i for i, r in enumerate(report["stages"]) if r["status"] != "passed")
    assert report["stages"][failed]["status"] in ("failed", "invalid")
    assert all(r["status"] == "blocked" for r in report["stages"][failed+1:])
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("field", ["sig", "contact_gap", "contact_status", "interfaces", "active"])
def test_missing_previous_snapshots_block_new_activation(result, field):
    getattr(result.stages[1], field).clear()
    report = audit.contact_activation_equilibrium_by_stage(result)
    assert report["stages"][1]["status"] == "invalid"
    assert report["stages"][3]["status"] == "blocked"


@pytest.mark.parametrize("bad", ["u", "stress", "reaction", "lambda", "maps"])
def test_invalid_initial_state_blocks_entire_history(result, bad):
    if bad == "u":
        result.initial.u[0, 1] = .001
    elif bad == "stress":
        result.initial.sig["lower"][..., 0] = .001
    elif bad == "reaction":
        result.initial.reactions[0, 0] = .001
    elif bad == "lambda":
        result.initial.lam = .5
    else:
        result.initial.contact_gap.clear()
    report = audit.contact_activation_equilibrium_by_stage(result)
    assert report["initial_status"] == "invalid"
    assert all(s["status"] == "blocked" for s in report["stages"])


@pytest.mark.parametrize("value", [0, -1, 1.1, True, np.nan, np.inf, "0.25"])
def test_invalid_fraction_fails_closed(result, value):
    result.stages[1].lam = value
    report = audit.contact_activation_equilibrium_by_stage(result)
    assert report["stages"][1]["status"] == "invalid"


@pytest.mark.parametrize("kind", ["missing", "extra", "name", "fraction", "reset_type"])
def test_stage_identity_and_reset_contracts(result, kind):
    if kind == "missing":
        result.stages.pop()
    elif kind == "extra":
        result.stages.append(result.last)
    elif kind == "name":
        result.stages[1].name = "wrong"
    elif kind == "fraction":
        result.model.stages[1] = replace(result.model.stages[1], load_split=.5)
    else:
        result.model.stages[1] = replace(result.model.stages[1], reset_displacements="yes")
    assert audit.contact_activation_equilibrium_by_stage(result)["status"] == "failed"


def test_no_mutation_duplicate_names_and_nonzero_moment_origin(result):
    before = pickle.dumps(result)
    a = audit.contact_activation_equilibrium_by_stage(result)
    b = audit.contact_activation_equilibrium_by_stage(result, origin=(10.0, -20.0))
    assert a["status"] == b["status"] == "passed"
    assert pickle.dumps(result) == before
    for x, y in zip(a["stages"], b["stages"]):
        fx, fy, moment = x["physical_external_resultant"]
        assert y["physical_external_resultant"][2] == pytest.approx(moment-10*fy-20*fx)
    assert a["stages"][1]["stage"] == a["stages"][2]["stage"]
    assert a["stages"][1]["stage_index"] != a["stages"][2]["stage_index"]


@pytest.mark.parametrize("kind", ["support", "excavation", "water", "material", "seismic"])
def test_out_of_scope_changes_remain_unsupported(result, kind):
    st = result.model.stages[1]
    if kind == "support":
        # Add prescribed normal motion at a previously free contact node set.
        st = replace(st, displacements=(*st.displacements,
                                       api.Displacement("upper_contact", uy=0.0)))
    elif kind == "excavation":
        st = replace(st, active_regions=set())
    elif kind == "water":
        st = replace(st, water=api.WaterCondition("piezo_line",
                       piezo_polyline=np.array([[0., 5.], [10., 5.]])))
    elif kind == "material":
        st = replace(st, material_override={1: "soil"})
    else:
        st = replace(st, seismic_kh=.1)
    result.model.stages[1] = st
    report = audit.contact_activation_equilibrium_by_stage(result)
    assert report["status"] == "failed"
    # The existing native model validator may reject an unsupported model at initial preflight.
    assert report["initial_status"] != "passed" or report["stages"][1]["status"] == "unsupported"


def test_disappearing_contact_only_nodes_are_not_guessed():
    original = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts"
                                  / "f7_contact_static_benchmark.py"))
    model, _ = original["build_model"]()
    report = audit.contact_activation_equilibrium_by_stage(api.run(model))
    assert report["initial_status"] == "unsupported"
    assert "Every node" in report["reason"]


@pytest.mark.parametrize("parameter", ["force_atol", "moment_atol", "traction_atol", "gap_atol",
                                       "rtol"])
@pytest.mark.parametrize("value", [0, np.nan, True])
def test_invalid_tolerance_never_loosens_acceptance(result, parameter, value):
    with pytest.raises(ValueError, match="positive finite"):
        audit.contact_activation_equilibrium_by_stage(result, **{parameter: value})


@pytest.mark.parametrize("fmt", ["h5", "ssproj"])
def test_snapshot_roundtrip_retains_release_evidence(tmp_path, fmt):
    solved = _solved("IFACE6", .002, "mixed")
    path = tmp_path / ("two-bodies."+fmt)
    if fmt == "h5":
        api.save_results(solved, path)
        restored = api.load_results(path)
    else:
        api.save_project(solved.model, path, solved)
        restored = api.load_project(path).results
    first = audit.contact_activation_equilibrium_by_stage(solved)
    second = audit.contact_activation_equilibrium_by_stage(restored)
    assert first == second
    assert second["status"] == "passed"


def test_start_contact_must_use_original_geometry_not_inactive_nan_gap(result, monkeypatch):
    original = audit._geometric_contact

    def wrong(model, total_u, active):
        force, gaps = original(model, total_u, active)
        return np.zeros_like(force), gaps

    monkeypatch.setattr(audit, "_geometric_contact", wrong)
    report = audit.contact_activation_equilibrium_by_stage(result)
    assert report["stages"][0]["status"] == "passed"
    assert report["stages"][3]["status"] == "failed"


def _predictor_problem(*, scaled=True, stubborn=False, amplitude=1.0):
    """Three scalar DOFs: two spring-supported faces and prescribed top motion."""
    committed = np.zeros(3)
    commits = []
    gap0, k, kn = .005, 1000., 2000.

    def integrate(du):
        u = committed+du
        a, b, v = u
        gap = gap0+b-a
        t = kn*min(gap, 0.)
        force = np.array([k*a-t, k*(b-v)+t, k*(v-b)])
        if stubborn and gap < 0:
            force = np.array([amplitude, -amplitude, 0.0])
        return u, force

    class Factor:
        def __init__(self, u):
            active = kn if gap0+u[1]-u[0] <= 0 else 0.
            self.matrix = np.array([[k+active, -active], [-active, k+active]])
            self.Kfp = np.array([[0.0], [-k]])

        def solve(self, rhs):
            return np.linalg.solve(self.matrix, rhs)

    def factor(kind, trial):
        return Factor(committed if kind != "tangent" else trial)

    def commit(trial, du):
        committed[:] = du
        commits.append(du.copy())

    return Problem(3, np.array([0, 1]), np.array([2]), integrate, factor, commit,
                   roundoff_force_scale=(lambda du: 100.0) if scaled else None), commits


def test_contact_closure_predictor_gets_a_correction_not_a_false_acceptance():
    problem, commits = _predictor_problem()
    settings = api.SolverSettings(dlam0=1.0, dlam_min=.9, dlam_max=1.0, line_search=False)
    _, du, history = solve_stage(problem, np.zeros(3), np.zeros(3), np.array([-.01]),
                                 settings, False)
    np.testing.assert_allclose(du, [-.002, -.008, -.01], atol=1e-14)
    assert history.steps[-1].iterations >= 2
    assert history.steps[-1].force_norms[1] > 1
    assert history.steps[-1].residuals[1] > 1e8
    assert history.steps[-1].force_norms[-1] < 1e-10
    assert len(commits) == 1


def test_legacy_no_callback_divergence_path_is_unchanged():
    problem, commits = _predictor_problem(scaled=False)
    settings = api.SolverSettings(dlam0=1.0, dlam_min=.9, dlam_max=1.0, line_search=False)
    with pytest.raises(NonConvergence) as caught:
        solve_stage(problem, np.zeros(3), np.zeros(3), np.array([-.01]), settings, False)
    assert caught.value.history.steps[-1].termination == "nonfinite_or_divergent"
    assert not commits


@pytest.mark.parametrize("amplitude", [1.0, 1e12])
def test_real_divergence_still_rejected_without_committing(amplitude):
    problem, commits = _predictor_problem(stubborn=True, amplitude=amplitude)
    settings = api.SolverSettings(dlam0=1.0, dlam_min=.9, dlam_max=1.0, line_search=False)
    with pytest.raises(NonConvergence):
        solve_stage(problem, np.zeros(3), np.zeros(3), np.array([-.01]), settings, False)
    assert not commits


def test_cli_failure_report_is_preserved(tmp_path, monkeypatch):
    target = tmp_path / "failed.json"
    main = _BENCH["main"]
    monkeypatch.setitem(main.__globals__, "run_benchmark", lambda: {"status": "failed"})
    monkeypatch.setattr("sys.argv", ["audit", "--output", str(target)])
    assert main() == 1
    assert json.loads(target.read_text())["status"] == "failed"

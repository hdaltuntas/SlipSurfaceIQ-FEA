"""Native staged-solver contact: analytical equilibrium, state and serialization."""

from __future__ import annotations

import copy
import runpy
from dataclasses import replace
from pathlib import Path

import h5py
import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.errors import MaterialIntegrationError, ModelError, NonConvergence
from slipsurface.fe2d.fem.static import StaticSolver
from slipsurface.fe2d.fem.structural import InterfaceGroup
from slipsurface.fe2d.fem.unilateral_contact import StagedNormalContactGroup
from slipsurface.fe2d.io.project_json import model_from_dict, model_to_dict

_BENCH = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts"
                            / "f7_contact_static_benchmark.py"))
build_model, run_case, reference = (_BENCH[k] for k in ("build_model", "run_case", "reference"))


@pytest.mark.parametrize("element_type", ["IFACE4", "IFACE6"])
@pytest.mark.parametrize("initial_gap", [0.0, 0.002])
@pytest.mark.parametrize("mode", ["displacement", "force"])
def test_native_continuum_contact_matches_independent_equilibrium(element_type, initial_gap, mode):
    report = run_case(element_type=element_type, initial_gap=initial_gap, mode=mode)
    assert report["status"] == "passed", report
    assert report["stage_count"] == 7
    assert all(row["completed_load_factor"] == 1.0 for row in report["stages"])


@pytest.mark.parametrize("element_type", ["IFACE4", "IFACE6"])
def test_six_to_five_mm_reversal_stays_open_in_native_solver(element_type):
    model, _ = build_model(element_type=element_type)
    result = api.run(model)
    for i, gap in enumerate((0.006, 0.005)):
        np.testing.assert_allclose(result.stages[i].contact_gap["contact"], gap, atol=1e-13)
        np.testing.assert_allclose(result.stages[i].interfaces["contact"], 0.0, atol=1e-10)
        assert np.all(result.stages[i].contact_status["contact"] == 0)
        assert "contact" not in result.stages[i].struct_flags
    assert np.all(result.stages[4].contact_status["contact"] == 2)


@pytest.mark.parametrize("element_type", ["IFACE4", "IFACE6"])
def test_inactive_contact_never_welds_and_reactivation_retains_geometry(element_type):
    model, _ = build_model(element_type=element_type)
    model.initial = api.InitialStress("none", active_structures=set())
    model.stages = [
        api.Stage("off_open", displacements=(api.Displacement("top", uy=0.006),)),
        api.Stage("on_open", active_structures={"contact"},
                  displacements=(api.Displacement("top", uy=0.005),)),
        api.Stage("off_close", displacements=(api.Displacement("top", uy=-0.003),)),
        api.Stage("on_close", active_structures={"contact"},
                  displacements=(api.Displacement("top", uy=-0.003),)),
    ]
    solver = StaticSolver(model)
    result = solver.run()
    for i in (0, 2):
        assert np.isnan(result.stages[i].contact_gap["contact"]).all()
        assert np.all(result.stages[i].contact_status["contact"] == 255)
        assert np.isnan(result.stages[i].interfaces["contact"]).all()
    np.testing.assert_allclose(result.stages[0].u[model.mesh.nodes("bottom"), 1], 0.006)
    np.testing.assert_allclose(result.stages[1].contact_gap["contact"], 0.005, atol=1e-13)
    expected = reference(-0.003, 0.0, "displacement")
    np.testing.assert_allclose(result.last.contact_gap["contact"], expected["gap"], atol=1e-13)
    np.testing.assert_allclose(result.last.interfaces["contact"][..., 1], expected["pressure"])
    assert solver._ties(solver.state.active).size == 0


def test_reporting_reset_and_partial_load_do_not_reset_physical_gap():
    model, _ = build_model()
    model.stages = [
        api.Stage("half", active_structures={"contact"}, load_split=0.5,
                  displacements=(api.Displacement("top", uy=0.006),)),
        api.Stage("reset_report", active_structures={"contact"}, reset_displacements=True,
                  displacements=(api.Displacement("top", uy=0.005),)),
        api.Stage("close", active_structures={"contact"},
                  displacements=(api.Displacement("top", uy=-0.003),)),
    ]
    result = api.run(model)
    np.testing.assert_allclose(result.stages[0].contact_gap["contact"], 0.003, atol=1e-13)
    np.testing.assert_allclose(result.stages[1].u[model.mesh.nodes("bottom"), 1], 0.002)
    np.testing.assert_allclose(result.stages[1].contact_gap["contact"], 0.005, atol=1e-13)
    assert np.all(result.last.contact_status["contact"] == 2)


def test_discarded_native_trials_do_not_change_committed_contact_gap():
    model, _ = build_model()
    solver = StaticSolver(model)
    state, _ = solver.initial_state()
    lay = solver.layout({})
    ctx = solver.stage_context(model.stages[0], {})
    state, system, _, _ = solver.solve_stage_ctx(state, ctx, lay)
    before = copy.deepcopy(state)
    du = np.zeros(system.dm.ndof)
    group = next(g for g in solver.groups if isinstance(g, StagedNormalContactGroup))
    bottom = group.f2.ravel()
    du[system.dm.node_dofs[bottom, 1]] = -0.01
    one, f1 = solver.integrate(state, du, system, lay)
    two, f2 = solver.integrate(state, du, system, lay)
    np.testing.assert_array_equal(one.st["contact"]["gap"], two.st["contact"]["gap"])
    np.testing.assert_array_equal(f1, f2)
    np.testing.assert_array_equal(state.struct["contact"]["gap"], before.struct["contact"]["gap"])
    np.testing.assert_array_equal(state.u, before.u)
    assert np.all(one.st["contact"]["gap"] < 0)


def test_native_cutback_rollback_does_not_commit_failed_contact_trial(monkeypatch):
    model, _ = build_model()
    solver = StaticSolver(model)
    state, _ = solver.initial_state()
    before = state.commit()
    actual = StagedNormalContactGroup.integrate

    def reject_nonzero(self, state, ids, du_e, p=None):
        trial = actual(self, state, ids, du_e, p)
        if np.any(np.abs(du_e) > 0):
            raise MaterialIntegrationError("intentional rejected contact trial")
        return trial

    monkeypatch.setattr(StagedNormalContactGroup, "integrate", reject_nonzero)
    with pytest.raises(NonConvergence) as caught:
        solver.solve_stage_ctx(state, solver.stage_context(model.stages[0], {}), solver.layout({}))
    assert caught.value.lam == 0
    assert len(caught.value.history.steps) > 1
    np.testing.assert_array_equal(state.struct["contact"]["gap"], before.struct["contact"]["gap"])
    np.testing.assert_array_equal(state.u, before.u)


def test_open_floating_body_is_not_artificially_stabilized():
    model, _ = build_model(initial_gap=0.002, mode="force")
    model.fixities = tuple(fix for fix in model.fixities if fix.node_set != "top")
    model.stages = model.stages[:1]
    with pytest.raises(NonConvergence):
        api.run(model)


@pytest.mark.parametrize("fmt", ["json", "h5", "ssproj"])
def test_model_and_contact_result_roundtrip(tmp_path, fmt):
    model, _ = build_model(initial_gap=0.002)
    result = api.run(model)
    path = tmp_path / f"contact.{fmt}"
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
    assert restored_model.interfaces["contact"].law == "unilateral_normal"
    assert restored_model.interfaces["contact"].initial_gap == 0.002
    assert len(restored.stages) == len(result.stages)
    for a, b in zip(result.stages, restored.stages):
        np.testing.assert_allclose(a.contact_gap["contact"], b.contact_gap["contact"], atol=1e-13)
        np.testing.assert_array_equal(a.contact_status["contact"], b.contact_status["contact"])
        assert b.contact_status["contact"].dtype == np.uint8
        np.testing.assert_allclose(a.interfaces["contact"], b.interfaces["contact"], atol=1e-10)
        assert "contact" not in b.struct_flags


def test_legacy_project_defaults_to_goodman_and_keeps_history_response():
    model, _ = build_model()
    model.interfaces["contact"] = api.InterfaceSpec("contact", kn=2000.0, ks=0.0)
    model.stages = model.stages[:2]
    doc = model_to_dict(model)
    doc["interfaces"]["contact"].pop("law")
    doc["interfaces"]["contact"].pop("initial_gap")
    restored = model_from_dict(doc)
    assert restored.interfaces["contact"].law == "goodman"
    solver = StaticSolver(restored)
    assert any(isinstance(g, InterfaceGroup) for g in solver.groups)
    result = solver.run()
    assert result.last.contact_gap == {}
    assert result.last.contact_status == {}
    # Compatibility is not physical contact equivalence: the previous Goodman
    # law can still develop compression when reversing while absolutely open.
    assert np.min(result.last.interfaces["contact"][..., 1]) < -0.1


def test_older_result_snapshot_has_empty_optional_contact_fields(tmp_path):
    model, _ = build_model()
    model.interfaces["contact"] = api.InterfaceSpec("contact", kn=KN, ks=0.0)
    result = api.run(model)
    path = tmp_path / "legacy.h5"
    api.save_results(result, path)
    with h5py.File(path, "r+") as root:
        for group in [root["initial"], *root["stages"].values()]:
            del group["contact_gap"]
            del group["contact_status"]
    assert api.load_results(path).last.contact_gap == {}


KN = 2000.0


@pytest.mark.parametrize("bad", [
    {"ks": 1.0}, {"c": 1.0}, {"phi": 30.0}, {"psi": 1.0}, {"sig_t": 1.0},
    {"initial_gap": -0.001}, {"initial_gap": float("nan")}, {"initial_gap": True},
    {"law": "typo"}, {"kn": True},
])
def test_invalid_law_properties_fail_closed(bad):
    parameters = {"name": "contact", "kn": KN, "ks": 0.0, "law": "unilateral_normal"}
    parameters.update(bad)
    with pytest.raises(ModelError):
        api.InterfaceSpec(**parameters)


def test_goodman_cannot_silently_accept_geometric_clearance():
    with pytest.raises(ModelError, match="Goodman"):
        api.InterfaceSpec("legacy", KN, 0.0, initial_gap=0.002)


@pytest.mark.parametrize("bad", ["gravity", "k0_field", "field", "wet", "undrained", "axisym",
                                 "mNR", "initial", "hybrid", "seismic"])
def test_out_of_scope_native_contact_models_rejected(bad):
    model, _ = build_model()
    if bad in ("gravity", "k0_field", "field"):
        model.initial = api.InitialStress(bad)
    elif bad == "wet":
        model.stages[0] = replace(model.stages[0], water=api.WaterCondition(
            mode="piezo_line", piezo_polyline=np.array([[0.0, 1.0], [2.0, 1.0]])))
    elif bad == "undrained":
        model.materials["solid"] = model.materials["solid"].with_drainage(api.Drainage.UNDRAINED_A)
    elif bad == "axisym":
        model.analysis = api.Analysis.AXISYMMETRIC
    elif bad in ("initial", "mNR", "hybrid"):
        model.settings = replace(model.settings, method=bad)
    else:
        model.stages[0] = replace(model.stages[0], seismic_kh=0.1)
    with pytest.raises(ModelError, match="[Uu]nilateral"):
        api.run(model)


def test_goodman_group_rejects_normal_law_instead_of_using_wrong_mechanics():
    model, _ = build_model()
    with pytest.raises(ValueError, match="Goodman-only"):
        InterfaceGroup(model.mesh.block("contact"), model.mesh.coords,
                       model.interfaces["contact"], model.analysis)


def test_benchmark_detects_nonfinite_contact_results(monkeypatch):
    actual = api.run

    def bad(model):
        result = actual(model)
        result.stages[0].contact_gap["contact"][0, 0] = np.nan
        return result

    monkeypatch.setattr(api, "run", bad)
    report = run_case()
    assert report["status"] == "failed"
    assert report["stages"][0]["checks"]["gap_m"]["maximum_absolute_error"] is None


def test_strength_reduction_rejects_normal_contact_instead_of_reporting_a_false_fos():
    model, _ = build_model()
    with pytest.raises(ModelError, match="strength reduction"):
        api.strength_reduction(model)


def test_legacy_hdf5_and_project_apis_preserve_contact_fields(tmp_path):
    from slipsurface.fe2d.io.ssproj import load_project, save_project

    model, _ = build_model()
    result = api.run(model)
    path = tmp_path / "legacy-api.ssproj"
    save_project(path, model, result)
    restored = load_project(path).results
    np.testing.assert_array_equal(restored.last.contact_status["contact"],
                                  result.last.contact_status["contact"])
    np.testing.assert_allclose(restored.last.contact_gap["contact"],
                               result.last.contact_gap["contact"])


@pytest.mark.parametrize("error", ["traction", "reaction", "status"])
def test_benchmark_rejects_corrupted_finite_evidence(monkeypatch, error):
    actual = api.run

    def bad(model):
        result = actual(model)
        if error == "traction":
            result.stages[0].interfaces["contact"][0, 0, 1] = -2.0
        elif error == "reaction":
            result.last.reactions[model.mesh.nodes("top")[0], 1] += 1.0
        else:
            result.stages[0].contact_status["contact"][:] = 2
        return result

    monkeypatch.setattr(api, "run", bad)
    assert run_case()["status"] == "failed"

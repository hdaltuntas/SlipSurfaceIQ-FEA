"""General elastic topology audit, independent fixture cross-checks and falsification."""

from __future__ import annotations

import copy
import pickle
import runpy
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.mesh import rectangle
from slipsurface.fe2d.post.contact_support_equilibrium import contact_support_equilibrium_by_stage
from slipsurface.fe2d.post.contact_topology_equilibrium import contact_topology_equilibrium_by_stage

_ROOT = Path(__file__).resolve().parents[2]
_B = runpy.run_path(str(_ROOT / "scripts" / "f7_contact_topology_benchmark.py"))
_R = _B["_REBIRTH"]
_S = runpy.run_path(str(_ROOT / "scripts" / "f7_contact_support_benchmark.py"))


@pytest.fixture(scope="module")
def specimen():
    model, _ = _R["build_model"](element_type="IFACE6", initial_gap=0.002)
    return api.run(model)


@pytest.mark.parametrize("family", ["reactivation", "excavation"])
@pytest.mark.parametrize("etype", ["IFACE4", "IFACE6"])
@pytest.mark.parametrize("gap", [0.0, 0.002])
@pytest.mark.parametrize("turn", [False, True])
@pytest.mark.parametrize("mode", ["force", "displacement", "mixed"])
def test_against_retained_independent_scalar_references(family, etype, gap, turn, mode):
    report = _B["run_case"](
        family, element_type=etype, initial_gap=gap, quarter_turn=turn, mode=mode
    )
    assert report["status"] == "passed", report
    assert report["independent_fixture_status"] == "passed"
    assert report["classification_matches"]


@pytest.mark.parametrize("etype", ["IFACE4", "IFACE6"])
@pytest.mark.parametrize("gap", [0.0, 0.002])
def test_asymmetric_partial_contact_and_materials(etype, gap):
    model = _B["asymmetric_model"](element_type=etype, initial_gap=gap)
    result = api.run(model)
    report = contact_topology_equilibrium_by_stage(result)
    assert report["status"] == "passed", report
    # One contact element stays active, the other automatically disappears.
    assert report["stages"][1]["topology"]["active_elements"]["contact"] == 1
    assert report["stages"][3]["topology"]["active_elements"]["contact"] == 2
    assert len(set(model.region_material.values())) == 2


@pytest.mark.parametrize("etype", ["IFACE4", "IFACE6"])
@pytest.mark.parametrize("variant", ["support_only", "support_and_contact", "eccentric_support"])
def test_temporary_restraint_contract_is_retained(etype, variant):
    model, _ = _S["build_model"](element_type=etype, initial_gap=0.002, variant=variant)
    result = api.run(model)
    old = contact_support_equilibrium_by_stage(result)
    new = contact_topology_equilibrium_by_stage(result)
    assert new["status"] == old["status"] == "passed"
    assert [r["physical_equilibrium"]["status"] for r in new["stages"]] == [
        r["physical_equilibrium"]["status"] for r in old["stages"]
    ]
    for a, b in zip(new["stages"], old["stages"]):
        np.testing.assert_allclose(
            a["history"]["physical_nodal"], b["history"]["actual_physical_nodal"]
        )
        np.testing.assert_allclose(
            a["history"]["retained_release_nodal"],
            b["history"]["retained_release_nodal"],
            atol=1e-10,
        )


def triangle_model(etype):
    source = rectangle(2.0, 1.0, 2, 2, etype=etype)
    bottom = source.nodes("bottom")
    copies = {int(v): source.nn + i for i, v in enumerate(bottom)}
    faces = source.edges("bottom").copy()
    for row in faces:
        if source.coords[row[0], 0] > source.coords[row[1], 0]:
            row[:2] = row[:2][::-1]
    contact_type = api.ElemType.IFACE4 if etype.nodes_per_edge == 2 else api.ElemType.IFACE6
    block = api.ElementBlock(
        contact_type,
        np.array([[*[copies[int(v)] for v in row], *row] for row in faces]),
        np.zeros(len(faces), dtype=int),
        "contact",
    )
    base = np.arange(source.nn, source.nn + len(bottom))
    mesh = api.Mesh(
        np.vstack([source.coords, source.coords[bottom]]),
        (*source.blocks, block),
        {**source.node_sets, "base": base, "solid": np.arange(source.nn)},
        source.edge_sets,
    )
    return api.Model(
        mesh=mesh,
        analysis=api.Analysis.PLANE_STRAIN,
        materials={"soil": api.MaterialSpec.elastic("soil", 2000.0, 0.25)},
        region_material={1: "soil"},
        initial=api.InitialStress("none"),
        interfaces={"contact": api.InterfaceSpec.unilateral_normal("contact", 2000.0)},
        fixities=(api.Fixity("solid", True, False), api.Fixity("base", True, True)),
        stages=[
            api.Stage(
                str(i),
                active_structures={"contact"},
                displacements=(api.Displacement("top", uy=v),),
            )
            for i, v in enumerate((0.006, 0.005, -0.003, 0.004))
        ],
        settings=api.SolverSettings(
            tol_force=1e-10, tol_energy=1e-10, dlam0=1.0, dlam_max=1.0, linear_solver="splu"
        ),
    )


@pytest.mark.parametrize(
    "etype", [api.ElemType.T3, api.ElemType.T6, api.ElemType.Q4, api.ElemType.Q8]
)
def test_multiple_element_families_against_uniform_layer_solution(etype):
    model = triangle_model(etype)
    result = api.run(model)
    report = contact_topology_equilibrium_by_stage(result)
    assert report["status"] == "passed", report
    # C=2400 kPa, height=1 m, closed equilibrium u_bottom=C*v/(C+kn).
    np.testing.assert_allclose(
        result.stages[2].contact_gap["contact"], -0.003 * 2400 / 4400, atol=1e-10
    )


_CORRUPTION = (
    "u",
    "balanced_reactions",
    "stress",
    "stress_zz",
    "gap",
    "pressure",
    "status",
    "missing_gap",
    "missing_activity",
    "activity",
    "flags",
    "pore",
    "rotation",
    "name",
    "lam",
    "bool_lam",
    "nan_lam",
    "sig_shape",
    "u_shape",
    "reaction_shape",
    "nan_stress",
    "nan_reaction",
)


@pytest.mark.parametrize("mode", _CORRUPTION)
def test_corrupted_predecessor_blocks_later_claims(specimen, mode):
    result = copy.deepcopy(specimen)
    st = result.stages[1]
    used = np.flatnonzero(np.isfinite(st.u).all(axis=1))
    bulk = result.model.mesh.continuum_blocks()[0].tag
    if mode == "u":
        st.u[used[0], 0] += 0.001
    elif mode == "balanced_reactions":
        st.reactions[used[0], 1] += 1.0
        st.reactions[used[-1], 1] -= 1.0
    elif mode in ("stress", "stress_zz", "nan_stress"):
        st.sig[bulk][0, 0, 2 if mode == "stress_zz" else 0] += (
            np.nan if mode == "nan_stress" else 1.0
        )
    elif mode == "gap":
        st.contact_gap["contact"][0, 0] -= 0.001
    elif mode == "pressure":
        st.interfaces["contact"][0, 0, 1] -= 1.0
    elif mode == "status":
        st.contact_status["contact"][0, 0] = 99
    elif mode == "missing_gap":
        st.contact_gap.clear()
    elif mode == "missing_activity":
        st.active.pop("contact")
    elif mode == "activity":
        st.active["contact"][0] = False
    elif mode == "flags":
        st.plastic[bulk][0, 0] = 1
    elif mode == "pore":
        st.pore[bulk][0, 0] = 1.0
    elif mode == "rotation":
        st.reactions[used[0], 2] = 1.0
    elif mode == "name":
        st.name = "wrong"
    elif mode in ("lam", "bool_lam", "nan_lam"):
        st.lam = {"lam": 0.123, "bool_lam": True, "nan_lam": np.nan}[mode]
    elif mode == "sig_shape":
        st.sig[bulk] = st.sig[bulk][:-1]
    elif mode == "u_shape":
        st.u = st.u[:-1]
    elif mode == "reaction_shape":
        st.reactions = st.reactions[:-1]
    else:
        st.reactions[used[0], 1] = np.nan
    report = contact_topology_equilibrium_by_stage(result)
    assert report["status"] == "failed"
    assert report["stages"][0]["status"] == "passed"
    assert report["stages"][1]["status"] in ("failed", "invalid")
    assert all(r["status"] == "blocked" for r in report["stages"][2:])


@pytest.mark.parametrize(
    "field",
    [
        "stress",
        "lost_u",
        "lost_reaction",
        "inactive_gap",
        "inactive_status",
        "datum",
        "rebirth_stress",
        "rebirth_u",
    ],
)
def test_removed_and_reborn_evidence_is_not_silently_filled(specimen, field):
    result = copy.deepcopy(specimen)
    st = result.stages[5]
    lost = np.flatnonzero(np.isnan(st.u).all(axis=1))
    assert len(lost) > 0
    if field == "stress":
        tag = result.model.mesh.continuum_blocks()[0].tag
        e = np.flatnonzero(~st.active[tag])[0]
        st.sig[tag][e, 0, 1] = 1.0
    elif field == "lost_u":
        st.u[lost[0]] = 0.0
    elif field == "lost_reaction":
        st.reactions[lost[0], 1] = 1.0
    elif field == "inactive_gap":
        st.contact_gap["contact"][:] = 0.0
    elif field == "inactive_status":
        st.contact_status["contact"][:] = 0
    elif field == "datum":
        result.model.stages[5] = replace(result.model.stages[5], reset_displacements=False)
    elif field == "rebirth_stress":
        result.stages[7].sig["lower"][0, 0, 1] += 1.0
    else:
        result.stages[7].u[lost[0], 1] += 0.001
    assert contact_topology_equilibrium_by_stage(result)["status"] == "failed"


@pytest.mark.parametrize("field", ["stress", "reaction", "u", "gap", "lam"])
def test_initial_reference_is_required(specimen, field):
    result = copy.deepcopy(specimen)
    if field == "stress":
        result.initial.sig["lower"][0, 0, 0] = 1.0
    elif field == "reaction":
        result.initial.reactions[0, 1] = 1.0
    elif field == "u":
        result.initial.u[0, 1] = 0.001
    elif field == "gap":
        result.initial.contact_gap["contact"][0, 0] += 0.001
    else:
        result.initial.lam = 0.5
    report = contact_topology_equilibrium_by_stage(result)
    assert report["status"] == "failed" and report["initial_status"] == "invalid"
    assert all(r["status"] == "blocked" for r in report["stages"])


def test_exact_removed_load_and_rebirth_history(specimen):
    report = contact_topology_equilibrium_by_stage(specimen)
    first = report["stages"][2]
    assert first["history"]["dropped_previous_load_resultant"][1] == pytest.approx(-5.0)
    assert first["physical_equilibrium"]["external_resultant"][1] == pytest.approx(-13.0)
    reborn = report["stages"][8]
    assert reborn["physical_equilibrium"]["external_resultant"][1] == pytest.approx(2.0)
    assert reborn["topology"]["reactivated_nodes"]
    assert all(
        r["physical_equilibrium"]["status"] == "passed"
        for r in report["stages"]
        if r["accepted_fraction"] == 1.0
    )
    assert any(r["physical_equilibrium"]["status"] == "failed" for r in report["stages"])


def test_partition_rebuilt_after_middle_layer_removed(specimen):
    report = contact_topology_equilibrium_by_stage(specimen)
    assert len(report["stages"][0]["transition_equilibrium"]["partitions"]) == 2
    assert len(report["stages"][5]["transition_equilibrium"]["partitions"]) == 1
    assert len(report["stages"][8]["transition_equilibrium"]["partitions"]) == 2


def test_nonmutation_and_translated_moment_origin(specimen):
    before = pickle.dumps(specimen)
    a = contact_topology_equilibrium_by_stage(specimen)
    b = contact_topology_equilibrium_by_stage(specimen, origin=(3.0, -2.0))
    assert pickle.dumps(specimen) == before
    assert a["status"] == b["status"] == "passed"
    for ra, rb in zip(a["stages"], b["stages"]):
        x, y, m = ra["physical_equilibrium"]["external_resultant"]
        assert rb["physical_equilibrium"]["external_resultant"][2] == pytest.approx(
            m - 3 * y - 2 * x
        )


@pytest.mark.parametrize("fmt", ["h5", "ssproj"])
def test_saved_snapshots_audit_without_resolve(specimen, tmp_path, fmt):
    path = tmp_path / ("saved." + fmt)
    if fmt == "h5":
        api.save_results(specimen, path)
        restored = api.load_results(path)
    else:
        api.save_project(specimen.model, path, specimen)
        restored = api.load_project(path).results
    assert contact_topology_equilibrium_by_stage(restored) == (
        contact_topology_equilibrium_by_stage(specimen)
    )


@pytest.mark.parametrize("bad", ["nonlinear", "gravity", "wet", "method", "override"])
def test_unsupported_contracts_are_explicit(specimen, bad):
    result = copy.deepcopy(specimen)
    if bad == "nonlinear":
        key = next(iter(result.model.materials))
        result.model.materials[key] = api.MaterialSpec.mohr_coulomb(key, 2000.0, 0.25, 5.0, 30.0)
    elif bad == "gravity":
        result.model.initial = api.InitialStress("none", gravity=True)
    elif bad == "wet":
        result.model.stages[0] = replace(
            result.model.stages[0],
            water=api.WaterCondition(
                mode="piezo_line", piezo_polyline=np.array([[0.0, 1.0], [4.0, 1.0]])
            ),
        )
    elif bad == "method":
        result.model.settings = replace(result.model.settings, method="mNR")
    else:
        result.model.stages[1] = replace(result.model.stages[1], material_override={1: "other"})
    assert contact_topology_equilibrium_by_stage(result)["status"] == "failed"


@pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), float("inf"), True])
def test_bad_tolerances_raise(specimen, value):
    with pytest.raises(ValueError, match="Tolerances"):
        contact_topology_equilibrium_by_stage(specimen, rtol=value)


def test_old_audit_still_rejects_topology(specimen):
    assert contact_support_equilibrium_by_stage(specimen)["status"] == "failed"


def test_missing_or_extra_stage_cannot_pass(specimen):
    for delete in (True, False):
        result = copy.deepcopy(specimen)
        if delete:
            result.stages.pop()
        else:
            result.stages.append(copy.deepcopy(result.stages[-1]))
        assert contact_topology_equilibrium_by_stage(result)["status"] == "failed"


def test_reference_does_not_call_native_solver_or_fixture(monkeypatch, specimen):
    def forbidden(*args, **kwargs):
        raise AssertionError("Audit must not run the solver")

    from slipsurface.fe2d.fem.static import StaticSolver
    from slipsurface.fe2d.fem.unilateral_contact import StagedNormalContactGroup

    monkeypatch.setattr(api, "run", forbidden)
    monkeypatch.setattr(StaticSolver, "__init__", forbidden)
    monkeypatch.setattr(StagedNormalContactGroup, "__init__", forbidden)
    assert contact_topology_equilibrium_by_stage(specimen)["status"] == "passed"


def test_benchmark_cli_fails_on_failed_evidence(monkeypatch, tmp_path):
    import sys

    monkeypatch.setitem(
        _B["main"].__globals__, "run_benchmark", lambda: {"status": "failed", "cases": []}
    )
    target, example = tmp_path / "failed.json", tmp_path / "no.ssproj"
    monkeypatch.setattr(sys, "argv", ["bench", "--output", str(target), "--example", str(example)])
    assert _B["main"]() == 1
    assert target.exists() and not example.exists()


@pytest.mark.parametrize("fmt", ["h5", "ssproj"])
def test_saved_project_cli_runs_no_solver(specimen, monkeypatch, tmp_path, fmt):
    import json
    import sys

    source = tmp_path / ("saved." + fmt)
    output = tmp_path / "audit.json"
    if fmt == "h5":
        api.save_results(specimen, source)
    else:
        api.save_project(specimen.model, source, specimen)

    def forbidden(*args, **kwargs):
        raise AssertionError("Stored-result audit must not solve again")

    monkeypatch.setattr(api, "run", forbidden)
    monkeypatch.setattr(sys, "argv", ["audit", "--project", str(source), "--output", str(output)])
    assert _B["main"]() == 0
    assert json.loads(output.read_text())["stage_count"] == 14


def test_project_without_results_not_a_pass(specimen, tmp_path):
    source = tmp_path / "unsolved.ssproj"
    api.save_project(specimen.model, source)
    with pytest.raises(ValueError, match="snapshots"):
        _B["audit_saved_project"](source)


def test_unknown_project_format_rejected(tmp_path):
    with pytest.raises(ValueError, match="ssproj"):
        _B["audit_saved_project"](tmp_path / "input.json")


def test_bad_mesh_reports_invalid_instead_of_crashing(specimen):
    result = copy.deepcopy(specimen)
    result.model.mesh.blocks[0].conn[0, 0] = result.model.mesh.nn + 5
    report = contact_topology_equilibrium_by_stage(result)
    assert report["status"] == "failed" and report["initial_status"] == "invalid"


def test_inactive_contact_is_not_reported_as_measured_law_agreement(specimen):
    report = contact_topology_equilibrium_by_stage(specimen)
    for row in report["stages"]:
        if row["topology"]["active_elements"]["contact"] == 0:
            assert row["checks"]["original_reference_gap"]["status"] == "not_applicable"
            assert row["checks"]["geometric_contact_pressure"]["status"] == "not_applicable"


def test_missing_pore_map_is_not_a_valid_dry_snapshot(specimen):
    result = copy.deepcopy(specimen)
    result.stages[0].pore.clear()
    assert contact_topology_equilibrium_by_stage(result)["stages"][0]["status"] == "invalid"

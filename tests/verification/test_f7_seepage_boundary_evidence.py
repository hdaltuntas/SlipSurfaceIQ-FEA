"""Independent scalar flux and atmospheric-face tests, including stored evidence."""

from __future__ import annotations

import copy
import runpy
from dataclasses import replace
from pathlib import Path

import h5py
import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.fem.seepage import SeepageBlock, solve_seepage
from slipsurface.fe2d.io import ResultsFile, read_results, write_results
from slipsurface.fe2d.mesh import rectangle
from slipsurface.fe2d.post.coupled_seepage_budget import coupled_seepage_stage_budget


def model_with_water(etype, water):
    mesh = rectangle(4., 6., 4, 6, etype=etype, origin=(0., -6.))
    return api.Model(
        api.Analysis.PLANE_STRAIN, mesh,
        {"soil": api.MaterialSpec.elastic("soil", 25000., 0.3, gamma=17., gamma_sat=20.)},
        {1: "soil"}, fixities=(api.Fixity("bottom", True, True),
                               api.Fixity("left", True, False),
                               api.Fixity("right", True, False)),
        initial=api.InitialStress("gravity"), stages=[api.Stage("flow", water=water)],
    )


@pytest.mark.parametrize("etype", [ElemType.T3, ElemType.T6, ElemType.Q4, ElemType.Q8])
def test_prescribed_outflux_recovers_exact_linear_head_and_total_water_budget(etype):
    water = api.WaterCondition.seepage({"left": 3.}, fluxes={"right": -5e-8})
    model = model_with_water(etype, water)
    solved = api.run(model)
    row = coupled_seepage_stage_budget(model, solved, 0)
    assert row["status"] == "passed", row.get("reason")
    np.testing.assert_allclose(solved.last.head, 3 - 0.5*model.mesh.coords[:, 0], atol=1e-8)
    assert row["prescribed_flux_inflow_m2_per_s"] == pytest.approx(-3e-7, abs=1e-18)
    assert row["reported_net_inflow_m2_per_s"] == pytest.approx(3e-7, abs=1e-15)
    assert abs(row["flow_balance_residual_m2_per_s"]) < 1e-15
    edges = model.mesh.edges("right")
    order = [1, 0] if edges.shape[1] == 2 else [1, 0, 2]
    reverse = replace(model, mesh=replace(model.mesh, edge_sets={
        **model.mesh.edge_sets, "right": edges[:, order],
    }))
    backward = coupled_seepage_stage_budget(reverse, solved, 0)
    assert backward["prescribed_flux_inflow_m2_per_s"] == pytest.approx(-3e-7, abs=1e-18)


@pytest.fixture(scope="module")
def face_case():
    water = api.WaterCondition.seepage({"left": 1.}, fluxes={"top": 1e-8},
                                      seepage_faces=("right",))
    model = model_with_water(ElemType.T6, water)
    return model, api.run(model)


def test_face_allows_outflow_at_zero_pressure_and_balances_applied_flux(face_case):
    model, solved = face_case
    row = coupled_seepage_stage_budget(model, solved, 0)
    assert row["status"] == "passed", row.get("reason")
    face = row["seepage_face_checks"][0]
    assert face["active_nodes"] > 0
    assert face["released_nodes"] > 0
    assert face["max_active_pressure_head_error_m"] < 1e-8
    assert face["max_active_inflow_m2_per_s"] < 1e-15
    assert row["prescribed_flux_inflow_m2_per_s"] == pytest.approx(4e-8, abs=1e-18)
    assert solved.last.flow["right"] < 0


def test_face_cannot_pass_from_aggregate_flows_without_saved_node_evidence(face_case):
    model, solved = face_case
    missing = copy.deepcopy(solved)
    missing.last.seepage_nodal_flux = None
    missing.last.seepage_nodes = None
    with pytest.raises(ValueError, match="saved nodal flux"):
        coupled_seepage_stage_budget(model, missing, 0)


def test_forged_face_inflow_fails_even_with_conserved_aggregate_flow(face_case):
    model, solved = face_case
    changed = copy.deepcopy(solved)
    a, b = changed.last.seepage_nodes[:2]
    transfer = abs(changed.last.seepage_nodal_flux[a]) + 1e-6
    changed.last.seepage_nodal_flux[a] += transfer
    changed.last.seepage_nodal_flux[b] -= transfer
    row = coupled_seepage_stage_budget(model, changed, 0)
    assert row["status"] == "failed"
    assert row["relative_reported_flow_imbalance"] < 1e-6
    assert row["seepage_face_checks"][0]["max_active_inflow_m2_per_s"] > 1e-7


def test_released_face_cannot_carry_positive_pressure(face_case):
    model, solved = face_case
    changed = copy.deepcopy(solved)
    released = np.setdiff1d(model.mesh.nodes("right"), solved.last.seepage_nodes)
    assert len(released)
    node = released[0]
    changed.last.head[node] = model.mesh.coords[node, 1] + 0.5
    row = coupled_seepage_stage_budget(model, changed, 0)
    assert row["status"] == "failed"
    assert row["seepage_face_checks"][0]["max_released_positive_pressure_head_m"] >= 0.5


def test_face_node_data_roundtrip_in_modern_legacy_and_project_storage(tmp_path, face_case):
    model, solved = face_case
    modern = api.save_results(solved, tmp_path / "modern.h5")
    legacy = write_results(solved, tmp_path / "legacy.h5")
    project = api.save_project(tmp_path / "face.ssproj", model, solved)
    snapshots = [api.load_results(modern), read_results(legacy, model),
                 api.load_project(project).results]
    for snapshot in snapshots:
        np.testing.assert_array_equal(snapshot.last.seepage_nodal_flux,
                                      solved.last.seepage_nodal_flux)
        np.testing.assert_array_equal(snapshot.last.seepage_nodes, solved.last.seepage_nodes)
        assert snapshot.last.seepage_diagnostics == solved.last.seepage_diagnostics
        assert coupled_seepage_stage_budget(model, snapshot, 0)["status"] == "passed"
    with ResultsFile(legacy) as reader:
        np.testing.assert_array_equal(reader.stage("flow").seepage_nodes, solved.last.seepage_nodes)
    # Old files load without inventing atmospheric-node evidence.
    with h5py.File(modern, "a") as root:
        del root["stages/0/seepage_nodes"]
        del root["stages/0/seepage_nodal_flux"]
        del root["stages/0/seepage_diagnostics"]
    old = api.load_results(modern)
    assert old.last.seepage_nodes is None
    assert old.last.seepage_nodal_flux is None
    assert old.last.seepage_diagnostics == {}
    with pytest.raises(ValueError, match="saved nodal flux"):
        coupled_seepage_stage_budget(model, old, 0)


def test_adaptive_relaxation_solves_actual_infiltration_without_changing_material_inputs():
    pytest.importorskip("shapely")
    root = Path(__file__).resolve().parents[2]
    helper = runpy.run_path(str(root / "examples/f7_excavation_mesh_audit.py"))
    case = runpy.run_path(str(root / "scripts/f7_seepage_boundary_audit.py"))["boundary_case"]
    model = case(helper["build_case"](helper["excavation_model"](), 2.5))
    blocks = []
    for block in model.mesh.continuum_blocks():
        specs = [model.materials[model.region_material[int(r)]] for r in block.region]
        blocks.append(SeepageBlock(
            block.tag, block.conn, block.etype, np.array([s.k_sat for s in specs]),
            np.array([s.vg for s in specs]),
        ))
    args = (model.mesh, blocks, [("left", model.mesh.nodes("Soil:4"), 1.)],
            [(model.mesh.edges("Soil:3"), 1e-8)], [("right", model.mesh.nodes("Soil:2"))])
    fixed = solve_seepage(*args, adaptive_damping=False)
    adaptive = solve_seepage(*args)
    assert fixed.damping_history == [0.5] * fixed.iterations
    assert adaptive.converged
    assert adaptive.conductivity_residual < 1e-4
    assert len(adaptive.damping_history) == adaptive.iterations
    assert all(0.125 <= value <= 0.5 for value in adaptive.damping_history)
    if not fixed.converged:
        assert min(adaptive.damping_history) < 0.5

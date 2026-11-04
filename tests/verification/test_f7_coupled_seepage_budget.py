"""Seepage head transfer, analytical confined flow and mechanical force accounting."""

from __future__ import annotations

import copy
import runpy
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.core.units import GAMMA_W
from slipsurface.fe2d.fem.elements import kernel
from slipsurface.fe2d.mesh import rectangle
from slipsurface.fe2d.post.coupled_seepage_budget import (
    coupled_seepage_budget_by_stage,
    coupled_seepage_stage_budget,
)


def column(etype, *, left=3., right=1.):
    mesh = rectangle(4., 6., 4, 6, etype=etype, origin=(0., -6.))
    water = api.WaterCondition.seepage({"left": left, "right": right})
    return api.Model(
        api.Analysis.PLANE_STRAIN, mesh,
        {"soil": api.MaterialSpec.elastic("soil", 25000., 0.3, gamma=17., gamma_sat=20.)},
        {1: "soil"},
        fixities=(api.Fixity("bottom", True, True), api.Fixity("left", True, False),
                  api.Fixity("right", True, False)),
        initial=api.InitialStress("gravity"), stages=[api.Stage("seep", water=water)],
    )


@pytest.mark.parametrize("etype", [ElemType.T3, ElemType.T6, ElemType.Q4, ElemType.Q8])
def test_confined_linear_head_discharge_pressure_and_reaction_references(etype):
    model = column(etype)
    solved = api.run(model)
    row = coupled_seepage_stage_budget(model, solved, 0)
    assert row["status"] == "passed", row.get("reason")
    np.testing.assert_allclose(solved.last.head, 3. - 0.5 * model.mesh.coords[:, 0], atol=1e-8)
    q = model.materials["soil"].k_sat[0] * (3. - 1.) / 4. * 6.
    assert solved.last.flow["left"] == pytest.approx(q, rel=1e-7)
    assert solved.last.flow["right"] == pytest.approx(-q, rel=1e-7)
    assert row["reaction_resultant"][1] == pytest.approx(4*6*20 + 8*GAMMA_W, abs=1e-7)
    assert row["reaction_resultant"][2] == pytest.approx(4*6*20*2 + 40/3*GAMMA_W, abs=1e-7)
    assert row["max_nodal_force_residual"] < 1e-7
    assert row["max_pressure_reference_error_kpa"] < 1e-10


def test_gp_pressure_clips_after_head_interpolation_not_at_the_nodes():
    model = column(ElemType.Q4, left=-0.1, right=-1.9)
    solved = api.run(model)
    assert coupled_seepage_stage_budget(model, solved, 0)["status"] == "passed"
    block = model.mesh.continuum_blocks()[0]
    geom = kernel(block.etype).precompute(model.mesh.coords, block.conn, model.analysis)
    clipped_nodes = GAMMA_W * np.maximum(solved.last.head - model.mesh.coords[:, 1], 0.)
    wrong = np.einsum("gn,en->eg", geom.N, clipped_nodes[block.conn])
    assert np.max(np.abs(wrong - solved.last.pore[block.tag])) > 0.1
    changed = copy.deepcopy(solved)
    changed.last.pore[block.tag] = wrong
    row = coupled_seepage_stage_budget(model, changed, 0)
    assert row["status"] == "failed"
    assert row["max_pressure_reference_error_kpa"] > 0.1


@pytest.mark.parametrize("change", ["missing_head", "nan_head", "missing_flow", "flux_error"])
def test_invalid_saved_seepage_evidence_never_passes(change):
    model = column(ElemType.T6)
    solved = api.run(model)
    if change == "missing_head":
        solved.last.head = None
    elif change == "nan_head":
        solved.last.head[0] = np.nan
    elif change == "missing_flow":
        solved.last.flow.clear()
    else:
        solved.last.flow["left"] *= 2
    row = coupled_seepage_budget_by_stage(model, solved)[0]
    assert row["status"] == ("failed" if change == "flux_error" else "unsupported")


def test_zero_gradient_does_not_amplify_roundoff_into_failed_flux_conservation():
    model = column(ElemType.T6, left=3., right=3.)
    row = coupled_seepage_stage_budget(model, api.run(model), 0)
    assert row["status"] == "passed"
    assert abs(row["reported_net_inflow_m2_per_s"]) < 1e-14


@pytest.fixture(scope="module")
def excavation():
    pytest.importorskip("shapely")
    root = Path(__file__).resolve().parents[2]
    helper = runpy.run_path(str(root / "examples/f7_excavation_mesh_audit.py"))
    loaded = runpy.run_path(str(root / "scripts/f7_loaded_excavation_audit.py"))["loaded_case"]
    seepage = runpy.run_path(str(root / "scripts/f7_seepage_excavation_audit.py"))["seepage_case"]
    model = seepage(loaded(helper["build_case"](helper["excavation_model"](), 2.5)))
    return model, api.run(model)


def test_real_pile_anchor_seepage_preserves_hydraulic_node_identity(excavation):
    model, solved = excavation
    rows = coupled_seepage_budget_by_stage(model, solved)
    assert [row["status"] for row in rows] == ["passed"] * 3
    assert rows[0]["hydraulic_node_count"] < model.mesh.nn
    assert all(row["hydraulically_inactive_zero_pressure_nodes"] > 0 for row in rows)
    assert all(row["max_nodal_force_residual"] < 1e-7 for row in rows)
    changed = copy.deepcopy(solved)
    inactive = np.flatnonzero(np.isnan(changed.last.head))[0]
    changed.last.head[inactive] = 1.
    assert coupled_seepage_budget_by_stage(model, changed)[-1]["status"] == "unsupported"


@pytest.mark.parametrize("condition", ["high_quadrature", "partial"])
def test_unimplemented_seepage_contracts_remain_explicit(excavation, condition):
    model, solved = excavation
    if condition == "high_quadrature":
        changed = replace(model, settings=replace(model.settings, gauss_order="high"))
    else:
        step = model.stages[0]
        if condition == "partial":
            step = replace(step, load_split=0.4)
        changed = replace(model, stages=[step, *model.stages[1:]])
    assert coupled_seepage_budget_by_stage(changed, solved)[0]["status"] == "unsupported"

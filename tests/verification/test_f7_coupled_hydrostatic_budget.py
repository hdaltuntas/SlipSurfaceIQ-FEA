"""Actual wet-column and supported-excavation numerical equilibrium."""

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
from slipsurface.fe2d.fem.loads import pressure_edge_forces
from slipsurface.fe2d.mesh import rectangle
from slipsurface.fe2d.post.coupled_hydrostatic_budget import (
    coupled_hydrostatic_budget_by_stage,
    coupled_hydrostatic_stage_budget,
)
from slipsurface.fe2d.post.hydrostatic_nodal_forces import _edge_pressure


@pytest.mark.parametrize("etype", [ElemType.T3, ElemType.T6, ElemType.Q4, ElemType.Q8])
@pytest.mark.parametrize("head", [0., 3.])
def test_wet_column_reactions_match_bulk_weight_and_water_surcharge(etype, head):
    mesh = rectangle(2., 10., 2, 5, etype=etype, origin=(0., -10.))
    water = api.WaterCondition.piezo([[0., head]])
    model = api.Model(
        api.Analysis.PLANE_STRAIN, mesh,
        {"soil": api.MaterialSpec.elastic("soil", 25000., 0.3, gamma=17., gamma_sat=20.)},
        {1: "soil"},
        fixities=(api.Fixity("bottom", True, True), api.Fixity("left", True, False),
                  api.Fixity("right", True, False)),
        initial=api.InitialStress("gravity", water=water),
        stages=[api.Stage("wet", water=water)],
    )
    solved = api.run(model)
    row = coupled_hydrostatic_stage_budget(model, solved, 0)
    assert row["status"] == "passed", row.get("reason")
    expected_weight = 2 * 10 * 20
    surcharge = 2 * head * GAMMA_W
    assert row["reaction_resultant"][1] == pytest.approx(expected_weight + surcharge, abs=1e-7)
    assert row["water_resultant"][1] == pytest.approx(-surcharge, abs=1e-7)
    assert row["max_nodal_force_residual"] < 1e-7
    corrupted = copy.deepcopy(solved)
    corrupted.last.pore["soil"][0, 0] += 1.
    changed = coupled_hydrostatic_stage_budget(model, corrupted, 0)
    assert changed["status"] == "failed"
    assert changed["max_pressure_reference_error_kpa"] == pytest.approx(1.)


def test_water_table_cut_edge_reference_is_exact_not_unsplit_quadrature():
    values = _edge_pressure(np.array([[0., -2.], [0., 0.]]), -1.)
    np.testing.assert_allclose(values, GAMMA_W * np.array([5/12, 1/12]), atol=1e-12)


@pytest.mark.parametrize("quadratic", [False, True])
@pytest.mark.parametrize("analysis", [api.Analysis.PLANE_STRAIN, api.Analysis.AXISYMMETRIC])
def test_split_solver_edge_matches_analytical_nodal_forces_and_moment(quadratic, analysis):
    coords = np.array([[2., -2.], [2., 0.], [2., -1.]])
    edge = np.array([[0, 1, 2]]) if quadratic else np.array([[0, 1]])
    force = pressure_edge_forces(
        coords, edge, np.array([[1., -1.]]),
        lambda x: GAMMA_W * np.maximum(-1. - x[:, 1], 0.), analysis,
        horizontal_head=-1.,
    )[0]
    factors = np.array([7/24, -1/24, 1/4]) if quadratic else np.array([5/12, 1/12])
    radius = 2. if analysis is api.Analysis.AXISYMMETRIC else 1.
    np.testing.assert_allclose(force[:, 0], -radius * GAMMA_W * factors, atol=1e-12)
    np.testing.assert_allclose(force[:, 1], 0., atol=1e-12)
    moment = np.sum(-coords[edge[0], 1] * force[:, 0])
    assert moment == pytest.approx(-radius * GAMMA_W * 5/6, abs=1e-12)


def test_free_cut_boundary_uses_exactly_split_hydrostatic_pressure():
    mesh = rectangle(2., 2., 1, 1, etype=ElemType.Q4, origin=(0., -2.))
    water = api.WaterCondition.piezo([[0., -1.]])
    model = api.Model(
        api.Analysis.PLANE_STRAIN, mesh,
        {"soil": api.MaterialSpec.elastic("soil", 25000., 0.3, gamma=17., gamma_sat=20.)},
        {1: "soil"}, fixities=(api.Fixity("bottom", True, True),),
        initial=api.InitialStress("gravity", water=water),
        stages=[api.Stage("cut boundary", water=water)],
    )
    row = coupled_hydrostatic_stage_budget(model, api.run(model), 0)
    assert row["status"] == "passed"
    assert row["max_nodal_force_residual"] < 1e-8
    assert row["max_pressure_reference_error_kpa"] == 0.


@pytest.fixture(scope="module")
def wet_excavation():
    pytest.importorskip("shapely")
    helper = runpy.run_path(str(
        Path(__file__).resolve().parents[2] / "examples/f7_excavation_mesh_audit.py"
    ))
    base = helper["build_case"](helper["excavation_model"](), 2.5)
    water = api.WaterCondition.piezo([[0., 0.]])
    model = replace(base,
        materials={tag: replace(spec, gamma_sat=20.) for tag, spec in base.materials.items()},
        initial=replace(base.initial, water=water),
        stages=[replace(step, water=water) for step in base.stages],
    )
    return model, api.run(model)


def test_wet_pile_anchor_excavation_matches_terrace_water_reference(wet_excavation):
    model, solved = wet_excavation
    for index, row in enumerate(coupled_hydrostatic_budget_by_stage(model, solved)):
        assert row["status"] == "passed", row.get("reason")
        assert row["water_resultant"][1] == pytest.approx(-15 * 2 * index * GAMMA_W, abs=1e-7)
        assert row["water_resultant"][2] == pytest.approx(
            15 * 2 * index * GAMMA_W * 7.5, abs=1e-7,
        )
        assert row["max_nodal_force_residual"] < 1e-7
        assert any("joint_water" in node for node in row["structural_nodes"])


def test_nonhorizontal_head_and_partial_wet_stage_are_unsupported(wet_excavation):
    model, solved = wet_excavation
    sloping = replace(model, stages=[replace(model.stages[0], water=api.WaterCondition.piezo(
        [[-15., 0.], [15., -1.]],
    )), *model.stages[1:]])
    assert coupled_hydrostatic_budget_by_stage(sloping, solved)[0]["status"] == "unsupported"
    partial = replace(model, stages=[replace(model.stages[0], load_split=0.4)])
    assert coupled_hydrostatic_budget_by_stage(partial, solved)[0]["status"] == "unsupported"


def test_missing_water_evidence_is_not_a_zero_pressure_field(wet_excavation):
    model, solved = wet_excavation
    missing = copy.deepcopy(solved)
    missing.last.pore.clear()
    rows = coupled_hydrostatic_budget_by_stage(model, missing)
    assert rows[-1]["status"] == "unsupported"
    assert "pore-pressure blocks" in rows[-1]["reason"]

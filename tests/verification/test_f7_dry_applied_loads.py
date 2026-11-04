"""Analytical force/moment and consistent nodal loads on straight boundaries."""

from __future__ import annotations

import runpy
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.mesh import rectangle
from slipsurface.fe2d.post.coupled_dry_budget import coupled_dry_stage_budget
from slipsurface.fe2d.post.dry_applied_loads import independent_dry_applied_loads


def case(etype):
    mesh = rectangle(4., 6., 2, 3, etype=etype, origin=(0., -6.))
    node = int(mesh.nodes("top")[np.argmax(mesh.coords[mesh.nodes("top"), 0])])
    step = api.Stage("loaded", loads=(api.EdgeLoad("top", qn=20., qt=3.),
                                      api.PointLoad(node, fx=10., fy=-5.)))
    model = api.Model(
        api.Analysis.PLANE_STRAIN, mesh,
        {"soil": api.MaterialSpec.elastic("soil", 25000., 0.3, gamma=18.)}, {1: "soil"},
        fixities=(api.Fixity("bottom", True, True), api.Fixity("left", True, False),
                  api.Fixity("right", True, False)),
        initial=api.InitialStress("gravity"), stages=[step],
    )
    return model


@pytest.mark.parametrize("etype", [ElemType.T3, ElemType.T6, ElemType.Q4, ElemType.Q8])
def test_analytical_force_moment_and_real_loaded_solve(etype):
    model = case(etype)
    result = api.run(model)
    ref = independent_dry_applied_loads(model, model.stages[0], result.last.active)
    # Top pressure: Fy=-80, M=-160. Point at x=4: Fy=-5, M=-20.
    np.testing.assert_allclose(ref["resultant"], [-2., -85., -180.])
    np.testing.assert_allclose(ref["nodal"][:, :2].sum(axis=0), [-2., -85.])
    row = coupled_dry_stage_budget(model, result, 0)
    assert row["status"] == "passed"
    assert row["max_nodal_force_residual"] < 1e-7
    np.testing.assert_allclose(row["global_residual"], 0., atol=1e-7)
    # Reverse endpoints, preserving the quadratic midpoint index.
    edges = model.mesh.edges("top")
    order = [1, 0] if edges.shape[1] == 2 else [1, 0, 2]
    reverse = replace(model, mesh=replace(model.mesh, edge_sets={
        **model.mesh.edge_sets, "top": edges[:, order],
    }))
    backward = independent_dry_applied_loads(reverse, reverse.stages[0], result.last.active)
    np.testing.assert_allclose(backward["nodal"], ref["nodal"])
    np.testing.assert_allclose(backward["resultant"], ref["resultant"])


def test_quadratic_uniform_load_has_exact_end_and_midpoint_weights():
    model = case(ElemType.T6)
    edge = model.mesh.edges("top")[0]
    mesh = replace(model.mesh, edge_sets={**model.mesh.edge_sets, "one": edge[None, :]})
    step = api.Stage("one", loads=(api.EdgeLoad("one", qn=6.),))
    model = replace(model, mesh=mesh, stages=[step])
    active = {b.tag: np.ones(b.ne, dtype=bool) for b in mesh.blocks}
    ref = independent_dry_applied_loads(model, step, active)
    np.testing.assert_allclose(ref["nodal"][edge, 1], [-2., -2., -8.])
    coords = mesh.coords.copy()
    coords[edge[2], 1] += 0.1
    curved = replace(model, mesh=replace(mesh, coords=coords))
    with pytest.raises(ValueError, match="Curved"):
        independent_dry_applied_loads(curved, step, active)


def test_nonfinite_point_load_cannot_produce_passing_reference():
    model = case(ElemType.T3)
    step = replace(model.stages[0], loads=(api.PointLoad(0, fy=np.nan),))
    active = {b.tag: np.ones(b.ne, dtype=bool) for b in model.mesh.blocks}
    with pytest.raises(ValueError, match="Nonfinite"):
        independent_dry_applied_loads(model, step, active)


def test_full_stage_load_removal_uses_current_target_instead_of_cumulative_sum():
    model = case(ElemType.T6)
    model = replace(model, stages=[model.stages[0], api.Stage("unloaded")])
    solved = api.run(model)
    first = coupled_dry_stage_budget(model, solved, 0)
    last = coupled_dry_stage_budget(model, solved, 1)
    assert first["status"] == last["status"] == "passed"
    np.testing.assert_allclose(first["applied_load_resultant"], [-2., -85., -180.])
    np.testing.assert_allclose(last["applied_load_resultant"], 0.)


@pytest.mark.parametrize("surface", ["new_exposed_top", "left"])
def test_excavation_exposed_face_moment_and_inactive_edge_filtering(surface):
    helpers = runpy.run_path(str(Path(__file__).with_name(
        "test_f7_excavation_exposed_face_balance.py"
    )))
    model = helpers["make_layered_case"](ElemType.T6)
    step = replace(model.stages[1], loads=(api.EdgeLoad(surface, qn=20., qt=3.
                        if surface == "new_exposed_top" else 0.),))
    model = replace(model, stages=[model.stages[0], step])
    solved = api.run(model)
    ref = independent_dry_applied_loads(model, step, solved.last.active)
    expected = [-12., -80., -196.] if surface == "new_exposed_top" else [60., 0., 270.]
    np.testing.assert_allclose(ref["resultant"], expected)
    if surface == "left":
        assert ref["skipped_inactive_edges"] > 0
    else:
        with pytest.raises(ValueError, match="one active continuum owner"):
            independent_dry_applied_loads(model, step, solved.stages[0].active)
    row = coupled_dry_stage_budget(model, solved, 1)
    assert row["status"] == "passed"
    assert row["max_nodal_force_residual"] < 1e-7

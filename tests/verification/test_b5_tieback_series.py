from __future__ import annotations

import math

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.fem.structural import TiebackFreeGroup
from slipsurface.fe2d.mesh import rectangle
from slipsurface.fe2d.mesh.structures import add_tieback_series, tieback_component_tags


def _series_model(
    nx: int,
    *,
    free_length: float = 3.0,
    bond_length: float = 5.0,
    ea: float = 90_000.0,
    kb: float = 12_000.0,
    head_pull: float = 0.001,
):
    base = rectangle(bond_length, 1.0, nx, 1, api.ElemType.Q4)
    head = base.nn
    mesh = api.Mesh(
        np.vstack([base.coords, [-free_length, 0.0]]),
        base.blocks,
        {**base.node_sets, "head": np.array([head], dtype=np.int64)},
        base.edge_sets,
    )
    start = int(base.nodes("bottom")[np.argmin(base.coords[base.nodes("bottom"), 0])])
    mesh = add_tieback_series(mesh, head, "bottom", "tie", bond_start_node=start)
    free_tag, bond_tag = tieback_component_tags("tie")
    stages = [
        api.Stage(
            "pull",
            active_structures={free_tag, bond_tag},
            displacements=(api.Displacement("tie:head", ux=-head_pull, uy=0.0),),
        )
    ]
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"host": api.MaterialSpec.elastic("host", 10_000.0, 0.25)},
        region_material={1: "host"},
        fixities=(api.Fixity("bottom", True, True),),
        initial=api.InitialStress("none"),
        stages=stages,
        bolts={
            free_tag: api.BoltSpec(free_tag, EA=ea, T_yield=1e12),
            bond_tag: api.BoltSpec(bond_tag, EA=ea, T_yield=1e12),
        },
        bonds={bond_tag: api.BondSlipSpec(bond_tag, stiffness=kb, strength=1e9)},
    )
    return model, free_tag, bond_tag


def _series_exact(ea: float, kb: float, free_length: float, bond_length: float) -> float:
    ku = ea / free_length
    lam = math.sqrt(kb / ea)
    bonded = ea * lam * math.tanh(lam * bond_length)
    return ku * bonded / (ku + bonded)


def test_series_builder_joins_free_element_to_first_bond_scalar_node():
    model, free_tag, bond_tag = _series_model(4)
    free = model.mesh.block(free_tag)
    bond = model.mesh.block(bond_tag)
    assert free.etype is api.ElemType.TIE3
    assert bond.etype is api.ElemType.BOND4
    assert free.ne == 1 and bond.ne == 4
    assert free.conn[0, 1] == bond.conn[0, 0]
    assert free.conn[0, 2] == bond.conn[0, 2]
    assert model.mesh.nodes("tie:head").size == 1
    assert model.mesh.nodes("tie:bond_start").tolist() == [int(bond.conn[0, 0])]


def test_free_element_activation_preserves_requested_pretension():
    coords = np.array([[-2.0, 0.0], [0.0, 0.0], [0.0, 0.0]])
    block = api.ElementBlock(
        api.ElemType.TIE3, np.array([[0, 1, 2]]), np.array([0]), "free"
    )
    spec = api.BoltSpec(
        "free", EA=60_000.0, T_yield=100.0,
        pretension=50.0, spacing_out_of_plane=2.0,
    )
    group = TiebackFreeGroup(block, coords, spec, api.Analysis.PLANE_STRAIN)
    ids = np.array([0], dtype=np.int64)
    state = group.zero_state()
    group.activate(state, ids)
    assert state["N"][0] == pytest.approx(25.0)
    trial, force, _, flags = group.integrate(state, ids, np.zeros((1, 5)), None)
    assert trial["N"][0] == pytest.approx(25.0)
    np.testing.assert_allclose(force[0], [-25.0, 0.0, 25.0, 0.0, 25.0])
    assert flags[0, 0] == 0


@pytest.mark.parametrize("nx", [4, 8, 16, 32])
def test_unbonded_plus_bonded_series_converges_to_closed_form(nx):
    ea, kb, lu, lb, u0 = 90_000.0, 12_000.0, 3.0, 5.0, 0.001
    model, free_tag, bond_tag = _series_model(
        nx, free_length=lu, bond_length=lb, ea=ea, kb=kb, head_pull=u0
    )
    stage = api.run(model).last
    head = int(model.mesh.nodes("tie:head")[0])
    reaction = abs(float(stage.reactions[head, 0]))
    exact = _series_exact(ea, kb, lu, lb) * u0
    rel = abs(reaction - exact) / exact
    limits = {4: 0.02, 8: 0.006, 16: 0.002, 32: 0.0006}
    assert rel <= limits[nx]
    assert stage.bars[free_tag][0] == pytest.approx(reaction, rel=1e-9)
    assert stage.bars[bond_tag][0] == pytest.approx(reaction, rel=5e-3)


def test_series_model_and_results_roundtrip(tmp_path):
    model, free_tag, bond_tag = _series_model(8)
    model_path = tmp_path / "tieback-series.json"
    api.save_model(model, model_path)
    loaded = api.load_model(model_path)
    assert loaded.mesh.block(free_tag).etype is api.ElemType.TIE3
    assert loaded.mesh.block(bond_tag).etype is api.ElemType.BOND4

    result = api.run(model)
    results_path = tmp_path / "tieback-series.h5"
    api.save_results(result, results_path)
    reopened = api.load_results(results_path)
    np.testing.assert_allclose(reopened.last.bars[free_tag], result.last.bars[free_tag])
    np.testing.assert_allclose(reopened.last.bars[bond_tag], result.last.bars[bond_tag])
    np.testing.assert_allclose(reopened.last.bonds[bond_tag], result.last.bonds[bond_tag])

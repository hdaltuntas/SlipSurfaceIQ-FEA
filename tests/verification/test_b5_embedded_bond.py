from __future__ import annotations

import math

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.fem.assembly import DofMap
from slipsurface.fe2d.fem.structural import BondedBarGroup
from slipsurface.fe2d.mesh import rectangle
from slipsurface.fe2d.mesh.structures import add_embedded_bonded_bar


def _embedded_model(
    nx: int,
    *,
    length: float = 4.0,
    ea: float = 80_000.0,
    kb: float = 20_000.0,
    qmax: float = 1e9,
    head_slip: float = -0.002,
    fix_tip: bool = False,
):
    mesh = rectangle(length, 1.0, nx, 1, api.ElemType.Q4)
    mesh = add_embedded_bonded_bar(mesh, "bottom", "tie")
    displacements = [api.Displacement("tie:slip_start", ux=head_slip)]
    if fix_tip:
        displacements.append(api.Displacement("tie:slip_end", ux=0.0))
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"soil": api.MaterialSpec.elastic("soil", 10_000.0, 0.25)},
        region_material={1: "soil"},
        fixities=(api.Fixity("bottom", True, True),),
        initial=api.InitialStress("none"),
        stages=[
            api.Stage(
                "pull",
                active_structures={"tie"},
                displacements=tuple(displacements),
            )
        ],
        bolts={"tie": api.BoltSpec("tie", EA=ea, T_yield=1e12)},
        bonds={"tie": api.BondSlipSpec("tie", stiffness=kb, strength=qmax)},
    )
    return model


def test_embedded_builder_creates_scalar_chain_without_mutating_host_sets():
    base = rectangle(3.0, 1.0, 3, 1, api.ElemType.Q4)
    bottom_before = base.nodes("bottom").copy()
    mesh = add_embedded_bonded_bar(base, "bottom", "tie")
    block = mesh.block("tie")
    assert block.etype is api.ElemType.BOND4
    assert block.ne == 3
    assert mesh.nodes("tie:slip").size == 4
    assert np.array_equal(mesh.nodes("bottom"), bottom_before)
    np.testing.assert_allclose(mesh.coords[block.conn[:, :2]], mesh.coords[block.conn[:, 2:]])
    assert np.unique(block.conn[:, 2:]).size == 4


def test_scalar_dofs_do_not_change_legacy_numbering_and_have_no_y_dof():
    base = rectangle(2.0, 1.0, 2, 1, api.ElemType.Q4)
    active_base = {b.tag: np.ones(b.ne, dtype=bool) for b in base.blocks}
    legacy = DofMap(base, active_base)
    expected = legacy.node_dofs.copy()
    assert np.array_equal(DofMap(base, active_base).node_dofs, expected)

    mesh = add_embedded_bonded_bar(base, "bottom", "tie")
    active = {b.tag: np.ones(b.ne, dtype=bool) for b in mesh.blocks}
    scalar = mesh.nodes("tie:slip")
    dm = DofMap(mesh, active, scalar_nodes=scalar)
    assert np.all(dm.node_dofs[scalar, 0] >= 0)
    assert np.all(dm.node_dofs[scalar, 1:] == -1)


def test_one_segment_elastic_reaction_and_reported_bond_fields_are_exact():
    length, ea, kb, delta = 2.0, 60_000.0, 9_000.0, 0.001
    model = _embedded_model(
        1, length=length, ea=ea, kb=kb, head_slip=-delta, fix_tip=True
    )
    result = api.run(model)
    stage = result.last
    start = int(model.mesh.nodes("tie:slip_start")[0])
    ka = ea / length
    expected_reaction = -(ka + kb * length / 3.0) * delta
    assert stage.reactions[start, 0] == pytest.approx(expected_reaction, rel=1e-10, abs=1e-10)
    assert stage.bars["tie"][0] == pytest.approx(ka * delta, rel=1e-10)

    xi = np.array([-1.0 / math.sqrt(3.0), 1.0 / math.sqrt(3.0)])
    expected_slip = -delta * (1.0 - xi) * 0.5
    np.testing.assert_allclose(stage.bonds["tie"][0, :, 0], expected_slip, rtol=0, atol=1e-13)
    np.testing.assert_allclose(stage.bonds["tie"][0, :, 1], kb * expected_slip, rtol=0, atol=1e-9)
    assert np.isnan(stage.u[model.mesh.nodes("tie:slip")]).all()


def test_bonded_group_caps_local_shear_without_bar_extension():
    model = _embedded_model(1, length=2.0, ea=60_000.0, kb=1_000.0, qmax=10.0)
    block = model.mesh.block("tie")
    group = BondedBarGroup(
        block, model.mesh.coords, model.bolts["tie"], model.bonds["tie"], model.analysis
    )
    ids = np.array([0], dtype=np.int64)
    state = group.zero_state()
    group.activate(state, ids)
    du = np.zeros((1, 6))
    du[0, 4:] = -0.02
    trial, _, _, flags = group.integrate(state, ids, du, None)
    np.testing.assert_allclose(trial["N"], 0.0, atol=1e-12)
    np.testing.assert_allclose(trial["q"], -10.0, atol=1e-12)
    assert flags.shape == (1, 3)
    assert flags[0, 0] == 0 and np.all(flags[0, 1:] == 1)


@pytest.mark.parametrize("nx", [4, 8, 16, 32])
def test_elastic_shear_lag_converges_to_closed_form(nx):
    length, ea, kb, u0 = 6.0, 90_000.0, 12_000.0, 0.001
    model = _embedded_model(nx, length=length, ea=ea, kb=kb, head_slip=-u0)
    result = api.run(model)
    start = int(model.mesh.nodes("tie:slip_start")[0])
    reaction = abs(float(result.last.reactions[start, 0]))
    lam = math.sqrt(kb / ea)
    exact = ea * lam * math.tanh(lam * length) * u0
    rel = abs(reaction - exact) / exact
    limits = {4: 0.02, 8: 0.006, 16: 0.002, 32: 0.0006}
    assert rel <= limits[nx]


def test_model_and_results_roundtrip_preserve_bond_definition_and_fields(tmp_path):
    model = _embedded_model(4)
    model_path = tmp_path / "bond.json"
    api.save_model(model, model_path)
    loaded = api.load_model(model_path)
    assert loaded.bonds == model.bonds
    assert loaded.mesh.block("tie").etype is api.ElemType.BOND4

    result = api.run(model)
    results_path = tmp_path / "bond.h5"
    api.save_results(result, results_path)
    reopened = api.load_results(results_path)
    np.testing.assert_allclose(reopened.last.bonds["tie"], result.last.bonds["tie"])
    np.testing.assert_allclose(reopened.last.bars["tie"], result.last.bars["tie"])

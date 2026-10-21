"""Differentiate the assembled internal force at a nonzero, branch-stable trial.

Mixed continua, beam and two-sided joints share the global assembly. This is a
Jacobian test, not an equilibrium benchmark; a centered difference at a yield
switch/at zero increment would not define the same classical derivative.
"""

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.fem.static import StaticSolver
from slipsurface.fe2d.mesh import recombine_mesh, rectangle
from slipsurface.fe2d.mesh.structures import add_beams, insert_interface


def _solver(etype, order):
    source = rectangle(2.0, 1.0, 4, 2, etype)
    ids = np.flatnonzero(abs(source.coords[:, 0] - 1.0) < 1e-12)
    ids = ids[np.argsort(source.coords[ids, 1])]
    source.edge_sets["wall"] = (
        np.column_stack([ids[:-1], ids[1:]])
        if etype is api.ElemType.T3
        else np.column_stack([ids[:-2:2], ids[2::2], ids[1::2]])
    )
    mesh = recombine_mesh(source, where=lambda x: x[:, 0] < 1.5)
    mesh = add_beams(mesh, "wall", "liner")
    mesh = insert_interface(mesh, "wall", "left_joint", "left")
    mesh = insert_interface(mesh, "wall", "right_joint", "right")
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"m": api.MaterialSpec.mohr_coulomb("m", 2e4, 0.3, 10.0, 30.0, 5.0, sig_t=0.0)},
        region_material={1: "m"},
        fixities=(api.Fixity("bottom", True, True), api.Fixity("left", True, False)),
        initial=api.InitialStress("none", active_structures={"liner", "left_joint", "right_joint"}),
        liners={"liner": api.LinerSpec("liner", 3e4, 0.2, 0.1, 0.001, 0.08)},
        interfaces={
            k: api.InterfaceSpec(k, 5e4, 5e4, c=5.0, phi=25.0, psi=5.0, sig_t=1.0)
            for k in ("left_joint", "right_joint")
        },
        settings=api.SolverSettings(gauss_order=order),
    )
    return StaticSolver(model)


@pytest.mark.parametrize("etype", [api.ElemType.T3, api.ElemType.T6])
@pytest.mark.parametrize("order", ["default", "high"])
@pytest.mark.parametrize("joint_mode", ["slip", "opening"])
def test_global_tangent_is_derivative_of_the_actual_return_mapping(etype, order, joint_mode):
    solver = _solver(etype, order)
    state, _ = solver.initial_state()
    sysm, lay = solver.system, solver._layout
    dm = sysm.dm
    for values in state.sig.values():
        values[:] = [-100.0, -110.0, -120.0, 5.0]
    for tag in solver.model.interfaces:
        state.struct[tag]["t"][:] = [5.0, -100.0]
    before = state.commit()
    u = np.zeros_like(state.u)
    u[:, 0] = 0.012 * solver.mesh.coords[:, 1]
    u[:, 1] = -0.003 * solver.mesh.coords[:, 1]
    for g in solver.groups:
        if g.tag not in solver.model.interfaces:
            continue
        local = np.array(
            [0.01, 0.005 if joint_mode == "opening" and g.tag == "right_joint" else -0.001]
        )
        jump = g.R[0, 0] @ local
        u[np.unique(g.f2), :2] += jump
    du = np.zeros(dm.ndof)
    present = dm.node_dofs >= 0
    du[dm.node_dofs[present]] = u[present]
    rng = np.random.default_rng(5831)
    du[dm.free] += rng.normal(size=dm.free.size) * 1e-5  # avoid exact branch boundaries
    du[dm.prescribed] = 0.0
    trial, _ = solver.integrate(state, du, sysm, lay)
    assert any(np.any(flags > 0) for flags in trial.flag.values())
    assert any(np.any(flags > 0) for flags in trial.sflag.values())
    assert any(np.any(flags == 1) for flags in trial.sflag.values())
    if joint_mode == "opening":
        assert any(np.any((flags & 2) != 0) for flags in trial.sflag.values())
    K = solver._stiffness(sysm, trial.D, trial.K)[dm.free][:, dm.free]
    assert np.linalg.norm((K - K.T).data) > 1e-6  # preserve non-associated nonsymmetry
    for _ in range(3):
        v = np.zeros(dm.ndof)
        v[dm.free] = rng.normal(size=dm.free.size)
        v /= np.linalg.norm(v)
        predicted = K @ v[dm.free]
        for h in (3e-7, 1e-7):
            plus, fp = solver.integrate(state, du + h * v, sysm, lay)
            minus, fm = solver.integrate(state, du - h * v, sysm, lay)
            for name in trial.flag:
                np.testing.assert_array_equal(plus.flag[name], trial.flag[name])
                np.testing.assert_array_equal(minus.flag[name], trial.flag[name])
            for name in trial.sflag:
                np.testing.assert_array_equal(plus.sflag[name], trial.sflag[name])
                np.testing.assert_array_equal(minus.sflag[name], trial.sflag[name])
            actual = (fp - fm)[dm.free] / (2 * h)
            relative = np.linalg.norm(actual - predicted) / np.linalg.norm(predicted)
            assert relative < 2e-6, relative
    for tag in state.sig:
        np.testing.assert_array_equal(state.sig[tag], before.sig[tag])
        np.testing.assert_array_equal(state.q[tag], before.q[tag])
    for tag in state.struct:
        for name in state.struct[tag]:
            np.testing.assert_array_equal(state.struct[tag][name], before.struct[tag][name])

"""Goodman joint active-set return, tangent, face geometry and water-force checks."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.optimize import minimize

from slipsurface.fe2d import api
from slipsurface.fe2d.fem.structural import InterfaceGroup, interface_return
from slipsurface.fe2d.mesh import rectangle
from slipsurface.fe2d.mesh.structures import add_beams, insert_interface


@pytest.mark.parametrize("trial", [[1, -2], [8, -4], [-8, -4], [0.1, 2], [10, 2], [10, 8]])
def test_return_tangent_and_admissibility(trial):
    ks, kn, c, tf, tp, st = 100.0, 200.0, 2.0, math.tan(math.pi / 6), math.tan(math.pi / 18), 1.0
    tr = np.array([trial], dtype=float)
    t, D, _ = interface_return(tr, ks, kn, c, tf, tp, st)
    assert abs(t[0, 0]) + tf * t[0, 1] <= c + 1e-10
    assert t[0, 1] <= st + 1e-10
    for j in range(2):
        d = np.zeros((1, 2))
        d[0, j] = 1e-6
        plus = interface_return(tr + d, ks, kn, c, tf, tp, st)[0]
        minus = interface_return(tr - d, ks, kn, c, tf, tp, st)[0]
        # input is trial traction: convert its derivative to the jump tangent
        fd = (plus - minus)[0] / 2e-6 * [ks, kn][j]
        np.testing.assert_allclose(fd, D[0, :, j], atol=2e-6, rtol=1e-6)


def test_dilatant_trial_in_tension_can_return_to_compressive_shear():
    t, _, flag = interface_return(
        np.array([[10.0, 2.0]]), 100, 200, 2, math.tan(math.pi / 6), math.tan(math.pi / 18), 1
    )
    assert t[0, 1] < 0
    assert flag[0] == api.PlasticFlag.SHEAR


def test_associated_return_is_closest_admissible_traction():
    rng = np.random.default_rng(827)
    trials = rng.normal(size=(150, 2)) * 10
    tf = math.tan(math.pi / 6)
    A, b = np.array([[1, tf], [-1, tf], [0, 1]]), np.array([2, 2, 1])
    t, _, _ = interface_return(trials, 100, 200, 2, tf, tf, 1)
    W = np.diag([1, 0.5])
    for tr, out in zip(trials, t):

        def fun(x, tr=tr):
            d = x - tr
            return d @ W @ d

        r = minimize(
            fun,
            np.zeros(2),
            jac=lambda x, tr=tr: 2 * W @ (x - tr),
            method="SLSQP",
            constraints={"type": "ineq", "fun": lambda x: b - A @ x, "jac": lambda x: -A},
            options={"ftol": 1e-10, "maxiter": 200},
        )
        assert r.success, r.message
        assert np.max(A @ r.x - b) < 1e-8
        np.testing.assert_allclose(out, r.x, atol=1e-5)


@pytest.mark.parametrize("ks", [0.0, 100.0])
@pytest.mark.parametrize("phi", [0.0, 30.0])
def test_gap_closes_and_resists_compression(ks, phi):
    tf = math.tan(math.radians(phi))
    opened, _, _ = interface_return(np.array([[0.0, 10.0]]), ks, 200, 0, tf, 0, 0)
    np.testing.assert_allclose(opened, 0, atol=1e-12)
    closed, D, _ = interface_return(opened + [[0.0, -5.0]], ks, 200, 0, tf, 0, 0)
    assert closed[0, 1] == -5
    assert D[0, 1, 1] == 200


def _split(etype):
    mesh = rectangle(2, 2, 2, 2, etype=etype)
    # Vertical edge chain x=1, upward; quadratic mids are in the third column.
    ids = np.flatnonzero(abs(mesh.coords[:, 0] - 1) < 1e-10)
    ids = ids[np.argsort(mesh.coords[ids, 1])]
    if etype in (api.ElemType.T6, api.ElemType.Q8):
        edges = np.column_stack([ids[:-2:2], ids[2::2], ids[1::2]])
    else:
        edges = np.column_stack([ids[:-1], ids[1:]])
    mesh.edge_sets["wall"] = edges
    return mesh


@pytest.mark.parametrize(
    "etype", [api.ElemType.T3, api.ElemType.T6, api.ElemType.Q4, api.ElemType.Q8]
)
def test_two_sided_interface_keeps_wall_distinct_from_both_soil_faces(etype):
    mesh = add_beams(_split(etype), "wall", "beam")
    original = mesh.block("beam").conn.copy()
    one = insert_interface(mesh, "wall", "left", "left")
    two = insert_interface(one, "wall", "right", "right")
    np.testing.assert_array_equal(two.block("beam").conn, original)
    # The beam nodes must be absent from both adjacent continuum sides.
    wall = np.unique(original)
    assert not np.isin(two.blocks[0].conn, wall).any()
    left = np.unique(two.edges("left:face2"))
    right = np.unique(two.edges("right:face2"))
    assert np.intersect1d(left, right).size == 0
    np.testing.assert_allclose(np.sort(two.coords[left, 1]), np.sort(two.coords[right, 1]))


@pytest.mark.parametrize("etype", [api.ElemType.IFACE4, api.ElemType.IFACE6])
def test_element_rigid_motion_force_balance_and_tangent(etype):
    npe = 2 if etype is api.ElemType.IFACE4 else 3
    face = np.array([[0.0, 0.0], [2.0, 1.0], [1.0, 0.5]])[:npe]
    coords = np.vstack([face, face])
    block = api.ElementBlock(etype, np.arange(2 * npe)[None], np.array([0]), "joint")
    group = InterfaceGroup(
        block,
        coords,
        api.InterfaceSpec("joint", 200, 100, c=2, phi=30, psi=10),
        api.Analysis.PLANE_STRAIN,
    )
    ids = np.array([0])
    state = group.zero_state()
    rigid = np.tile([0.3, -0.5], 2 * npe)[None]
    _, f, _, _ = group.integrate(state, ids, rigid, None)
    np.testing.assert_allclose(f, 0, atol=1e-12)
    # Local jump that activates shear under compression.
    jump = np.zeros((1, 4 * npe))
    jump[0, 2 * npe :] = np.tile([0.08, -0.03], npe)
    _, f, K, _ = group.integrate(state, ids, jump, None)
    np.testing.assert_allclose(f.reshape(2 * npe, 2).sum(axis=0), 0, atol=1e-12)
    for j in range(4 * npe):
        du = np.zeros_like(jump)
        du[0, j] = 1e-7
        fp = group.integrate(state, ids, jump + du, None)[1]
        fm = group.integrate(state, ids, jump - du, None)[1]
        np.testing.assert_allclose((fp - fm)[0] / 2e-7, K[0, :, j], atol=2e-5)
    force = group.pore_force(ids, np.full((1, npe), 10))
    np.testing.assert_allclose(force.reshape(2 * npe, 2).sum(axis=0), 0, atol=1e-12)
    np.testing.assert_array_equal(state["t"], 0)  # trial evaluation never commits


def test_shear_return_without_tension_cap():
    t, D, _ = interface_return(np.array([[10.0, -3.0]]), 100, 200, 2, 0, 0, np.inf)
    np.testing.assert_allclose(t, [[2, -3]])
    np.testing.assert_allclose(D[0], [[0, 0], [0, 200]])


def test_open_interior_tips_remain_shared():
    mesh = rectangle(2, 2, 4, 4, etype=api.ElemType.T6)
    line = np.flatnonzero(
        (abs(mesh.coords[:, 0] - 1) < 1e-10)
        & (mesh.coords[:, 1] >= 0.5)
        & (mesh.coords[:, 1] <= 1.5)
    )
    line = line[np.argsort(mesh.coords[line, 1])]
    edges = np.column_stack([line[:-2:2], line[2::2], line[1::2]])
    mesh.edge_sets["joint"] = edges
    out = insert_interface(mesh, "joint", "joint")
    np.testing.assert_array_equal(out.coords[: mesh.nn], mesh.coords)
    assert out.nn == mesh.nn + len(line) - 2
    face1, face2 = out.edges("joint:face1"), out.edges("joint:face2")
    assert face1[0, 0] == face2[0, 0]
    assert face1[-1, 1] == face2[-1, 1]
    assert np.all(face1[:, 2] != face2[:, 2])


@pytest.mark.parametrize(
    "phi,psi,c,st", [(30, 0, 0, 0), (30, 10, 2, 1), (30, 30, 2, 10), (0, 0, 2, 0)]
)
def test_random_returns_are_admissible(phi, psi, c, st):
    rng = np.random.default_rng(738)
    tf, tp = np.tan(np.radians([phi, psi]))
    tr = rng.normal(size=(1000, 2)) * 100
    t, _, _ = interface_return(tr, 100, 200, c, tf, tp, st)
    assert np.max(np.abs(t[:, 0]) + tf * t[:, 1] - c) < 1e-8
    assert np.max(t[:, 1] - st) < 1e-8

"""Regression tests for the Faz 3 staging fixes (Oct 2026 review).

* an inactive interface means full continuity (its duplicated nodes are tied);
* a newly activated interface takes over the soil traction (no stress release);
* reactions of a load-split stage balance lam f_ext + (1 - lam) f0;
* SRF reduces interface strength (block sliding on an inclined joint).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.fem.srf import strength_reduction
from slipsurface.fe2d.mesh import Domain, unstructured_mesh
from slipsurface.fe2d.mesh.structures import insert_interface

SOIL = api.MaterialSpec.elastic("s", 2e4, 0.3, gamma=18.0)


def _layered(with_joint: bool):
    d = Domain()
    d.add_polygon([(0, -6), (8, -6), (8, -3), (0, -3)], 1,
                  edge_names=["bottom", None, "joint", None])  # fmt: skip
    d.add_polygon([(0, -3), (8, -3), (8, 0), (0, 0)], 2, edge_names=[None, None, "top", None])
    d.add_line([(4, 0), (4, -5)], name="wall")
    mesh = unstructured_mesh(d, h=0.5)
    if with_joint:
        mesh = insert_interface(mesh, "joint", "j", side="left")
        mesh = insert_interface(mesh, "wall", "w", side="right")
    return mesh


def _model(mesh, stages, initial_structures=None, joints=True):
    ifs = (
        {
            "j": api.InterfaceSpec("j", kn=1e6, ks=1e5, c=5.0, phi=25.0),
            "w": api.InterfaceSpec("w", kn=1e6, ks=1e5, c=5.0, phi=25.0),
        }
        if joints
        else {}
    )
    return api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"s": SOIL},
        region_material={1: "s", 2: "s"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        initial=api.InitialStress("gravity", active_structures=initial_structures),
        stages=stages,
        interfaces=ifs,
    )


def _side_fix(mesh):
    x = mesh.coords[:, 0]
    ns = dict(mesh.node_sets)
    ns["right"] = np.flatnonzero(np.isclose(x, 8.0))
    ns["left"] = np.flatnonzero(np.isclose(x, 0.0))
    return api.Mesh(mesh.coords, mesh.blocks, ns, mesh.edge_sets)


def test_inactive_interfaces_mean_full_continuity():
    plain = _side_fix(_layered(False))
    joint = _side_fix(_layered(True))
    load = (api.EdgeLoad("top", qn=50.0),)
    fix = (
        api.Fixity("bottom", True, True),
        api.Fixity("left", True, False),
        api.Fixity("right", True, False),
    )

    def run(mesh, ifs):
        m = _model(mesh, [api.Stage("q", loads=load)], initial_structures=frozenset(), joints=ifs)
        m.fixities = fix
        return api.run(m)

    r0 = run(plain, False)
    r1 = run(joint, True)
    n0 = plain.nn
    u0, u1 = r0.last.u, r1.last.u[:n0]  # original nodes keep their numbers
    assert np.abs(u0 - u1).max() < 1e-9 * np.abs(u0).max()
    # copies move with their originals (tied)
    for tag in ("j", "w"):
        blk = joint.block(tag)
        npe = blk.conn.shape[1] // 2
        a, b = blk.conn[:, :npe].ravel(), blk.conn[:, npe:].ravel()
        assert np.allclose(r1.last.u[a], r1.last.u[b])
    # reactions are not counted twice on tied nodes
    W = SOIL.gamma_unsat * 8.0 * 6.0
    for r in (r0, r1):
        assert r.last.reactions[:, 1].sum() == pytest.approx(W + 50.0 * 8.0, rel=1e-9)


def test_activating_an_interface_does_not_release_stress():
    mesh = _side_fix(_layered(True))
    m = _model(mesh, [api.Stage("joints_on", active_structures={"j", "w"})],
               initial_structures=frozenset())  # fmt: skip
    m.fixities = (
        api.Fixity("bottom", True, True),
        api.Fixity("left", True, False),
        api.Fixity("right", True, False),
    )
    res = api.run(m)
    # elastic settlement scale of the gravity stage vs. the movement caused by switching on
    gravity_scale = SOIL.gamma_unsat * 6.0**2 / (2 * 2e4)
    du = np.nanmax(np.abs(res.last.u))
    assert du < 0.02 * gravity_scale
    t = res.last.interfaces["j"]
    assert np.all(t[..., 1] < 0)  # joint in compression from the start


def test_load_split_reactions_balance():
    d = Domain().add_polygon([(0, -4), (4, -4), (4, 0), (0, 0)],
                             edge_names=["bottom", "right", "top", "left"])  # fmt: skip
    mesh = unstructured_mesh(d, h=0.5)
    alpha, q = 0.4, 100.0
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"s": SOIL},
        region_material={1: "s"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        stages=[
            api.Stage("split", loads=(api.EdgeLoad("top", qn=q),), load_split=alpha),
            api.Stage("rest", loads=(api.EdgeLoad("top", qn=q),)),
        ],
    )
    res = api.run(model)
    W = SOIL.gamma_unsat * 16.0
    assert res.stages[0].reactions[:, 1].sum() == pytest.approx(W + alpha * q * 4, rel=1e-9)
    assert res.stages[1].reactions[:, 1].sum() == pytest.approx(W + q * 4, rel=1e-9)


@pytest.mark.parametrize("phi", [30.0, 35.0])
def test_srf_reduces_interface_strength(phi):
    """Rigid-ish block on a 20° joint, c = 0: FS = tan(phi) / tan(beta)."""
    beta = math.radians(20.0)
    Lb, H = 6.0, 1.0
    c, s = math.cos(beta), math.sin(beta)
    p0, p1 = np.array([0.0, 0.0]), np.array([Lb * c, Lb * s])
    n = np.array([-s, c])
    base = [(-1.0, -2.0), (Lb * c + 1.0, -2.0), (Lb * c + 1.0, Lb * s), tuple(p1), tuple(p0),
            (-1.0, 0.0)]  # fmt: skip
    block = [tuple(p0), tuple(p1), tuple(p1 + H * n), tuple(p0 + H * n)]
    d = Domain()
    d.add_polygon(base, 1, edge_names=["bottom", None, None, "plane", None, None])
    d.add_polygon(block, 2)
    mesh = unstructured_mesh(d, h=0.3)
    mesh = insert_interface(mesh, "plane", "j", side="left")
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={
            "rock": api.MaterialSpec.elastic("rock", 1e7, 0.25, gamma=25.0),
            "blk": api.MaterialSpec.elastic("blk", 1e7, 0.25, gamma=25.0),
        },
        region_material={1: "rock", 2: "blk"},
        fixities=(api.Fixity("bottom", True, True),),
        initial=api.InitialStress("gravity"),
        interfaces={"j": api.InterfaceSpec("j", kn=1e8, ks=1e7, c=0.0, phi=phi)},
    )
    res = strength_reduction(model, tol=0.005)
    fs = math.tan(math.radians(phi)) / math.tan(beta)
    assert abs(res.factor - fs) / fs < 0.02, (res.factor, fs)

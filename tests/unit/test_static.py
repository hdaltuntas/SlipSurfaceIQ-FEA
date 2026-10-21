"""Static driver behaviour: initial stress, staging bookkeeping, BCs, errors."""

from __future__ import annotations

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.errors import ModelError, SingularSystemError
from slipsurface.fe2d.mesh import layered_box, rectangle
from slipsurface.fe2d.post import nodal_average

ROLLERS = (
    api.Fixity("bottom", True, True),
    api.Fixity("left", True, False),
    api.Fixity("right", True, False),
)


def column_model(initial="gravity", stages=None, layered=False):
    if layered:
        mesh = layered_box(4.0, [0.0, -3.0], -8.0, 4, [6, 10])
        mats = {
            "sand": api.MaterialSpec.elastic("sand", 3e4, 0.25, gamma=19.0),
            "clay": api.MaterialSpec.elastic("clay", 1e4, 0.35, gamma=17.0),
        }
        rm = {1: "sand", 2: "clay"}
    else:
        mesh = rectangle(4.0, 8.0, 4, 16, origin=(0.0, -8.0))
        mats = {"clay": api.MaterialSpec.elastic("clay", 1e4, 0.35, gamma=18.0)}
        rm = {1: "clay"}
    return api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials=mats,
        region_material=rm,
        fixities=ROLLERS,
        initial=api.InitialStress(initial),
        stages=stages or [],
    )


@pytest.mark.parametrize("layered", [False, True])
def test_gravity_and_k0_field_agree_for_laterally_confined_column(layered):
    """With rollers on both sides, elastic gravity loading gives K0 = nu/(1-nu)."""
    rg = api.run(column_model("gravity", layered=layered))
    rk = api.run(column_model("k0_field", layered=layered))
    sg, sk = rg.initial.sig["soil"], rk.initial.sig["soil"]
    assert np.max(np.abs(sg - sk)) < 1e-6 * np.max(np.abs(sg))
    assert np.allclose(rg.initial.u, 0.0)


def test_k0_field_values_and_override():
    m = column_model("k0_field")
    m.initial = api.InitialStress("k0_field", k0=0.6)
    r = api.run(m)
    xg = r.geom["soil"].xg
    sig = r.initial.sig["soil"]
    depth = -xg[..., 1]
    assert np.allclose(sig[..., 1], -18.0 * depth)
    assert np.allclose(sig[..., 0], 0.6 * sig[..., 1])


def test_stage_increment_superposition_and_reset():
    q = 50.0
    stages = [
        api.Stage("s1", loads=(api.EdgeLoad("top", qn=q),)),
        api.Stage("s2", loads=(api.EdgeLoad("top", qn=2 * q),), reset_displacements=True),
    ]
    r = api.run(column_model("gravity", stages))
    top = r.model.mesh.nodes("top")
    u1 = r.stage("s1").u[top, 1].mean()
    u2 = r.stage("s2").u[top, 1].mean()
    assert u1 < 0
    assert u2 == pytest.approx(u1, rel=1e-10)  # second increment equals the first
    s2 = nodal_average(r.model.mesh, r.stage("s2").sig)
    assert np.nanmean(s2[top, 1]) == pytest.approx(-2 * q, rel=1e-8)


def test_reactions_balance_loads():
    r = api.run(column_model("gravity", [api.Stage("q", loads=(api.EdgeLoad("top", qn=10.0),))]))
    assert r.last.reactions[:, 1].sum() == pytest.approx(18.0 * 4 * 8 + 10.0 * 4, rel=1e-10)
    assert r.last.reactions[:, 0].sum() == pytest.approx(0.0, abs=1e-8)


def test_point_load_and_material_override():
    m = column_model("none")
    top_mid = int(np.argmin(np.hypot(m.mesh.coords[:, 0] - 2.0, m.mesh.coords[:, 1])))
    m.materials["stiff"] = api.MaterialSpec.elastic("stiff", 1e5, 0.35)
    m.stages = [
        api.Stage("p1", loads=(api.PointLoad(top_mid, fy=-10.0),)),
        api.Stage("p2", loads=(api.PointLoad(top_mid, fy=-20.0),), material_override={1: "stiff"}),
    ]
    r = api.run(m)
    d1 = r.stage("p1").u[top_mid, 1]
    d2 = r.stage("p2").u[top_mid, 1] - d1
    assert d2 == pytest.approx(0.1 * d1, rel=1e-8)  # same increment, 10x stiffer


def test_prescribed_displacement_stage():
    m = column_model("none")
    m.displacements = (api.Displacement("top", uy=-0.01),)
    m.stages = [api.Stage("push")]
    r = api.run(m)
    assert np.allclose(r.last.u[m.mesh.nodes("top"), 1], -0.01)
    # 1D constrained modulus
    E, nu = 1e4, 0.35
    Eoed = E * (1 - nu) / ((1 + nu) * (1 - 2 * nu))
    assert r.last.reactions[m.mesh.nodes("top"), 1].sum() == pytest.approx(
        -Eoed * 0.01 / 8.0 * 4.0, rel=1e-8
    )


def test_singular_system_detected():
    m = column_model("gravity")
    m.fixities = (api.Fixity("left", True, False),)
    with pytest.raises(SingularSystemError):
        api.run(m)


def test_validation_errors():
    m = column_model()
    m.region_material = {}
    with pytest.raises(ModelError):
        api.run(m)
    m = column_model(stages=[api.Stage("bad", loads=(api.EdgeLoad("nope", 1.0),))])
    with pytest.raises(ModelError):
        api.run(m)
    m = column_model(stages=[api.Stage("exc", active_regions=frozenset())])
    with pytest.raises(NotImplementedError):
        api.run(m)

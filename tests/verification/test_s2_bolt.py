"""S2 — pretensioned end-anchored bolt: series-spring balance.

An end-anchored bolt (BAR2 between head A and anchor B) is installed with pretension T0
in an elastic block. The ground between A and B acts as a spring k_s (measured on the
same mesh by an equal-and-opposite pair of forces along the bolt), the bolt as
k_b = EA / (s L). Locking the pretension gives

    N = T0 / s * k_s / (k_s + k_b)

Criterion: bolt force within 0.5 % (achieved to round-off). Also checked: yield limit
|N| <= T_yield / s and the out-of-plane spacing equivalence.
"""

from __future__ import annotations

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.mesh import rectangle
from slipsurface.fe2d.mesh.structures import add_bar, nearest_node

E, NU = 5e4, 0.3
EA, T0 = 2.0e5, 150.0


def _mesh():
    m = rectangle(10.0, 10.0, 10, 10, origin=(0.0, -10.0))
    a, b = nearest_node(m, 5.0, 0.0), nearest_node(m, 5.0, -6.0)
    return add_bar(m, a, b, "bolt"), a, b


def _model(mesh, stages, bolt):
    return api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"s": api.MaterialSpec.elastic("s", E, NU)},
        region_material={1: "s"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        initial=api.InitialStress("none"),
        stages=stages,
        bolts={"bolt": bolt},
    )


@pytest.mark.parametrize("spacing", [1.0, 2.0])
def test_pretension_series_springs(spacing):
    mesh, a, b = _mesh()
    L = 6.0
    e = np.array([0.0, -1.0])  # A -> B
    # ground stiffness between A and B: unit forces pulling A and B together
    probe = _model(
        mesh,
        [api.Stage("probe", loads=(api.PointLoad(a, 0.0, -1.0), api.PointLoad(b, 0.0, 1.0)))],
        api.BoltSpec("bolt", EA, 1e9),
    )
    u = api.run(probe).last.u
    approach = (u[a] - u[b]) @ e  # shortening of the A-B chord per unit force
    ks = 1.0 / approach
    kb = EA / spacing / L
    expected = T0 / spacing * ks / (ks + kb)
    spec = api.BoltSpec("bolt", EA, 1e9, pretension=T0, spacing_out_of_plane=spacing)
    res = api.run(_model(mesh, [api.Stage("install", active_structures={"bolt"})], spec))
    N = res.last.bars["bolt"][0]
    assert N == pytest.approx(expected, rel=5e-3)
    assert N == pytest.approx(expected, rel=1e-9)  # exact for linear springs
    # the head moves towards the anchor
    assert (res.last.u[a] - res.last.u[b]) @ e > 0


def test_bolt_yield_limit():
    mesh, a, b = _mesh()
    ty = 50.0
    # pretension above yield: clipped to T_y, then the ground compression unloads it
    spec = api.BoltSpec("bolt", EA, ty, pretension=T0)
    res = api.run(_model(mesh, [api.Stage("install", active_structures={"bolt"})], spec))
    assert 0 < res.last.bars["bolt"][0] < ty
    # pulling the head out yields the bolt at exactly T_y
    spec = api.BoltSpec("bolt", EA, ty)
    pull = api.Stage("pull", active_structures={"bolt"}, loads=(api.PointLoad(a, 0.0, 2000.0),))
    res = api.run(_model(mesh, [api.Stage("install", active_structures={"bolt"}), pull], spec))
    assert res.last.bars["bolt"][0] == pytest.approx(ty, rel=1e-9)
    assert res.last.struct_flags["bolt"][0, 0] == 1
    # an unbolted stage leaves the bar inactive (NaN force)
    res2 = api.run(_model(mesh, [api.Stage("none")], spec))
    assert np.isnan(res2.last.bars["bolt"][0])

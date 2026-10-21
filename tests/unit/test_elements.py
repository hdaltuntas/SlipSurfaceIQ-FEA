from __future__ import annotations

import numpy as np
import pytest

from slipsurface.fe2d.core.enums import Analysis
from slipsurface.fe2d.core.errors import MeshError
from slipsurface.fe2d.fem.elements import Quad4, Quad8, Tri3, Tri6
from slipsurface.fe2d.fem.elements.quadrature import tri_rule


@pytest.mark.parametrize("el", [Tri3(), Tri6(), Quad4(), Quad8()])
def test_partition_of_unity_and_derivatives(el, rng):
    xi = rng.uniform(0, 0.5, (20, 2))
    N, dN = el.shape(xi)
    assert np.allclose(N.sum(axis=1), 1.0)
    assert np.allclose(dN.sum(axis=1), 0.0)
    h = 1e-6
    for k in range(2):
        e = np.zeros(2)
        e[k] = h
        fd = (el.shape(xi + e)[0] - el.shape(xi - e)[0]) / (2 * h)
        assert np.allclose(fd, dN[:, :, k], atol=1e-7)


def test_tri6_kronecker_property():
    pts = np.array([[0, 0], [1, 0], [0, 1], [0.5, 0], [0.5, 0.5], [0, 0.5]], dtype=float)
    N, _ = Tri6().shape(pts)
    assert np.allclose(N, np.eye(6))


@pytest.mark.parametrize("npts,deg", [(1, 1), (3, 2), (6, 4), (7, 5)])
def test_triangle_rules_integrate_monomials(npts, deg):
    from math import factorial

    r = tri_rule(npts)
    for p in range(deg + 1):
        for q in range(deg + 1 - p):
            exact = factorial(p) * factorial(q) / factorial(p + q + 2)
            num = np.sum(r.weights * r.points[:, 0] ** p * r.points[:, 1] ** q)
            assert num == pytest.approx(exact, rel=1e-12, abs=1e-14)


def test_area_and_axisymmetric_volume():
    coords = np.array([[1.0, 0.0], [3.0, 0.0], [1.0, 2.0], [2.0, 0.0], [2.0, 1.0], [1.0, 1.0]])
    conn = np.arange(6)[None, :]
    g = Tri6().precompute(coords, conn, Analysis.PLANE_STRAIN)
    assert g.wdet.sum() == pytest.approx(2.0)
    g = Tri6().precompute(coords, conn, Analysis.AXISYMMETRIC)
    # integral of r over the triangle = area * r_centroid = 2 * 5/3
    assert g.wdet.sum() == pytest.approx(2.0 * 5.0 / 3.0)


def test_inverted_element_rejected():
    coords = np.array([[0.0, 0.0], [0.0, 1.0], [1.0, 0.0]])
    with pytest.raises(MeshError):
        Tri3().precompute(coords, np.array([[0, 1, 2]]), Analysis.PLANE_STRAIN)


def test_element_stiffness_symmetric_with_three_rigid_modes():
    from slipsurface.fe2d.fem.assembly import element_stiffness
    from slipsurface.fe2d.fem.materials import isotropic_D

    coords = np.array([[0.0, 0.0], [2.0, 0.3], [0.4, 1.5]])
    mids = 0.5 * (coords[[0, 1, 2]] + coords[[1, 2, 0]])
    X = np.vstack([coords, mids])
    g = Tri6().precompute(X, np.arange(6)[None], Analysis.PLANE_STRAIN)
    K = element_stiffness(g, isotropic_D(100.0, 0.3))[0]
    assert np.allclose(K, K.T)
    ev = np.linalg.eigvalsh(K)
    assert np.sum(np.abs(ev) < 1e-9 * ev.max()) == 3


def test_quad_kronecker_property():
    c = np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]], dtype=float)
    m = 0.5 * (c + np.roll(c, -1, axis=0))
    assert np.allclose(Quad4().shape(c)[0], np.eye(4))
    assert np.allclose(Quad8().shape(np.vstack([c, m]))[0], np.eye(8))


def _quad_K(el, order="default", nu=0.3):
    from slipsurface.fe2d.fem.assembly import element_stiffness
    from slipsurface.fe2d.fem.materials import isotropic_D

    c = np.array([[0.0, 0.0], [2.0, 0.2], [2.3, 1.6], [-0.2, 1.2]])
    X = c if el.nen == 4 else np.vstack([c, 0.5 * (c + np.roll(c, -1, axis=0))])
    g = el.precompute(X, np.arange(el.nen)[None], Analysis.PLANE_STRAIN, order)
    return element_stiffness(g, isotropic_D(100.0, nu))[0]


@pytest.mark.parametrize(
    "el,order,nzero",
    [(Quad4(), "default", 3), (Quad4(bbar=False), "default", 3), (Quad8(), "high", 3),
     (Quad8(), "default", 4)],  # 2x2 reduced Q8: one (non-communicable) spurious mode
)  # fmt: skip
def test_quad_stiffness_rigid_modes(el, order, nzero):
    K = _quad_K(el, order)
    assert np.allclose(K, K.T)
    ev = np.linalg.eigvalsh(K)
    assert np.sum(np.abs(ev) < 1e-9 * ev.max()) == nzero


def test_bbar_removes_volumetric_locking():
    """Nearly incompressible strip under a uniform end shear: B-bar Q4 matches Q8,
    plain Q4 locks (far too stiff)."""
    from slipsurface.fe2d import api
    from slipsurface.fe2d.core.enums import ElemType
    from slipsurface.fe2d.fem import elements as el_mod
    from slipsurface.fe2d.mesh import rectangle

    def tip(etype, plain=False):
        mesh = rectangle(10.0, 1.0, 20, 4, etype)
        model = api.Model(
            analysis=api.Analysis.PLANE_STRAIN,
            mesh=mesh,
            materials={"m": api.MaterialSpec.elastic("m", 1e4, 0.4999)},
            region_material={1: "m"},
            fixities=(api.Fixity("left", True, True),),
            initial=api.InitialStress("none"),
            stages=[api.Stage("q", loads=(api.EdgeLoad("right", qt=10.0),))],
        )
        saved = el_mod.KERNELS[ElemType.Q4]
        if plain:
            el_mod.KERNELS[ElemType.Q4] = Quad4(bbar=False)
        try:
            u = api.run(model).last.u
        finally:
            el_mod.KERNELS[ElemType.Q4] = saved
        return np.abs(u[mesh.nodes("right"), 1]).mean()

    ref = tip(ElemType.Q8)
    assert abs(tip(ElemType.Q4) - ref) / ref < 0.1
    assert tip(ElemType.Q4, plain=True) < 0.5 * ref

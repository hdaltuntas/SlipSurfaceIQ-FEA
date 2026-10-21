from __future__ import annotations

import numpy as np
import pytest

from slipsurface.fe2d.core.enums import Analysis
from slipsurface.fe2d.core.errors import MeshError
from slipsurface.fe2d.fem.elements import Tri3, Tri6
from slipsurface.fe2d.fem.elements.quadrature import tri_rule


@pytest.mark.parametrize("el", [Tri3(), Tri6()])
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

from __future__ import annotations

import numpy as np
import pytest

from slipsurface.fe2d.core.enums import Analysis, ElemType
from slipsurface.fe2d.core.errors import MeshError
from slipsurface.fe2d.fem.elements import kernel
from slipsurface.fe2d.mesh import layered_box, plate_with_hole, rectangle
from slipsurface.fe2d.model import ElementBlock, Mesh


def _area(mesh):
    b = mesh.blocks[0]
    return kernel(b.etype).precompute(mesh.coords, b.conn, Analysis.PLANE_STRAIN).wdet.sum()


@pytest.mark.parametrize("etype", [ElemType.T3, ElemType.T6])
@pytest.mark.parametrize("pattern", ["right", "left", "alternate"])
def test_rectangle_counts_and_sets(etype, pattern):
    m = rectangle(3.0, 2.0, 6, 4, etype, pattern=pattern)
    q = 1 if etype is ElemType.T3 else 2
    assert m.nn == (q * 6 + 1) * (q * 4 + 1)
    assert m.blocks[0].ne == 2 * 6 * 4
    assert _area(m) == pytest.approx(6.0)
    assert np.allclose(m.coords[m.nodes("left"), 0], 0.0)
    assert np.allclose(m.coords[m.nodes("top"), 1], 2.0)
    assert m.edges("bottom").shape == (6, etype.nodes_per_edge)


def test_t6_midnodes_are_midpoints_on_straight_mesh():
    m = rectangle(1.0, 1.0, 3, 3, ElemType.T6, pattern="alternate")
    c = m.blocks[0].conn
    for mid, (a, b) in zip((3, 4, 5), ((0, 1), (1, 2), (2, 0))):
        assert np.allclose(m.coords[c[:, mid]], 0.5 * (m.coords[c[:, a]] + m.coords[c[:, b]]))


@pytest.mark.parametrize("etype", [ElemType.T3, ElemType.T6])
def test_plate_with_hole_geometry(etype):
    a, L = 1.0, 4.0
    m = plate_with_hole(a, L, 12, 24, etype)
    exact = L * L - np.pi * a * a / 4
    tol = 2e-3 if etype is ElemType.T3 else 1e-6
    assert _area(m) == pytest.approx(exact, rel=tol)
    r = np.hypot(*m.coords[m.nodes("hole")].T)
    assert np.allclose(r, a)
    # merged diagonal: no duplicate coordinates
    assert np.unique(np.round(m.coords, 9), axis=0).shape[0] == m.nn


def test_layered_box_regions():
    m = layered_box(10.0, [0.0, -2.0, -5.0], -10.0, 10, [2, 3, 5])
    b = m.blocks[0]
    yc = m.coords[b.conn[:, :3], 1].mean(axis=1)
    assert set(np.unique(b.region)) == {1, 2, 3}
    assert np.all(yc[b.region == 1] > -2.0)
    assert np.all((yc[b.region == 2] < -2.0) & (yc[b.region == 2] > -5.0))
    assert np.all(yc[b.region == 3] < -5.0)


def test_mesh_validation_errors():
    coords = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    with pytest.raises(MeshError):
        Mesh(coords, (ElementBlock(ElemType.T3, np.array([[0, 2, 1]]), np.array([1])),))
    with pytest.raises(MeshError):
        Mesh(coords, (ElementBlock(ElemType.T3, np.array([[0, 1, 5]]), np.array([1])),))
    with pytest.raises(MeshError):
        ElementBlock(ElemType.T6, np.array([[0, 1, 2]]), np.array([1]))


@pytest.mark.parametrize("etype", [ElemType.Q4, ElemType.Q8])
def test_mapped_quads(etype):
    m = rectangle(3.0, 2.0, 6, 4, etype)
    nq = 7 * 5
    assert m.nn == (nq if etype is ElemType.Q4 else 13 * 9 - 6 * 4)
    assert m.blocks[0].ne == 24
    assert _area(m) == pytest.approx(6.0)
    assert m.edges("top").shape == (6, etype.nodes_per_edge)
    pm = plate_with_hole(1.0, 4.0, 8, 16, etype)
    assert _area(pm) == pytest.approx(16.0 - np.pi / 4, rel=2e-3 if etype is ElemType.Q4 else 1e-5)

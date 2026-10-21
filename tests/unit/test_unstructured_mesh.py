from __future__ import annotations

import numpy as np
import pytest

from slipsurface.fe2d.core.enums import Analysis, ElemType
from slipsurface.fe2d.core.errors import MeshError
from slipsurface.fe2d.fem.elements import kernel
from slipsurface.fe2d.mesh import (
    DistanceSize,
    Domain,
    circle,
    mesh_quality,
    unstructured_mesh,
)

BOX = [(0.0, -20.0), (40.0, -20.0), (40.0, 0.0), (0.0, 0.0)]
SIDES = ["bottom", "right", "top", "left"]


def _area(mesh, region=None):
    b = mesh.blocks[0]
    w = kernel(b.etype).precompute(mesh.coords, b.conn, Analysis.PLANE_STRAIN).wdet.sum(axis=1)
    return w.sum() if region is None else w[b.region == region].sum()


def _edge_length(mesh, name):
    e = mesh.edges(name)
    return np.linalg.norm(mesh.coords[e[:, 1]] - mesh.coords[e[:, 0]], axis=1).sum()


def _tunnel_domain(n=64):
    d = Domain()
    d.add_polygon(BOX, 1, edge_names=SIDES)
    d.add_polygon([(0, -5), (40, -5), (40, 0), (0, 0)], 2)
    d.add_polygon(circle(20.0, -10.0, 3.0, n), hole=True, name="tunnel")
    d.add_line([(8.0, 0.0), (8.0, -12.0)], name="wall")
    d.add_point(30.0, -15.0, "P")
    return d


@pytest.mark.parametrize("etype", [ElemType.T3, ElemType.T6])
def test_rectangle_area_quality_sets(etype):
    d = Domain().add_polygon(BOX, edge_names=SIDES)
    m = unstructured_mesh(d, etype=etype, h=2.0, min_angle=30.0)
    assert _area(m) == pytest.approx(800.0, rel=1e-12)
    assert mesh_quality(m).min_angle >= 30.0 - 1e-6
    assert np.allclose(m.coords[m.nodes("left"), 0], 0.0)
    assert np.allclose(m.coords[m.nodes("top"), 1], 0.0)
    assert _edge_length(m, "bottom") == pytest.approx(40.0)
    assert _edge_length(m, "right") == pytest.approx(20.0)
    assert m.edges("top").shape[1] == etype.nodes_per_edge
    # every element edge is at most ~h (size field honoured)
    b = m.blocks[0]
    X = m.coords[b.conn[:, :3]]
    lmax = max(np.linalg.norm(X[:, (i + 1) % 3] - X[:, i], axis=1).max() for i in range(3))
    assert lmax < 2.0 * 1.25
    # boundary set = whole perimeter
    assert _edge_length(m, "boundary") == pytest.approx(120.0)


def test_t6_midnodes_are_midpoints():
    m = unstructured_mesh(Domain().add_polygon(BOX), h=4.0)
    c = m.blocks[0].conn
    for mid, (a, b) in zip((3, 4, 5), ((0, 1), (1, 2), (2, 0))):
        assert np.allclose(m.coords[c[:, mid]], 0.5 * (m.coords[c[:, a]] + m.coords[c[:, b]]))
    # no duplicated nodes
    assert np.unique(np.round(m.coords, 10), axis=0).shape[0] == m.nn


def test_regions_hole_line_point():
    m = unstructured_mesh(_tunnel_domain(), h=1.0)
    hole_area = 0.5 * 64 * 9.0 * np.sin(2 * np.pi / 64)
    assert _area(m) == pytest.approx(800.0 - hole_area, rel=1e-12)
    assert _area(m, 2) == pytest.approx(200.0, rel=1e-12)
    b = m.blocks[0]
    yc = m.coords[b.conn[:, :3], 1].mean(axis=1)
    assert np.all(yc[b.region == 2] > -5.0) and np.all(yc[b.region == 1] < -5.0)
    # no element centroid inside the hole
    xc = m.coords[b.conn[:, :3], 0].mean(axis=1)
    assert np.all(np.hypot(xc - 20.0, yc + 10.0) > 2.9)
    # hole wall nodes on the polygon, wall line embedded and complete
    r = np.hypot(*(m.coords[m.nodes("tunnel")] - [20.0, -10.0]).T)
    assert np.all(r <= 3.0 + 1e-9) and np.all(r >= 3.0 * np.cos(np.pi / 64) - 1e-9)
    assert _edge_length(m, "tunnel") == pytest.approx(64 * 2 * 3.0 * np.sin(np.pi / 64))
    assert np.allclose(m.coords[m.nodes("wall"), 0], 8.0)
    assert _edge_length(m, "wall") == pytest.approx(12.0)
    # the wall line does not split region 1 / 2 labelling
    assert set(np.unique(b.region)) == {1, 2}
    assert np.allclose(m.coords[m.nodes("P")], [[30.0, -15.0]])


def test_crossing_lines_share_node():
    d = Domain().add_polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    d.add_line([(1, 1), (9, 9)], "a").add_line([(1, 9), (9, 1)], "b")
    m = unstructured_mesh(d, etype=ElemType.T3, h=1.0)
    common = np.intersect1d(m.nodes("a"), m.nodes("b"))
    assert common.size == 1 and np.allclose(m.coords[common[0]], [5.0, 5.0])
    assert _edge_length(m, "a") == pytest.approx(8 * np.sqrt(2))


def test_shared_edges_merge_names():
    """Two layers sharing an edge: one set of mesh edges carries both names."""
    d = Domain()
    d.add_polygon([(0, 0), (10, 0), (10, 2), (0, 2)], 1, edge_names=[None, None, "top1", None])
    d.add_polygon([(0, 2), (10, 2), (10, 5), (0, 5)], 2, edge_names=["bot2", None, None, None])
    m = unstructured_mesh(d, h=1.0)
    assert np.array_equal(np.sort(m.nodes("top1")), np.sort(m.nodes("bot2")))
    assert _area(m, 1) == pytest.approx(20.0) and _area(m, 2) == pytest.approx(30.0)


def test_t_junction_and_overlapping_segments():
    d = Domain().add_polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    d.add_line([(5, 10), (5, 4)], "stem")  # T-junction on top edge
    d.add_line([(2, 0), (8, 0)], "footing")  # overlaps the bottom edge
    m = unstructured_mesh(d, etype=ElemType.T3, h=1.0)
    assert _edge_length(m, "footing") == pytest.approx(6.0)
    assert np.allclose(m.coords[m.nodes("footing"), 1], 0.0)
    assert _edge_length(m, "stem") == pytest.approx(6.0)
    assert _area(m) == pytest.approx(100.0)


def test_graded_size_field():
    c = circle(0.0, -25.0, 5.0, 96)
    d = Domain().add_polygon([(-50, -60), (50, -60), (50, 0), (-50, 0)])
    d.add_polygon(c, hole=True, name="tunnel")
    hf = DistanceSize(0.25, 5.0, 1.2, lines=[c], closed=[True])
    m = unstructured_mesh(d, etype=ElemType.T3, h=hf)
    b = m.blocks[0]
    X = m.coords[b.conn]
    size = np.sqrt(
        4
        / np.sqrt(3)
        * 0.5
        * np.abs(
            (X[:, 1, 0] - X[:, 0, 0]) * (X[:, 2, 1] - X[:, 0, 1])
            - (X[:, 2, 0] - X[:, 0, 0]) * (X[:, 1, 1] - X[:, 0, 1])
        )
    )
    dist = np.hypot(X[:, :, 0].mean(1), X[:, :, 1].mean(1) + 25.0) - 5.0
    assert size[dist < 0.5].max() < 0.6
    assert size[dist > 30].mean() > 2.0
    assert mesh_quality(m).min_angle > 28.0 - 1e-6


def test_polygon_max_area_and_seed_override():
    d = Domain().add_polygon([(0, 0), (10, 0), (10, 10), (0, 10)], 1)
    d.add_polygon([(2, 2), (4, 2), (4, 4), (2, 4)], 1, max_area=0.01)  # refinement zone
    d.add_polygon([(6, 6), (8, 6), (8, 8), (6, 8)], 3)
    d.add_seed(7.0, 7.0, 0)  # turn region 3 into a hole
    m = unstructured_mesh(d, etype=ElemType.T3)
    b = m.blocks[0]
    X = m.coords[b.conn]
    area = 0.5 * np.abs(
        (X[:, 1, 0] - X[:, 0, 0]) * (X[:, 2, 1] - X[:, 0, 1])
        - (X[:, 2, 0] - X[:, 0, 0]) * (X[:, 1, 1] - X[:, 0, 1])
    )
    cen = X.mean(axis=1)
    zone = (cen[:, 0] > 2) & (cen[:, 0] < 4) & (cen[:, 1] > 2) & (cen[:, 1] < 4)
    assert area[zone].max() <= 0.01 * (1 + 1e-9)
    assert set(np.unique(b.region)) == {1}
    assert area.sum() == pytest.approx(96.0)


def test_acute_input_terminates():
    d = Domain().add_polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    for a in (3.0, 9.0, 20.0, 33.0):
        t = np.radians(a)
        d.add_line([(0, 0), (9 * np.cos(t), 9 * np.sin(t))])
    th = np.radians(4.0)
    d.add_polygon([(10, 10), (5, 10), (10 - 5 * np.cos(th), 10 - 5 * np.sin(th))], 2)
    m = unstructured_mesh(d, etype=ElemType.T3, h=0.8)
    q = mesh_quality(m)
    # elements below the target may only occur in the clusters of the small input angles
    b = m.blocks[0]
    cen = m.coords[b.conn].mean(axis=1)
    bad = q.per_element_min_angle < 28.0 - 1e-6
    near_apex = (np.hypot(*cen.T) < 3.0) | (np.hypot(*(cen - 10.0).T) < 5.5)
    assert bad.any() and np.all(near_apex[bad])
    assert q.per_element_min_angle.min() >= 3.0 - 1e-6  # never worse than the input
    assert _area(m) == pytest.approx(100.0)


def test_deterministic():
    m1 = unstructured_mesh(_tunnel_domain(), h=1.5)
    m2 = unstructured_mesh(_tunnel_domain(), h=1.5)
    assert np.array_equal(m1.coords, m2.coords)
    assert np.array_equal(m1.blocks[0].conn, m2.blocks[0].conn)


def test_errors():
    with pytest.raises(MeshError):
        unstructured_mesh(Domain())
    with pytest.raises(MeshError):
        Domain().add_polygon([(0, 0), (1, 0)])
    with pytest.raises(MeshError):
        Domain().add_polygon([(0, 0), (1, 0), (2, 0)])
    with pytest.raises(MeshError):
        unstructured_mesh(Domain().add_polygon(BOX), min_angle=40.0)
    with pytest.raises(MeshError):
        unstructured_mesh(Domain().add_polygon(BOX), h=lambda x, y: -np.ones_like(x))
    with pytest.raises(MeshError):
        unstructured_mesh(Domain().add_polygon(BOX), h=0.05, max_points=1000)
    d = Domain().add_polygon(BOX)
    d.add_point(100.0, 100.0, "outside")
    with pytest.raises(MeshError):
        unstructured_mesh(d, h=5.0)

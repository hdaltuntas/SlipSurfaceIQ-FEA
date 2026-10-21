"""Conforming pair recombination, protected geometry, metadata and quad quality."""

from __future__ import annotations

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.errors import MeshError
from slipsurface.fe2d.mesh import mesh_quality, recombine_mesh, rectangle, validate_conformity


@pytest.mark.parametrize("etype", [api.ElemType.T3, api.ElemType.T6])
def test_recombination_retains_constraints_and_is_deterministic(etype):
    source = rectangle(2, 1, 4, 2, etype)
    before = source.coords.copy()
    mixed = recombine_mesh(source, where=lambda x: x[:, 0] < 1)
    other = recombine_mesh(source, where=lambda x: x[:, 0] < 1)
    assert {b.etype for b in mixed.blocks} == {
        etype,
        api.ElemType.Q4 if etype == api.ElemType.T3 else api.ElemType.Q8,
    }
    for name, edges in source.edge_sets.items():
        np.testing.assert_array_equal(source.coords[edges], mixed.coords[mixed.edges(name)])
    for name, ids in source.node_sets.items():
        if name != "all":
            np.testing.assert_array_equal(source.coords[ids], mixed.coords[mixed.nodes(name)])
    assert mixed.nn == source.nn - (4 if etype == api.ElemType.T6 else 0)
    np.testing.assert_array_equal(mixed.coords, other.coords)
    for a, b in zip(mixed.blocks, other.blocks):
        np.testing.assert_array_equal(a.conn, b.conn)
    np.testing.assert_array_equal(source.coords, before)
    validate_conformity(mixed)
    report = mesh_quality(mixed)
    assert report.n_triangles == 8 and report.n_quads == 4
    assert report.n_elements == 12
    assert report.angle_hist[0].sum() == 12
    assert report.min_quad_scaled_jacobian == pytest.approx(1)


def test_all_quads_quality_and_no_orphan_midnodes():
    source = rectangle(1, 1, 2, 2)
    mixed = recombine_mesh(source)
    assert len(mixed.blocks) == 1 and mixed.blocks[0].etype == api.ElemType.Q8
    assert len(np.unique(mixed.blocks[0].conn)) == mixed.nn
    q = mesh_quality(mixed)
    assert q.n_quads == 4 and q.n_triangles == 0
    assert q.min_angle == 90 and q.max_angle == 90
    assert np.isnan(q.max_radius_edge)
    assert q.max_aspect == pytest.approx(1)


def test_named_diagonal_and_named_quadratic_point_are_protected():
    source = rectangle(1, 1, 1, 1)
    b = source.blocks[0]
    corners = set(b.conn[0, :3]) & set(b.conn[1, :3])
    a, c = sorted(corners)
    mid = int(
        np.flatnonzero(
            np.linalg.norm(source.coords - source.coords[[a, c]].mean(axis=0), axis=1) < 1e-12
        )[0]
    )
    source.edge_sets["anchor_line"] = np.array([[a, c, mid]])
    assert recombine_mesh(source) is source
    source.edge_sets.pop("anchor_line")
    source.node_sets["point_load"] = np.array([mid])
    assert recombine_mesh(source) is source


def test_region_boundary_cannot_be_removed():
    source = rectangle(1, 1, 1, 1, api.ElemType.T3)
    b = source.blocks[0]
    source = api.Mesh(
        source.coords,
        (api.ElementBlock(b.etype, b.conn, np.array([1, 2]), b.tag),),
        source.node_sets,
        source.edge_sets,
    )
    assert recombine_mesh(source) is source


def test_curved_geometry_is_retained_as_triangles():
    source = rectangle(1, 1, 1, 1)
    coords = source.coords.copy()
    mid = source.edges("top")[0, 2]
    coords[mid, 1] += 0.05
    source = api.Mesh(coords, source.blocks, source.node_sets, source.edge_sets)
    assert recombine_mesh(source) is source


def test_concave_pair_is_not_recombined():
    source = api.Mesh(
        np.array([[0, 0], [2, 0], [0.5, 0.5], [0, 2]]),
        (api.ElementBlock(api.ElemType.T3, np.array([[0, 1, 2], [0, 2, 3]]), np.array([1, 1])),),
    )
    assert recombine_mesh(source) is source


def test_hanging_node_is_rejected():
    mesh = api.Mesh(
        np.array([[0, 0], [1, 0], [1, 1], [0, 1], [0.5, 0], [0.5, -1]]),
        (api.ElementBlock(api.ElemType.T3, np.array([[0, 1, 3], [4, 5, 1]]), np.array([1, 1])),),
    )
    with pytest.raises(MeshError, match="hanging"):
        validate_conformity(mesh)


def test_incompatible_quadratic_midnode_is_rejected():
    source = rectangle(1, 1, 1, 1)
    b = source.blocks[0]
    mid = set(b.conn[0, 3:]) & set(b.conn[1, 3:])
    mid = int(next(iter(mid)))
    coords = np.vstack([source.coords, source.coords[mid] + [0.01, 0]])
    conn = b.conn.copy()
    conn[1, conn[1] == mid] = len(coords) - 1
    mesh = api.Mesh(coords, (api.ElementBlock(b.etype, conn, b.region, b.tag),))
    with pytest.raises(MeshError, match="midnodes"):
        validate_conformity(mesh)


def test_mixed_interpolation_orders_are_rejected():
    t = rectangle(1, 1, 1, 1, api.ElemType.T3)
    q = rectangle(1, 1, 1, 1, api.ElemType.Q8, origin=(1, 0))
    mesh = api.Mesh(
        np.vstack([t.coords, q.coords]),
        (
            t.blocks[0],
            api.ElementBlock(api.ElemType.Q8, q.blocks[0].conn + t.nn, np.array([1]), "q"),
        ),
    )
    with pytest.raises(MeshError, match="one interpolation order"):
        recombine_mesh(mesh)


def test_bad_options_and_selection():
    source = rectangle(1, 1, 1, 1)
    with pytest.raises(ValueError):
        recombine_mesh(source, max_aspect=0.5)
    with pytest.raises(ValueError, match="Boolean"):
        recombine_mesh(source, where=lambda x: True)

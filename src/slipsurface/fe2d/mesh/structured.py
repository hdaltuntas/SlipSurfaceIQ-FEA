"""Structured (mapped) mesh generators.

These cover the verification problems and simple layered boxes. General geometries use
the unstructured Delaunay/Ruppert mesher in :mod:`slipsurface.fe2d.mesh.mesher`.

All generators build a ``(2*nx+1) x (2*ny+1)`` lattice from a mapping ``f(s, t) -> (x, y)``
on the unit square; T6 mid-side nodes are taken from the odd lattice points, so curved
boundaries (e.g. a hole) are represented with quadratic accuracy.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray

from ..core.enums import ElemType
from ..core.errors import MeshError
from ..model.mesh import ElementBlock, Mesh

MapFn = Callable[[NDArray[np.float64], NDArray[np.float64]], tuple[NDArray, NDArray]]


def _graded(n: int, ratio: float) -> NDArray[np.float64]:
    """n+1 points on [0, 1]; last/first segment length ratio = ``ratio``."""
    if abs(ratio - 1.0) < 1e-12:
        return np.linspace(0.0, 1.0, n + 1)
    q = ratio ** (1.0 / max(n - 1, 1))
    seg = q ** np.arange(n)
    return np.concatenate([[0.0], np.cumsum(seg) / seg.sum()])


def _fine_params(n: int, ratio: float) -> NDArray[np.float64]:
    c = _graded(n, ratio)
    out = np.empty(2 * n + 1)
    out[0::2] = c
    out[1::2] = 0.5 * (c[:-1] + c[1:])
    return out


def mapped_mesh(
    fmap: MapFn,
    nx: int,
    ny: int,
    etype: ElemType = ElemType.T6,
    grade_x: float = 1.0,
    grade_y: float = 1.0,
    pattern: str = "alternate",
    region: int = 1,
    tag: str = "soil",
) -> Mesh:
    """Mapped mesh with sets ``bottom/right/top/left`` (s=0/1, t=0/1 sides).

    Triangles (T3/T6): ``pattern`` = ``"right"`` (all diagonals one way), ``"left"`` or
    ``"alternate"`` (union-jack-like, better isotropy). Quadrilaterals (Q4/Q8) ignore it.
    """
    if etype not in (ElemType.T3, ElemType.T6, ElemType.Q4, ElemType.Q8):
        raise MeshError("mapped_mesh supports T3, T6, Q4 and Q8")
    quad = etype in (ElemType.Q4, ElemType.Q8)
    quadratic = etype in (ElemType.T6, ElemType.Q8)
    if nx < 1 or ny < 1:
        raise MeshError("nx, ny must be >= 1")
    s = _fine_params(nx, grade_x)
    t = _fine_params(ny, grade_y)
    S, T = np.meshgrid(s, t, indexing="ij")  # (2nx+1, 2ny+1)
    X, Y = fmap(S, T)
    X = np.asarray(X, dtype=float)
    Y = np.asarray(Y, dtype=float)
    mx, my = 2 * nx + 1, 2 * ny + 1

    def gid(i: NDArray, j: NDArray) -> NDArray:
        return i * my + j

    if etype is ElemType.T6:
        keep = np.ones((mx, my), dtype=bool)  # cell centres = diagonal mid-side nodes
    elif etype is ElemType.Q8:
        keep = np.ones((mx, my), dtype=bool)
        keep[1::2, 1::2] = False  # no centre node (serendipity)
    else:
        keep = np.zeros((mx, my), dtype=bool)
        keep[0::2, 0::2] = True
    new_id = -np.ones(mx * my, dtype=np.int64)
    new_id[keep.ravel()] = np.arange(int(keep.sum()))
    coords = np.column_stack([X.ravel(), Y.ravel()])[keep.ravel()]

    grid_i, grid_j = np.meshgrid(np.arange(nx), np.arange(ny), indexing="ij")
    I, J = 2 * grid_i.ravel(), 2 * grid_j.ravel()
    p00, p10 = gid(I, J), gid(I + 2, J)
    p01, p11 = gid(I, J + 2), gid(I + 2, J + 2)
    m_b, m_t = gid(I + 1, J), gid(I + 1, J + 2)
    m_l, m_r = gid(I, J + 1), gid(I + 2, J + 1)
    m_c = gid(I + 1, J + 1)
    if pattern == "right":
        flip = np.zeros(I.size, dtype=bool)
    elif pattern == "left":
        flip = np.ones(I.size, dtype=bool)
    elif pattern == "alternate":
        flip = ((I // 2 + J // 2) % 2).astype(bool)
    else:
        raise MeshError(f"unknown pattern '{pattern}'")

    # diagonal p00-p11 (not flipped) or p10-p01 (flipped)
    if quad:
        cols = [p00, p10, p11, p01] + ([m_b, m_r, m_t, m_l] if quadratic else [])
        a = np.column_stack(cols)
        b = a[:0]
    elif etype is ElemType.T6:
        a = np.where(
            flip[:, None],
            np.column_stack([p00, p10, p01, m_b, m_c, m_l]),
            np.column_stack([p00, p10, p11, m_b, m_r, m_c]),
        )
        b = np.where(
            flip[:, None],
            np.column_stack([p10, p11, p01, m_r, m_t, m_c]),
            np.column_stack([p00, p11, p01, m_c, m_t, m_l]),
        )
    else:
        a = np.where(
            flip[:, None], np.column_stack([p00, p10, p01]), np.column_stack([p00, p10, p11])
        )
        b = np.where(
            flip[:, None], np.column_stack([p10, p11, p01]), np.column_stack([p00, p11, p01])
        )
    conn = new_id[np.vstack([a, b])]
    if np.any(conn < 0):
        raise MeshError("internal error: unmapped lattice node")

    # orientation fix (mapping may be orientation-reversing)
    x = coords[conn[:, :3]]
    a2 = (x[:, 1, 0] - x[:, 0, 0]) * (x[:, 2, 1] - x[:, 0, 1]) - (x[:, 2, 0] - x[:, 0, 0]) * (
        x[:, 1, 1] - x[:, 0, 1]
    )
    neg = a2 < 0
    if np.any(neg):
        perm = {
            ElemType.T3: [0, 2, 1],
            ElemType.T6: [0, 2, 1, 5, 4, 3],
            ElemType.Q4: [0, 3, 2, 1],
            ElemType.Q8: [0, 3, 2, 1, 7, 6, 5, 4],
        }[etype]
        conn[neg] = conn[neg][:, perm]

    def side_nodes(ii: NDArray, jj: NDArray) -> NDArray:
        ids = new_id[gid(ii, jj)]
        return ids[ids >= 0]

    def side_edges(ii: NDArray, jj: NDArray) -> NDArray:
        ids = new_id[gid(ii, jj)]
        if quadratic:
            return np.column_stack([ids[0:-1:2], ids[2::2], ids[1::2]])
        ids = ids[ids >= 0]
        return np.column_stack([ids[:-1], ids[1:]])

    ax = np.arange(mx)
    ay = np.arange(my)
    sides = {
        "bottom": (ax, np.zeros(mx, dtype=int)),
        "top": (ax, np.full(mx, my - 1)),
        "left": (np.zeros(my, dtype=int), ay),
        "right": (np.full(my, mx - 1), ay),
    }
    node_sets = {k: side_nodes(*v) for k, v in sides.items()}
    edge_sets = {k: side_edges(*v) for k, v in sides.items()}
    node_sets["all"] = np.arange(coords.shape[0])
    blk = ElementBlock(etype, conn, np.full(conn.shape[0], region, dtype=np.int32), tag)
    return Mesh(coords, (blk,), node_sets, edge_sets)


def rectangle(
    lx: float,
    ly: float,
    nx: int,
    ny: int,
    etype: ElemType = ElemType.T6,
    origin: tuple[float, float] = (0.0, 0.0),
    **kw,
) -> Mesh:
    x0, y0 = origin
    return mapped_mesh(lambda s, t: (x0 + lx * s, y0 + ly * t), nx, ny, etype, **kw)


def layered_box(
    width: float,
    layer_tops: list[float],
    bottom: float,
    nx: int,
    ny_per_layer: list[int],
    etype: ElemType = ElemType.T6,
    x0: float = 0.0,
) -> Mesh:
    """Rectangular box with horizontal layers; region ids 1, 2, ... from the top down.

    ``layer_tops`` lists the top elevation of each layer from the surface down; the last
    layer extends to ``bottom``.
    """
    tops = list(layer_tops) + [bottom]
    if any(tops[i] <= tops[i + 1] for i in range(len(tops) - 1)):
        raise MeshError("layer elevations must decrease downwards")
    ny = sum(ny_per_layer)
    # piecewise-linear t -> y mapping honouring the layer interfaces
    t_knots = np.concatenate([[0.0], np.cumsum(ny_per_layer[::-1]) / ny])
    y_knots = np.array(tops[::-1])
    mesh = mapped_mesh(lambda s, t: (x0 + width * s, np.interp(t, t_knots, y_knots)), nx, ny, etype)
    blk = mesh.blocks[0]
    yc = mesh.coords[blk.conn[:, :3], 1].mean(axis=1)
    region = np.searchsorted(-np.array(tops[1:-1]), -yc, side="right").astype(np.int32) + 1
    return Mesh(
        mesh.coords,
        (ElementBlock(blk.etype, blk.conn, region, blk.tag),),
        mesh.node_sets,
        mesh.edge_sets,
    )


def plate_with_hole(
    a: float,
    L: float,
    n_r: int,
    n_t: int,
    etype: ElemType = ElemType.T6,
    grade: float = 8.0,
) -> Mesh:
    """Quarter of a square plate (side 2L) with a central circular hole of radius ``a``.

    Two mapped patches joined on the 45° diagonal. Sets: ``hole`` (edge/node), ``x_sym``
    (y = 0), ``y_sym`` (x = 0), ``outer_x`` (x = L), ``outer_y`` (y = L).
    ``grade`` is the outer/inner radial element size ratio.
    """
    if not 0 < a < L:
        raise MeshError("need 0 < a < L")
    half = max(n_t // 2, 1)

    def patch(theta0: float, theta1: float, outer: Callable) -> MapFn:
        def f(s: NDArray, t: NDArray) -> tuple[NDArray, NDArray]:
            th = theta0 + (theta1 - theta0) * t
            xin, yin = a * np.cos(th), a * np.sin(th)
            xo, yo = outer(th)
            return xin + s * (xo - xin), yin + s * (yo - yin)

        return f

    m1 = mapped_mesh(
        patch(0.0, np.pi / 4, lambda th: (np.full_like(th, L), L * np.tan(th))),
        n_r,
        half,
        etype,
        grade_x=grade,
    )
    m2 = mapped_mesh(
        patch(np.pi / 4, np.pi / 2, lambda th: (L / np.tan(th), np.full_like(th, L))),
        n_r,
        half,
        etype,
        grade_x=grade,
    )
    return _merge(
        [m1, m2],
        tol=1e-9 * L,
        rename=[
            {"left": "hole", "bottom": "x_sym", "right": "outer_x", "top": "_diag1"},
            {"left": "hole", "top": "y_sym", "right": "outer_y", "bottom": "_diag2"},
        ],
    )


def _merge(meshes: list[Mesh], tol: float, rename: list[dict[str, str]]) -> Mesh:
    """Merge meshes with coincident nodes; sets are renamed and concatenated."""
    coords = np.vstack([m.coords for m in meshes])
    offsets = np.cumsum([0] + [m.nn for m in meshes[:-1]])
    key = np.round(coords / tol).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    inv = inv.ravel()
    order = np.argsort(first)
    remap_unique = np.empty_like(order)
    remap_unique[order] = np.arange(order.size)
    gmap = remap_unique[inv]
    new_coords = coords[np.sort(first)]
    conns, regions = [], []
    node_sets: dict[str, list] = {}
    edge_sets: dict[str, list] = {}
    for m, off, rn in zip(meshes, offsets, rename):
        b = m.blocks[0]
        conns.append(gmap[b.conn + off])
        regions.append(b.region)
        for k, v in m.node_sets.items():
            if k == "all":
                continue
            node_sets.setdefault(rn.get(k, k), []).append(gmap[v + off])
        for k, v in m.edge_sets.items():
            edge_sets.setdefault(rn.get(k, k), []).append(gmap[v + off])
    ns = {k: np.unique(np.concatenate(v)) for k, v in node_sets.items() if not k.startswith("_")}
    ns["all"] = np.arange(new_coords.shape[0])
    es = {k: np.vstack(v) for k, v in edge_sets.items() if not k.startswith("_")}
    b0 = meshes[0].blocks[0]
    blk = ElementBlock(b0.etype, np.vstack(conns), np.concatenate(regions), b0.tag)
    return Mesh(new_coords, (blk,), ns, es)

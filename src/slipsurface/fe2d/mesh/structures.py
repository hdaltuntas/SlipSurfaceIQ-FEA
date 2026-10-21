"""Structural element blocks and interface node duplication (L2).

* :func:`add_beams` — BEAM2 (Timoshenko) elements along an edge set (liner, wall, sheet
  pile). Quadratic edges ``[a, b, mid]`` are split into two beam elements so that every
  beam node coincides with a continuum node.
* :func:`add_bar` / :func:`add_bars_along` — BAR2 elements between two nodes (end-anchored
  bolt, free length of an anchor) or along an embedded line (fully grouted bolt, grout body).
* :func:`insert_interface` — zero-thickness interface along an edge set: the nodes of the
  line are duplicated, the continuum elements on one side are reconnected to the copies
  and IFACE4 / IFACE6 elements pair the two faces. Ends of an open line that lie inside the
  mesh are *not* duplicated (the joint closes at its tip). Calling it twice (``side="left"``
  then ``"right"``) gives a wall with interfaces on both faces; the original nodes then
  carry only the wall (beam) and the interface faces.

Interface connectivity: face 1 ``[a1, b1(, m1)]`` then face 2 ``[a2, b2(, m2)]``; node
``a2`` is the partner of ``a1``. Face 2 lies on the left (+n) of the direction a1 → b1, so a
positive normal relative displacement ``(u2 - u1) . n`` is opening.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from ..core.enums import ElemType
from ..core.errors import MeshError
from ..model.mesh import ElementBlock, Mesh


def _replace_blocks(mesh: Mesh, blocks: list[ElementBlock], **kw: object) -> Mesh:
    return Mesh(
        kw.get("coords", mesh.coords),  # type: ignore[arg-type]
        tuple(blocks),
        kw.get("node_sets", mesh.node_sets),  # type: ignore[arg-type]
        kw.get("edge_sets", mesh.edge_sets),  # type: ignore[arg-type]
    )


def _check_tag(mesh: Mesh, tag: str) -> None:
    if any(b.tag == tag for b in mesh.blocks):
        raise MeshError(f"a block with tag '{tag}' already exists")


def _linear_segments(edges: NDArray[np.int64]) -> NDArray[np.int64]:
    """Split [a, b] or [a, b, mid] edges into 2-node segments."""
    if edges.shape[1] == 2:
        return edges.copy()
    if edges.shape[1] == 3:
        return np.vstack([edges[:, [0, 2]], edges[:, [2, 1]]])
    raise MeshError(f"unsupported edge width {edges.shape[1]}")


def add_beams(mesh: Mesh, edge_set: str, tag: str) -> Mesh:
    """BEAM2 block (tag = liner name) along ``edge_set``."""
    _check_tag(mesh, tag)
    seg = _linear_segments(mesh.edges(edge_set))
    blk = ElementBlock(ElemType.BEAM2, seg, np.zeros(seg.shape[0], dtype=np.int32), tag)
    return _replace_blocks(mesh, [*mesh.blocks, blk])


def nearest_node(mesh: Mesh, x: float, y: float) -> int:
    return int(np.argmin(np.hypot(mesh.coords[:, 0] - x, mesh.coords[:, 1] - y)))


def add_bar(mesh: Mesh, node_a: int, node_b: int, tag: str) -> Mesh:
    """Single BAR2 element (end-anchored bolt / anchor free length) between two nodes."""
    if node_a == node_b:
        raise MeshError("bar end nodes must differ")
    existing = [b for b in mesh.blocks if b.tag == tag]
    conn = np.array([[node_a, node_b]])
    if existing:
        if existing[0].etype is not ElemType.BAR2:
            raise MeshError(f"block '{tag}' is not a BAR2 block")
        conn = np.vstack([existing[0].conn, conn])
    blk = ElementBlock(ElemType.BAR2, conn, np.zeros(conn.shape[0], dtype=np.int32), tag)
    return _replace_blocks(mesh, [b for b in mesh.blocks if b.tag != tag] + [blk])


def add_bars_along(mesh: Mesh, edge_set: str, tag: str) -> Mesh:
    """BAR2 chain sharing the nodes of an embedded line (fully grouted bolt)."""
    _check_tag(mesh, tag)
    seg = _linear_segments(mesh.edges(edge_set))
    blk = ElementBlock(ElemType.BAR2, seg, np.zeros(seg.shape[0], dtype=np.int32), tag)
    return _replace_blocks(mesh, [*mesh.blocks, blk])


def boundary_node_mask(mesh: Mesh) -> NDArray[np.bool_]:
    """Nodes on the outer boundary of the continuum mesh."""
    from ..post.recovery import boundary_nodes

    m = np.zeros(mesh.nn, dtype=bool)
    m[boundary_nodes(mesh)] = True
    return m


def insert_interface(mesh: Mesh, edge_set: str, tag: str, side: str = "left") -> Mesh:
    """Duplicate the nodes of ``edge_set`` and insert an IFACE4/IFACE6 block ``tag``.

    ``side``: which side's continuum elements move to the new nodes ("left" of the edge
    direction, or "right"). Edge sets produced by the unstructured mesher keep the
    direction of the input line.
    """
    if side not in ("left", "right"):
        raise MeshError("side must be 'left' or 'right'")
    _check_tag(mesh, tag)
    edges = mesh.edges(edge_set)
    npe = edges.shape[1]
    X = mesh.coords
    nn = mesh.nn
    # ---- nodes to duplicate: all line nodes except interior open ends
    ends = np.concatenate([edges[:, 0], edges[:, 1]])
    uniq, cnt = np.unique(ends, return_counts=True)
    tips = uniq[cnt == 1]
    on_bnd = boundary_node_mask(mesh)
    keep_shared = tips[~on_bnd[tips]]
    line_nodes = np.unique(edges)
    dup = np.setdiff1d(line_nodes, keep_shared)
    if dup.size == 0:
        raise MeshError("nothing to duplicate (closed tips on both ends of a single edge?)")
    copy_of = -np.ones(nn, dtype=np.int64)
    copy_of[dup] = nn + np.arange(dup.size)
    new_coords = np.vstack([X, X[dup]])

    # ---- classify continuum elements touching duplicated nodes by the nearest line edge
    A, B = X[edges[:, 0]], X[edges[:, 1]]
    T = B - A
    L2 = np.maximum(np.einsum("ij,ij->i", T, T), 1e-300)
    sgn = 1.0 if side == "left" else -1.0
    blocks = []
    for b in mesh.blocks:
        if b.etype not in (ElemType.T3, ElemType.T6, ElemType.Q4, ElemType.Q8):
            blocks.append(b)
            continue
        conn = b.conn.copy()
        touch = np.flatnonzero((copy_of[conn] >= 0).any(axis=1))
        if touch.size:
            nc = 4 if b.etype in (ElemType.Q4, ElemType.Q8) else 3
            cen = X[conn[touch, :nc]].mean(axis=1)
            rel = cen[:, None, :] - A[None]  # (m, e, 2)
            t = np.clip(np.einsum("mej,ej->me", rel, T) / L2, 0, 1)
            d = np.linalg.norm(rel - t[..., None] * T[None], axis=-1)
            k = d.argmin(axis=1)
            cross = (
                T[k, 0] * rel[np.arange(touch.size), k, 1]
                - T[k, 1] * rel[np.arange(touch.size), k, 0]
            )
            move = touch[sgn * cross > 0]
            sub = conn[move]
            repl = copy_of[sub]
            conn[move] = np.where(repl >= 0, repl, sub)
        blocks.append(ElementBlock(b.etype, conn, b.region, b.tag))

    # ---- interface elements: face 2 must be on the left of a1 -> b1
    c2 = np.where(copy_of[edges] >= 0, copy_of[edges], edges)
    if side == "left":
        f1, f2 = edges, c2
    else:  # reverse the direction so that the moved (right) side is on the left
        perm = [1, 0] + ([2] if npe == 3 else [])
        f1, f2 = edges[:, perm], c2[:, perm]
    if npe == 2:
        iconn, et = np.hstack([f1, f2]), ElemType.IFACE4
    else:
        iconn, et = np.hstack([f1, f2]), ElemType.IFACE6
    iblk = ElementBlock(et, iconn, np.zeros(iconn.shape[0], dtype=np.int32), tag)

    # ---- sets: nodes sets get both copies; edges follow the element that owns them
    node_sets = {}
    for k, v in mesh.node_sets.items():
        extra = copy_of[v][copy_of[v] >= 0]
        node_sets[k] = (
            np.unique(np.concatenate([v, extra])) if k != "all" else np.arange(new_coords.shape[0])
        )
    owner_keys: set[tuple[int, ...]] = set()
    for b in blocks:
        if b.etype in (ElemType.T3, ElemType.T6, ElemType.Q4, ElemType.Q8):
            nc = 4 if b.etype in (ElemType.Q4, ElemType.Q8) else 3
            for i in range(nc):
                a, c = b.conn[:, i], b.conn[:, (i + 1) % nc]
                for p, q in zip(a.tolist(), c.tolist()):
                    owner_keys.add((min(p, q), max(p, q)))
    edge_sets = {}
    for k, e in mesh.edge_sets.items():
        e2 = e.copy()
        for r in range(e.shape[0]):
            a, c = int(e[r, 0]), int(e[r, 1])
            if (min(a, c), max(a, c)) in owner_keys:
                continue
            ra = copy_of[e[r]]
            cand = np.where(ra >= 0, ra, e[r])
            if (min(int(cand[0]), int(cand[1])), max(int(cand[0]), int(cand[1]))) in owner_keys:
                e2[r] = cand
        edge_sets[k] = e2
    edge_sets[f"{tag}:face1"] = f1
    edge_sets[f"{tag}:face2"] = f2
    node_sets[f"{tag}:face2"] = np.unique(f2)
    return Mesh(new_coords, (*blocks, iblk), node_sets, edge_sets)

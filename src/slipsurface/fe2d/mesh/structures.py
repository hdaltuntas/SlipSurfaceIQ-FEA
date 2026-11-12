"""Structural element blocks and interface node duplication (L2).

* :func:`add_beams` — BEAM2 (Timoshenko) elements along an edge set (liner, wall, sheet
  pile). Quadratic edges ``[a, b, mid]`` are split into two beam elements so that every
  beam node coincides with a continuum node.
* :func:`add_bar` / :func:`add_bars_along` — BAR2 elements between two nodes (end-anchored
  bolt, free length of an anchor) or along an embedded line (fully grouted bolt, grout body).
* :func:`add_bar_with_bonded_tail` — one free BAR2 length followed by a perfectly bonded
  BAR2 tail on a named embedded edge chain. This is topology only; it does not add finite
  grout bond-slip stiffness or strength.
* :func:`add_embedded_bonded_bar` — a BOND4 chain with host continuum nodes and
  duplicated scalar-slip tendon nodes for finite axial bond transfer.
* :func:`add_tieback_series` — one unbonded TIE3 element from the wall/head node to
  the first BOND4 scalar tendon station, followed by the finite-bonded tail.
* :func:`insert_interface` — zero-thickness interface along an edge set: the nodes of the
  line are duplicated, the continuum elements on one side are reconnected to the copies
  and IFACE4 / IFACE6 elements pair the two faces. Ends of an open line that lie inside the
  mesh are *not* duplicated (the joint closes at its tip). Calling it twice (``side="left"``
  then ``"right"``) gives a wall with interfaces on both faces; the original nodes then
  carry only the wall (beam) and the interface faces, except the shared interior tips.
  Existing interface cuts are ignored when classifying exterior endpoints, so both
  insertion orders preserve the same closed interior tips.

Node sets that belong to an edge set of the same name (the sets created from named
polygon edges) follow their edges to one side of the joint; other node sets get both
copies of a duplicated node.

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


def _ordered_open_chain(
    seg: NDArray[np.int64], start_node: int | None = None
) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    """Return oriented 2-node segments and node order for one open non-branching chain."""
    if seg.ndim != 2 or seg.shape[1] != 2 or seg.shape[0] == 0:
        raise MeshError("edge chain must contain at least one 2-node segment")
    if np.any(seg[:, 0] == seg[:, 1]):
        raise MeshError("edge chain contains a zero-length topological segment")
    nodes, degree = np.unique(seg, return_counts=True)
    if np.any(degree > 2) or np.count_nonzero(degree == 1) != 2:
        raise MeshError("edge set must form one non-branching open chain")
    endpoints = nodes[degree == 1]
    if start_node is None:
        first = int(seg[0, 0])
        start = first if first in endpoints else int(endpoints.min())
    else:
        start = int(start_node)
        if start not in endpoints:
            raise MeshError("start node must be an endpoint of the edge chain")
    adjacency: dict[int, list[int]] = {int(n): [] for n in nodes}
    for a, b in seg:
        ia, ib = int(a), int(b)
        adjacency[ia].append(ib)
        adjacency[ib].append(ia)
    order = [start]
    previous = -1
    current = start
    while True:
        nxt = [n for n in adjacency[current] if n != previous]
        if not nxt:
            break
        if len(nxt) != 1:
            raise MeshError("edge set must form one non-branching open chain")
        previous, current = current, nxt[0]
        order.append(current)
    if len(order) != len(nodes):
        raise MeshError("edge set must form one connected chain")
    ordered = np.column_stack([order[:-1], order[1:]]).astype(np.int64)
    return ordered, np.asarray(order, dtype=np.int64)

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


def add_bar_with_bonded_tail(
    mesh: Mesh,
    node_head: int,
    bond_start_node: int,
    bonded_edge_set: str,
    tag: str,
) -> Mesh:
    """Add an anchor free length followed by a perfectly bonded BAR2 tail.

    The free length is one BAR2 element from node_head to bond_start_node.
    The named edge set must be one connected, non-branching open chain whose endpoint
    is bond_start_node. Its BAR2 segments share continuum nodes and therefore model
    a perfect bond. Finite grout bond-slip stiffness/strength needs a separate element
    law and is deliberately not approximated here.
    """
    _check_tag(mesh, tag)
    if not (0 <= node_head < mesh.nn and 0 <= bond_start_node < mesh.nn):
        raise MeshError("bar head and bond-start node ids must be inside the mesh")
    if node_head == bond_start_node:
        raise MeshError("bar head and bond-start nodes must differ")

    seg = _linear_segments(mesh.edges(bonded_edge_set))
    if seg.shape[0] == 0:
        raise MeshError("bonded edge set must contain at least one segment")
    if np.any(seg[:, 0] == seg[:, 1]):
        raise MeshError("bonded edge set contains a zero-length topological segment")

    nodes, degree = np.unique(seg, return_counts=True)
    if np.any(degree > 2) or np.count_nonzero(degree == 1) != 2:
        raise MeshError("bonded edge set must form one non-branching open chain")
    where_start = np.flatnonzero(nodes == bond_start_node)
    if where_start.size != 1 or degree[int(where_start[0])] != 1:
        raise MeshError("bond-start node must be an endpoint of the bonded edge chain")
    if np.any(nodes == node_head):
        raise MeshError("bar head must lie outside the bonded edge chain")

    adjacency: dict[int, list[int]] = {int(n): [] for n in nodes}
    for a, b in seg:
        ia, ib = int(a), int(b)
        adjacency[ia].append(ib)
        adjacency[ib].append(ia)
    seen = {int(bond_start_node)}
    stack = [int(bond_start_node)]
    while stack:
        current = stack.pop()
        for neighbour in adjacency[current]:
            if neighbour not in seen:
                seen.add(neighbour)
                stack.append(neighbour)
    if len(seen) != len(nodes):
        raise MeshError("bonded edge set must form one connected chain")

    free = np.array([[node_head, bond_start_node]], dtype=np.int64)
    conn = np.vstack([free, seg])
    blk = ElementBlock(ElemType.BAR2, conn, np.zeros(conn.shape[0], dtype=np.int32), tag)
    return _replace_blocks(mesh, [*mesh.blocks, blk])


def add_embedded_bonded_bar(
    mesh: Mesh,
    edge_set: str,
    tag: str,
    *,
    start_node: int | None = None,
) -> Mesh:
    """Create a finite-bond embedded tendon chain on a host edge set.

    Each BOND4 row is ``[host_a, host_b, slip_a, slip_b]``. The host nodes retain
    ordinary continuum displacement DOFs. The duplicated nodes are colocated but are
    interpreted by the solver as one scalar axial-slip DOF each; they are not physical
    2-D tendon nodes. The structural group combines tendon axial stiffness with the
    separately defined BondSlipSpec transfer law.

    Node sets ``<tag>:slip``, ``<tag>:slip_start`` and ``<tag>:slip_end`` are added
    for diagnostics and controlled verification.
    """
    _check_tag(mesh, tag)
    seg, order = _ordered_open_chain(_linear_segments(mesh.edges(edge_set)), start_node)
    if np.any(np.linalg.norm(mesh.coords[seg[:, 1]] - mesh.coords[seg[:, 0]], axis=1) <= 0):
        raise MeshError("embedded bond path contains a zero-length geometric segment")

    nn = mesh.nn
    slip_of = {int(host): nn + i for i, host in enumerate(order.tolist())}
    slip_nodes = np.asarray([slip_of[int(host)] for host in order], dtype=np.int64)
    new_coords = np.vstack([mesh.coords, mesh.coords[order]])
    conn = np.column_stack([
        seg[:, 0],
        seg[:, 1],
        np.asarray([slip_of[int(n)] for n in seg[:, 0]], dtype=np.int64),
        np.asarray([slip_of[int(n)] for n in seg[:, 1]], dtype=np.int64),
    ])
    block = ElementBlock(
        ElemType.BOND4, conn, np.zeros(conn.shape[0], dtype=np.int32), tag
    )
    node_sets = dict(mesh.node_sets)
    node_sets[f"{tag}:slip"] = slip_nodes
    node_sets[f"{tag}:slip_start"] = slip_nodes[:1]
    node_sets[f"{tag}:slip_end"] = slip_nodes[-1:]
    return _replace_blocks(
        mesh, [*mesh.blocks, block], coords=new_coords, node_sets=node_sets
    )

def add_tieback_series(
    mesh: Mesh,
    node_head: int,
    bonded_edge_set: str,
    tag: str,
    *,
    bond_start_node: int | None = None,
) -> Mesh:
    """Create a straight unbonded + finite-bonded tieback series topology.

    Two structural blocks are created:

    * <tag>:free — one TIE3 unbonded tendon element with connectivity
      [head, host_bond_start, scalar_bond_start];
    * <tag>:bond — the BOND4 bonded tail created by add_embedded_bonded_bar.

    The free element uses the same scalar tendon displacement at the bond start as the
    bonded tail, so axial force is transferred in series without tying the tendon to the
    host soil at the free/bond transition.
    """
    free_tag = f"{tag}:free"
    bond_tag = f"{tag}:bond"
    _check_tag(mesh, free_tag)
    _check_tag(mesh, bond_tag)
    if not 0 <= int(node_head) < mesh.nn:
        raise MeshError("tieback head node id must be inside the mesh")

    out = add_embedded_bonded_bar(
        mesh, bonded_edge_set, bond_tag, start_node=bond_start_node
    )
    bond = out.block(bond_tag)
    host_start = int(bond.conn[0, 0])
    slip_start = int(bond.conn[0, 2])
    if int(node_head) == host_start:
        raise MeshError("tieback unbonded length must be non-zero")

    free_vec = out.coords[host_start] - out.coords[int(node_head)]
    bond_vec = out.coords[int(bond.conn[0, 1])] - out.coords[host_start]
    lf = float(np.linalg.norm(free_vec))
    lb = float(np.linalg.norm(bond_vec))
    if lf <= 0 or lb <= 0:
        raise MeshError("tieback free and bonded segments must have positive length")
    cross = abs(float(free_vec[0] * bond_vec[1] - free_vec[1] * bond_vec[0]))
    if cross > 1e-10 * lf * lb or float(free_vec @ bond_vec) <= 0:
        raise MeshError("tieback free length must continue straight into the bonded tail")

    conn = np.array([[int(node_head), host_start, slip_start]], dtype=np.int64)
    block = ElementBlock(ElemType.TIE3, conn, np.zeros(1, dtype=np.int32), free_tag)
    node_sets = dict(out.node_sets)
    node_sets[f"{tag}:head"] = np.array([int(node_head)], dtype=np.int64)
    node_sets[f"{tag}:bond_start"] = np.array([host_start], dtype=np.int64)
    return _replace_blocks(out, [*out.blocks, block], node_sets=node_sets)


def tieback_component_tags(tag: str) -> tuple[str, str]:
    """Return (free_tag, bonded_tag) for add_tieback_series."""
    return f"{tag}:free", f"{tag}:bond"

def boundary_node_mask(mesh: Mesh) -> NDArray[np.bool_]:
    """Exterior node mask with existing paired interface faces identified."""
    from .topology import boundary_nodes

    m = np.zeros(mesh.nn, dtype=bool)
    m[boundary_nodes(mesh, join_interfaces=True)] = True
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
            n0, n1 = int(e[r, 0]), int(e[r, 1])
            if (min(n0, n1), max(n0, n1)) in owner_keys:
                continue
            ra = copy_of[e[r]]
            cand = np.where(ra >= 0, ra, e[r])
            if (min(int(cand[0]), int(cand[1])), max(int(cand[0]), int(cand[1]))) in owner_keys:
                e2[r] = cand
        edge_sets[k] = e2
    # a node set that is the node set of an edge set of the same name follows the side its
    # edges were moved to (otherwise both copies would carry e.g. a prescribed head of
    # the other side); pure node sets (points, supports) keep both copies
    for k, e in edge_sets.items():
        if (
            k in node_sets
            and k in mesh.node_sets
            and np.array_equal(np.unique(mesh.node_sets[k]), np.unique(mesh.edge_sets[k]))
        ):
            node_sets[k] = np.unique(e)
    edge_sets[f"{tag}:face1"] = f1
    edge_sets[f"{tag}:face2"] = f2
    node_sets[f"{tag}:face2"] = np.unique(f2)
    return Mesh(new_coords, (*blocks, iblk), node_sets, edge_sets)

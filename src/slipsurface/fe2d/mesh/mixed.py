"""Conforming triangle/quad meshes by conservative triangle-pair recombination.

This operates before model construction and before adding beams/bars/interfaces.
Only convex, straight-sided pairs in the same region and block are recombined.
Named edges and quadratic nodes in named node sets are protected. Node IDs can change;
all sets are remapped. This is a deterministic quality-based greedy pairing, not a
structured quad mesher or a guarantee of a prescribed quad fraction/alignment.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from scipy.spatial import cKDTree

from ..core.enums import ElemType
from ..core.errors import MeshError
from ..model.mesh import ElementBlock, Mesh

_CONT = (ElemType.T3, ElemType.T6, ElemType.Q4, ElemType.Q8)
_QUADRATIC = (ElemType.T6, ElemType.Q8)


def _edge_records(mesh):
    records = {}
    for block in mesh.continuum_blocks():
        nc = 3 if block.etype in (ElemType.T3, ElemType.T6) else 4
        for conn in block.conn:
            for i in range(nc):
                a, b = int(conn[i]), int(conn[(i + 1) % nc])
                mid = int(conn[nc + i]) if block.etype in _QUADRATIC else None
                records.setdefault(tuple(sorted((a, b))), []).append(mid)
    return records


def _tolerance(mesh):
    span = max(float(np.ptp(mesh.coords, axis=0).max()), 1.0)
    return max(1e-10 * span, 64 * np.finfo(float).eps * float(np.abs(mesh.coords).max()))


def validate_conformity(mesh: Mesh) -> None:
    """Validate a continuum-only, single-order mesh before inserting interfaces.

    Reject nonmanifold edges, duplicate coordinates, inconsistent shared midnodes,
    and hanging corner nodes on straight edges. Curved shared edges must have the
    same endpoints and midnode; general curved-edge intersection tests are outside
    this check. It does not test arbitrary overlapping element interiors.
    """
    if not mesh.blocks or any(b.etype not in _CONT for b in mesh.blocks):
        raise MeshError("conformity check requires continuum blocks before adding structures")
    if not np.isfinite(mesh.coords).all():
        raise MeshError("continuum coordinates must be finite")
    if len({b.tag for b in mesh.blocks}) != len(mesh.blocks):
        raise MeshError("continuum block tags must be unique")
    if len({b.etype in _QUADRATIC for b in mesh.blocks if b.ne}) != 1:
        raise MeshError("use one interpolation order: T3/Q4 or T6/Q8")
    tol = _tolerance(mesh)
    used = np.unique(np.concatenate([b.conn.ravel() for b in mesh.blocks]))
    if cKDTree(mesh.coords[used]).query_pairs(tol):
        raise MeshError(
            "coincident continuum nodes have different IDs; merge them before interfaces"
        )
    records = _edge_records(mesh)
    corners = np.unique(
        np.concatenate(
            [
                b.conn[:, : 3 if b.etype in (ElemType.T3, ElemType.T6) else 4].ravel()
                for b in mesh.blocks
            ]
        )
    )
    tree = cKDTree(mesh.coords[corners])
    for (a, b), mids in records.items():
        if len(mids) > 2:
            raise MeshError("nonmanifold continuum edge has more than two owners")
        if any(mid != mids[0] for mid in mids):
            raise MeshError("shared edge has incompatible interpolation or quadratic midnodes")
        A, B = mesh.coords[[a, b]]
        v = B - A
        length = np.linalg.norm(v)
        if length <= tol:
            raise MeshError("degenerate continuum edge")
        mid = mids[0]
        if mid is not None and np.linalg.norm(mesh.coords[mid] - (A + B) / 2) > tol:
            continue
        ids = corners[tree.query_ball_point((A + B) / 2, length / 2 + tol)]
        rel = mesh.coords[ids] - A
        t = rel @ v / (length * length)
        distance = np.abs(rel[:, 0] * v[1] - rel[:, 1] * v[0]) / length
        if np.any((t > tol / length) & (t < 1 - tol / length) & (distance <= tol)):
            raise MeshError("hanging corner node on a continuum edge")
    for name, edges in mesh.edge_sets.items():
        for row in edges:
            mids = records.get(tuple(sorted(map(int, row[:2]))))
            if mids is None or len(row) != (2 if mids[0] is None else 3):
                raise MeshError(f"edge set '{name}' does not match continuum edges")
            if len(row) == 3 and row[2] != mids[0]:
                raise MeshError(f"edge set '{name}' has an incompatible midnode")


def recombine_mesh(
    mesh: Mesh,
    *,
    min_angle: float = 45.0,
    max_aspect: float = 5.0,
    where: Callable[[np.ndarray], np.ndarray] | None = None,
) -> Mesh:
    """Pair suitable T3/T6 elements into Q4/Q8, preserving constrained topology.

    ``where`` receives triangle centroids (ne,2) and returns a Boolean mask (ne,).
    Both triangles must be selected. Existing quads pass through unchanged. Curved
    T6 pairs remain triangular. Returns a mesh, not a solved/refined solver state.
    Build loads, material assignments and structural elements after this operation.
    """
    if not 0 < min_angle <= 90 or not np.isfinite(max_aspect) or max_aspect < 1:
        raise ValueError("need 0 < min_angle <= 90 and finite max_aspect >= 1")
    validate_conformity(mesh)
    tol = _tolerance(mesh)
    protected = {
        tuple(sorted(map(int, row[:2]))) for edges in mesh.edge_sets.values() for row in edges
    }
    named_nodes = set(int(n) for name, ids in mesh.node_sets.items() if name != "all" for n in ids)
    tags = {b.tag for b in mesh.blocks}
    blocks = []
    changed = False
    for block in mesh.blocks:
        if block.etype not in (ElemType.T3, ElemType.T6) or not block.ne:
            blocks.append(block)
            continue
        conn = block.conn
        X = mesh.coords[conn[:, :3]]
        selected = (
            np.ones(block.ne, dtype=bool)
            if where is None
            else np.asarray(where(X.mean(axis=1)))
        )
        if selected.shape != (block.ne,) or selected.dtype.kind != "b":
            raise ValueError("where must return one Boolean per triangle")
        owners: dict[tuple[int, ...], list[int]] = {}
        mids: dict[tuple[int, ...], int] = {}
        for e, row in enumerate(conn):
            for j in range(3):
                key = tuple(sorted((int(row[j]), int(row[(j + 1) % 3]))))
                owners.setdefault(key, []).append(e)
                if block.etype is ElemType.T6:
                    mids[key] = int(row[3 + j])
        candidates = []
        for edge, pair in owners.items():
            if len(pair) != 2 or edge in protected:
                continue
            i, j = pair
            if not selected[i] or not selected[j] or block.region[i] != block.region[j]:
                continue
            if block.etype is ElemType.T6 and mids[edge] in named_nodes:
                continue
            vertices = np.unique(conn[[i, j], :3])
            if len(vertices) != 4:
                continue
            points = mesh.coords[vertices]
            centre = points.mean(axis=0)
            vertices = vertices[
                np.argsort(np.arctan2(points[:, 1] - centre[1], points[:, 0] - centre[0]))
            ]
            points = mesh.coords[vertices]
            edges = np.roll(points, -1, axis=0) - points
            prev = np.roll(edges, 1, axis=0)
            cross = prev[:, 0] * edges[:, 1] - prev[:, 1] * edges[:, 0]
            lengths = np.linalg.norm(edges, axis=1)
            if np.min(cross) <= tol * max(float(np.max(lengths)), tol):
                continue
            angles = 180 - np.degrees(np.arctan2(cross, np.einsum("ij,ij->i", prev, edges)))
            aspect = float(np.max(lengths)) ** 2 / float(np.min(cross))
            if (
                float(np.min(angles)) < min_angle - 1e-10
                or float(np.max(angles)) > 180 - min_angle + 1e-10
                or aspect > max_aspect
            ):
                continue
            qconn = list(map(int, vertices))
            if block.etype is ElemType.T6:
                keys = [
                    tuple(sorted((int(vertices[k]), int(vertices[(k + 1) % 4])))) for k in range(4)
                ]
                # Conservative: do not change a curved triangle's geometry mapping.
                all_keys = set(keys) | {edge}
                if any(
                    np.linalg.norm(mesh.coords[mids[k]] - mesh.coords[list(k)].mean(axis=0)) > tol
                    for k in all_keys
                ):
                    continue
                qconn += [mids[k] for k in keys]
            score = np.min(cross / (np.roll(lengths, 1) * lengths)) / aspect
            candidates.append((-score, i, j, qconn))
        used = np.zeros(block.ne, dtype=bool)
        quads, regions = [], []
        for _, i, j, qconn in sorted(candidates, key=lambda c: (c[0], c[1], c[2])):
            if used[i] or used[j]:
                continue
            used[[i, j]] = True
            quads.append(qconn)
            regions.append(block.region[i])
        if not quads:
            blocks.append(block)
            continue
        changed = True
        if np.any(~used):
            blocks.append(ElementBlock(block.etype, conn[~used], block.region[~used], block.tag))
        tag = block.tag + ":quad"
        while tag in tags:
            tag += "_"
        tags.add(tag)
        blocks.append(
            ElementBlock(
                ElemType.Q8 if block.etype is ElemType.T6 else ElemType.Q4,
                np.asarray(quads),
                np.asarray(regions),
                tag,
            )
        )
    if not changed:
        return mesh
    used = np.unique(
        np.concatenate(
            [b.conn.ravel() for b in blocks]
            + [ids for name, ids in mesh.node_sets.items() if name != "all"]
        )
    )
    remap = np.full(mesh.nn, -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    out = Mesh(
        mesh.coords[used],
        tuple(ElementBlock(b.etype, remap[b.conn], b.region, b.tag) for b in blocks),
        {
            name: np.arange(len(used)) if name == "all" else remap[ids]
            for name, ids in mesh.node_sets.items()
        },
        {name: remap[edges] for name, edges in mesh.edge_sets.items()},
    )
    validate_conformity(out)
    return out

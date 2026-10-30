"""Which elements are on, and which inactive interface nodes stay tied.

The Newton loop is not here. A stage only passes regions and structure names in;
these functions turn that into per-element masks and master/slave node pairs.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from ..core.enums import ElemType
from .structural import BeamGroup, InterfaceGroup


def edge_owner_map(blocks) -> dict[tuple[int, int], tuple[int, int]]:
    """Undirected continuum edge -> (block index, element index)."""
    out: dict[tuple[int, int], tuple[int, int]] = {}
    for bi, b in enumerate(blocks):
        nc = 4 if b.etype in (ElemType.Q4, ElemType.Q8) else 3
        for i in range(nc):
            a, c = b.conn[:, i], b.conn[:, (i + 1) % nc]
            for e, (p, q) in enumerate(zip(a.tolist(), c.tolist())):
                out[(min(p, q), max(p, q))] = (bi, e)
    return out


def interface_adjacency(blocks, groups) -> dict[str, tuple[NDArray, NDArray, NDArray, NDArray]]:
    """For each interface element: continuum (block, element) owning face 1 / face 2."""
    if not any(isinstance(g, InterfaceGroup) for g in groups):
        return {}
    owner = edge_owner_map(blocks)
    out = {}
    for g in groups:
        if not isinstance(g, InterfaceGroup):
            continue
        res = []
        for face in (g.f1, g.f2):
            bi = np.full(g.ne, -1)
            ei = np.full(g.ne, -1)
            for k, (p, q) in enumerate(zip(face[:, 0].tolist(), face[:, 1].tolist())):
                hit = owner.get((min(p, q), max(p, q)))
                if hit is not None:
                    bi[k], ei[k] = hit
            res += [bi, ei]
        out[g.tag] = tuple(res)
    return out


def interface_face_keys(groups) -> set[tuple[int, int]]:
    keys: set[tuple[int, int]] = set()
    for g in groups:
        if isinstance(g, InterfaceGroup):
            for face in (g.f1, g.f2):
                for p, q in zip(face[:, 0].tolist(), face[:, 1].tolist()):
                    keys.add((min(p, q), max(p, q)))
    return keys


def active_masks(blocks, groups, adjacency, regions, structures, nn: int):
    """Activity per block; ``structures=None`` means all interfaces, no beams/bars."""
    act: dict[str, NDArray[np.bool_]] = {}
    for b in blocks:
        act[b.tag] = (
            np.ones(b.ne, dtype=bool)
            if regions is None
            else np.isin(b.region, np.fromiter(regions, dtype=np.int64))
        )
    beam_nodes = np.zeros(nn, dtype=bool)
    for g in groups:
        if isinstance(g, BeamGroup) and structures is not None and g.tag in structures:
            beam_nodes[g.block.conn.ravel()] = True
    for g in groups:
        on = (isinstance(g, InterfaceGroup) and structures is None) or (
            structures is not None and g.tag in structures
        )
        m = np.full(g.ne, on)
        if on and isinstance(g, InterfaceGroup):
            # a face is supported by an active continuum element owning it or by an
            # active beam carrying all its nodes; otherwise the joint is switched off
            b1, e1, b2, e2 = adjacency[g.tag]
            for face, bi, ei in ((g.f1, b1, e1), (g.f2, b2, e2)):
                ok = beam_nodes[face].all(axis=1) | (bi < 0)
                for k in np.flatnonzero(bi >= 0):
                    ok[k] |= bool(act[blocks[bi[k]].tag][ei[k]])
                m &= ok
        act[g.tag] = m
    return act


def tie_pairs(groups, active, nn: int) -> NDArray[np.int64]:
    """Partner-node pairs of inactive interface elements (full continuity there).

    A pair is tied only if no *active* interface element joins the same two nodes, so a
    partially active joint keeps its relative displacement where it is active.
    """
    pairs, keep = [], []
    for g in groups:
        if not isinstance(g, InterfaceGroup):
            continue
        pr = np.stack([g.f1, g.f2], axis=-1).reshape(-1, 2)  # (ne*npe, 2)
        on = np.repeat(active[g.tag], g.npe)
        pairs.append(pr[~on])
        keep.append(pr[on])
    if not pairs:
        return np.empty((0, 2), np.int64)
    tie = np.vstack(pairs)
    tie = tie[tie[:, 0] != tie[:, 1]]
    act = np.vstack(keep)
    if act.size and tie.size:
        k_t = np.minimum(tie[:, 0], tie[:, 1]) * nn + np.maximum(tie[:, 0], tie[:, 1])
        k_a = np.minimum(act[:, 0], act[:, 1]) * nn + np.maximum(act[:, 0], act[:, 1])
        tie = tie[~np.isin(k_t, k_a)]
    return np.unique(tie, axis=0) if tie.size else tie

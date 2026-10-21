"""Continuum boundary topology shared by meshing and post-processing (L2)."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from ..core.enums import ElemType
from ..model.mesh import Mesh


def boundary_nodes(mesh: Mesh, *, join_interfaces: bool = False) -> NDArray[np.int64]:
    """Nodes on continuum edges used by one element.

    By default interface faces are boundaries too (e.g. for stress recovery).
    ``join_interfaces=True`` identifies explicitly paired interface nodes only for
    this topology query, so existing internal cuts cannot turn embedded joint tips
    into exterior tips. All copies of an exterior node are included in the result;
    coordinates, connectivity and mechanical degrees of freedom remain untouched.
    """
    keys, mids = [], []
    nn = mesh.nn
    alias = np.arange(nn)
    if join_interfaces:
        for block in mesh.blocks:
            if block.etype not in (ElemType.IFACE4, ElemType.IFACE6):
                continue
            nface = block.conn.shape[1] // 2
            for a, b in zip(block.conn[:, :nface].ravel(), block.conn[:, nface:].ravel()):
                while alias[a] != a:
                    alias[a] = alias[alias[a]]
                    a = alias[a]
                while alias[b] != b:
                    alias[b] = alias[alias[b]]
                    b = alias[b]
                alias[max(a, b)] = min(a, b)
        while not np.array_equal(alias, alias[alias]):
            alias = alias[alias]
    for b in mesh.continuum_blocks():
        nc = 4 if b.etype in (ElemType.Q4, ElemType.Q8) else 3
        quad = b.etype in (ElemType.T6, ElemType.Q8)
        for i in range(nc):
            a, c = alias[b.conn[:, i]], alias[b.conn[:, (i + 1) % nc]]
            keys.append(np.minimum(a, c) * nn + np.maximum(a, c))
            mids.append(alias[b.conn[:, nc + i]] if quad else np.full(b.ne, -1))
    if not keys:
        return np.empty(0, dtype=np.int64)
    k = np.concatenate(keys)
    m = np.concatenate(mids)
    u, inv, cnt = np.unique(k, return_inverse=True, return_counts=True)
    once = cnt[inv.ravel()] == 1
    nodes = np.concatenate([k[once] // nn, k[once] % nn, m[once][m[once] >= 0]])
    return np.flatnonzero(np.isin(alias, nodes)) if join_interfaces else np.unique(nodes)

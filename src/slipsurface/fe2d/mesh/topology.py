"""Continuum boundary topology shared by meshing and post-processing (L2)."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from ..core.enums import ElemType
from ..model.mesh import Mesh


def boundary_nodes(mesh: Mesh) -> NDArray[np.int64]:
    """Nodes on the outer boundary of the continuum mesh (edges used by one element)."""
    keys, mids = [], []
    nn = mesh.nn
    for b in mesh.continuum_blocks():
        nc = 4 if b.etype in (ElemType.Q4, ElemType.Q8) else 3
        quad = b.etype in (ElemType.T6, ElemType.Q8)
        for i in range(nc):
            a, c = b.conn[:, i], b.conn[:, (i + 1) % nc]
            keys.append(np.minimum(a, c) * nn + np.maximum(a, c))
            mids.append(b.conn[:, nc + i] if quad else np.full(b.ne, -1))
    k = np.concatenate(keys)
    m = np.concatenate(mids)
    u, inv, cnt = np.unique(k, return_inverse=True, return_counts=True)
    once = cnt[inv.ravel()] == 1
    nodes = np.concatenate([k[once] // nn, k[once] % nn, m[once][m[once] >= 0]])
    return np.unique(nodes)

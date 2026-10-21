"""Shared test helpers."""

from __future__ import annotations

import numpy as np
import pytest

from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.model import Displacement, ElementBlock, Mesh


def distort(mesh: Mesh, amount: float, seed: int = 0) -> Mesh:
    """Randomly move interior corner nodes; T6 mid-nodes are reset to straight midpoints."""
    rng = np.random.default_rng(seed)
    blk = mesh.blocks[0]
    coords = mesh.coords.copy()
    boundary = np.unique(np.concatenate([v for k, v in mesh.node_sets.items() if k != "all"]))
    corners = np.unique(blk.conn[:, :3])
    interior = np.setdiff1d(corners, boundary)
    coords[interior] += amount * rng.uniform(-1, 1, (interior.size, 2))
    if blk.etype is ElemType.T6:
        c = blk.conn
        for m, (a, b) in zip((3, 4, 5), ((0, 1), (1, 2), (2, 0))):
            coords[c[:, m]] = 0.5 * (coords[c[:, a]] + coords[c[:, b]])
    return Mesh(
        coords,
        (ElementBlock(blk.etype, blk.conn, blk.region, blk.tag),),
        mesh.node_sets,
        mesh.edge_sets,
    )


def per_node_displacements(mesh: Mesh, nodes, field) -> tuple[Mesh, tuple[Displacement, ...]]:
    """Add one node set per node and a Displacement BC with ``field(x, y) -> (ux, uy)``."""
    ns = dict(mesh.node_sets)
    bcs = []
    for n in np.asarray(nodes):
        name = f"_p{int(n)}"
        ns[name] = np.array([n])
        ux, uy = field(*mesh.coords[n])
        bcs.append(Displacement(name, float(ux), float(uy)))
    return Mesh(mesh.coords, mesh.blocks, ns, mesh.edge_sets), tuple(bcs)


def rel_err(a, b) -> float:
    a, b = np.asarray(a), np.asarray(b)
    return float(np.max(np.abs(a - b)) / np.max(np.abs(b)))


@pytest.fixture
def rng():
    return np.random.default_rng(1234)

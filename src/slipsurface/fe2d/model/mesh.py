"""Mesh data structure (L1).

The mesh is pure data: one contiguous coordinate array plus element blocks. Mesh
*generation* lives in L2 (:mod:`slipsurface.fe2d.mesh`); this module only defines and
validates the container so that every layer above can rely on its invariants.

Node ordering conventions
-------------------------
* T3: corners counter-clockwise.
* T6: corners 0-1-2 counter-clockwise, then mid-side nodes 3 (0-1), 4 (1-2), 5 (2-0).
* Edge sets: rows of ``nodes_per_edge`` node ids; for quadratic edges ``[end_a, end_b, mid]``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from ..core.enums import ElemType
from ..core.errors import MeshError


@dataclass(frozen=True, eq=False)
class ElementBlock:
    etype: ElemType
    conn: NDArray[np.int64]  # (ne, nen)
    region: NDArray[np.int32]  # (ne,) region id -> material
    tag: str = "soil"

    def __post_init__(self) -> None:
        conn = np.ascontiguousarray(self.conn, dtype=np.int64)
        region = np.ascontiguousarray(self.region, dtype=np.int32)
        if conn.ndim != 2 or conn.shape[1] != self.etype.nen:
            raise MeshError(
                f"block '{self.tag}': conn shape {conn.shape} does not match "
                f"{self.etype.name} ({self.etype.nen} nodes)"
            )
        if region.shape != (conn.shape[0],):
            raise MeshError(f"block '{self.tag}': region must have shape ({conn.shape[0]},)")
        object.__setattr__(self, "conn", conn)
        object.__setattr__(self, "region", region)

    @property
    def ne(self) -> int:
        return int(self.conn.shape[0])


@dataclass(frozen=True, eq=False)
class Mesh:
    coords: NDArray[np.float64]  # (nn, 2)
    blocks: tuple[ElementBlock, ...]
    node_sets: dict[str, NDArray[np.int64]] = field(default_factory=dict)
    edge_sets: dict[str, NDArray[np.int64]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        coords = np.ascontiguousarray(self.coords, dtype=np.float64)
        if coords.ndim != 2 or coords.shape[1] != 2:
            raise MeshError(f"coords must have shape (nn, 2), got {coords.shape}")
        object.__setattr__(self, "coords", coords)
        object.__setattr__(self, "blocks", tuple(self.blocks))
        object.__setattr__(
            self, "node_sets", {k: np.asarray(v, dtype=np.int64) for k, v in self.node_sets.items()}
        )
        object.__setattr__(
            self,
            "edge_sets",
            {k: np.atleast_2d(np.asarray(v, dtype=np.int64)) for k, v in self.edge_sets.items()},
        )
        self.validate()

    # ------------------------------------------------------------------ queries
    @property
    def nn(self) -> int:
        return int(self.coords.shape[0])

    def block(self, tag: str) -> ElementBlock:
        for b in self.blocks:
            if b.tag == tag:
                return b
        raise MeshError(f"no element block with tag '{tag}'")

    def continuum_blocks(self) -> tuple[ElementBlock, ...]:
        return tuple(
            b
            for b in self.blocks
            if b.etype in (ElemType.T3, ElemType.T6, ElemType.Q4, ElemType.Q8)
        )

    def regions(self) -> frozenset[int]:
        out: set[int] = set()
        for b in self.continuum_blocks():
            out.update(int(r) for r in np.unique(b.region))
        return frozenset(out)

    def nodes(self, name: str) -> NDArray[np.int64]:
        try:
            return self.node_sets[name]
        except KeyError:
            raise MeshError(f"unknown node set '{name}'") from None

    def edges(self, name: str) -> NDArray[np.int64]:
        try:
            return self.edge_sets[name]
        except KeyError:
            raise MeshError(f"unknown edge set '{name}'") from None

    # --------------------------------------------------------------- validation
    def validate(self) -> None:
        nn = self.nn
        for b in self.blocks:
            if b.ne and (b.conn.min() < 0 or b.conn.max() >= nn):
                raise MeshError(f"block '{b.tag}': node index out of range [0, {nn})")
            if b.etype in (ElemType.T3, ElemType.T6) and b.ne:
                x = self.coords[b.conn[:, :3]]
                a2 = (x[:, 1, 0] - x[:, 0, 0]) * (x[:, 2, 1] - x[:, 0, 1]) - (
                    x[:, 2, 0] - x[:, 0, 0]
                ) * (x[:, 1, 1] - x[:, 0, 1])
                bad = np.flatnonzero(a2 <= 0.0)
                if bad.size:
                    raise MeshError(
                        f"block '{b.tag}': {bad.size} element(s) with non-positive area "
                        f"(clockwise or degenerate), first index {int(bad[0])}"
                    )
        for name, ids in self.node_sets.items():
            if ids.size and (ids.min() < 0 or ids.max() >= nn):
                raise MeshError(f"node set '{name}' has out-of-range ids")
        for name, e in self.edge_sets.items():
            if e.size and (e.min() < 0 or e.max() >= nn):
                raise MeshError(f"edge set '{name}' has out-of-range ids")

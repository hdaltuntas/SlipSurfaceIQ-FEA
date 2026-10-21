"""Element size fields for the unstructured mesher.

A size field is any vectorised callable ``h(x, y) -> size``. :class:`DistanceSize` grades
the mesh away from polylines/points (excavation contours, footing edges, wall lines):

    h(d) = min(h_max, h_min + (growth - 1) * d)

where ``d`` is the distance to the nearest source. ``growth`` ≈ 1.2–1.5 keeps the size
change between neighbouring elements smooth.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from ..core.errors import MeshError


@dataclass(frozen=True, eq=False)
class DistanceSize:
    h_min: float
    h_max: float
    growth: float = 1.3
    lines: Sequence[NDArray[np.float64]] = field(default_factory=tuple)
    points: NDArray[np.float64] | None = None
    closed: Sequence[bool] | None = None  # per line: treat as closed polygon

    def __post_init__(self) -> None:
        if not 0 < self.h_min <= self.h_max:
            raise MeshError("need 0 < h_min <= h_max")
        if self.growth < 1.0:
            raise MeshError("growth must be >= 1")
        segs = []
        closed = self.closed or [False] * len(self.lines)
        for ln, cl in zip(self.lines, closed):
            p = np.asarray(ln, dtype=float)
            if cl:
                p = np.vstack([p, p[:1]])
            segs.append(np.stack([p[:-1], p[1:]], axis=1))
        object.__setattr__(self, "_segs", np.concatenate(segs) if segs else np.empty((0, 2, 2)))
        pts = np.empty((0, 2)) if self.points is None else np.atleast_2d(self.points)
        object.__setattr__(self, "_pts", np.asarray(pts, dtype=float))
        if self._segs.shape[0] == 0 and self._pts.shape[0] == 0:  # type: ignore[attr-defined]
            raise MeshError("DistanceSize needs at least one line or point")

    def distance(self, x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float64]:
        q = np.column_stack([np.ravel(x), np.ravel(y)])
        d = np.full(q.shape[0], np.inf)
        segs: NDArray = self._segs  # type: ignore[attr-defined]
        pts: NDArray = self._pts  # type: ignore[attr-defined]
        for i0 in range(0, q.shape[0], 4096):
            qq = q[i0 : i0 + 4096]
            if segs.shape[0]:
                a, b = segs[:, 0], segs[:, 1]
                ab = b - a
                L2 = np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-300)
                rel = qq[:, None, :] - a[None]
                t = np.clip(np.einsum("qsj,sj->qs", rel, ab) / L2, 0.0, 1.0)
                diff = rel - t[..., None] * ab[None]
                d[i0 : i0 + 4096] = np.sqrt(np.einsum("qsj,qsj->qs", diff, diff).min(axis=1))
            if pts.shape[0]:
                dp = np.linalg.norm(qq[:, None, :] - pts[None], axis=2).min(axis=1)
                d[i0 : i0 + 4096] = np.minimum(d[i0 : i0 + 4096], dp)
        return d.reshape(np.shape(x))

    def __call__(self, x: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float64]:
        d = self.distance(x, y)
        return np.minimum(self.h_max, self.h_min + (self.growth - 1.0) * d)


_Fn = Callable[[NDArray, NDArray], NDArray]


def min_size(*fields: _Fn) -> _Fn:
    """Combine several size fields (pointwise minimum)."""

    def fn(x: NDArray, y: NDArray) -> NDArray:
        out = np.asarray(fields[0](x, y), dtype=float)
        for f in fields[1:]:
            out = np.minimum(out, f(x, y))
        return out

    return fn

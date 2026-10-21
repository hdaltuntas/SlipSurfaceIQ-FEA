"""Planar straight-line graph (PSLG) input for the unstructured mesher.

A :class:`Domain` collects polygons (material regions, holes), embedded polylines
(liner / bolt / query lines) and named points. :meth:`Domain.build` cleans the input into a
:class:`PSLG`:

* coincident vertices are merged (tolerance ``tol``),
* segments are split at proper crossings and at vertices lying on them,
* duplicate segments (e.g. the shared edge of two layers) are merged; their names,
  barrier flags and target sizes are combined.

Region assignment does not need seed points: after triangulation every connected patch
of triangles (separated by polygon edges) is given the region of the *innermost* polygon
that contains it. Explicit seeds (:meth:`Domain.add_seed`) override this.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import cKDTree

from ..core.errors import MeshError

ArrayLike2 = NDArray[np.float64] | list[tuple[float, float]] | list[list[float]]


@dataclass(frozen=True, eq=False)
class PolygonSpec:
    coords: NDArray[np.float64]  # (n, 2), closed implicitly
    region: int
    hole: bool
    max_area: float | None
    area: float


@dataclass(frozen=True)
class SeedSpec:
    x: float
    y: float
    region: int  # 0 -> hole
    max_area: float | None = None


@dataclass(frozen=True, eq=False)
class PSLG:
    """Cleaned input: vertices, segments and their attributes."""

    verts: NDArray[np.float64]  # (nv, 2)
    segs: NDArray[np.int64]  # (ns, 2)
    barrier: NDArray[np.bool_]  # (ns,) True: separates regions (polygon edges)
    seg_h: NDArray[np.float64]  # (ns,) target subsegment length (inf = none)
    seg_names: dict[str, NDArray[np.int64]]  # name -> segment ids
    seg_sign: dict[str, NDArray[np.int8]]  # name -> +1/-1: segment direction vs that input
    point_names: dict[str, int]  # name -> vertex id
    polygons: tuple[PolygonSpec, ...]
    seeds: tuple[SeedSpec, ...]
    tol: float


@dataclass
class _RawSeg:
    a: tuple[float, float]
    b: tuple[float, float]
    barrier: bool
    h: float
    names: frozenset[str]


@dataclass
class Domain:
    """Mesher input builder.

    Example::

        d = Domain()
        d.add_polygon([(0, -20), (40, -20), (40, 0), (0, 0)], region=1,
                      edge_names=["bottom", "right", "top", "left"])
        d.add_polygon([(0, -5), (40, -5), (40, 0), (0, 0)], region=2)   # top layer
        d.add_polygon(circle(20, -10, 3), hole=True, name="tunnel", h=0.3)
        d.add_line([(10, 0), (10, -8)], name="wall")
    """

    tol: float | None = None
    _segs: list[_RawSeg] = field(default_factory=list)
    _points: list[tuple[float, float, str | None]] = field(default_factory=list)
    _polys: list[tuple[NDArray[np.float64], int, bool, float | None]] = field(default_factory=list)
    _seeds: list[SeedSpec] = field(default_factory=list)

    # ------------------------------------------------------------------ builders
    def add_polygon(
        self,
        points: ArrayLike2,
        region: int = 1,
        *,
        hole: bool = False,
        name: str | None = None,
        edge_names: list[str | None] | None = None,
        max_area: float | None = None,
        h: float | None = None,
    ) -> Domain:
        """Closed polygon. Its edges always separate regions.

        ``name`` creates an edge/node set for the whole boundary, ``edge_names[i]`` one for
        edge ``i`` (from ``points[i]`` to ``points[i+1]``). ``h`` is a target edge length
        along the boundary; ``max_area`` limits triangle area inside the polygon.
        """
        p = _as_points(points)
        if p.shape[0] >= 2 and np.allclose(p[0], p[-1]):
            p = p[:-1]
        if p.shape[0] < 3:
            raise MeshError("a polygon needs at least 3 distinct vertices")
        if edge_names is not None and len(edge_names) != p.shape[0]:
            raise MeshError(f"edge_names needs {p.shape[0]} entries, got {len(edge_names)}")
        if abs(_signed_area(p)) <= 0.0:
            raise MeshError("degenerate polygon (zero area)")
        n = p.shape[0]
        for i in range(n):
            names = {name} if name else set()
            if edge_names is not None and edge_names[i]:
                names.add(edge_names[i])  # type: ignore[arg-type]
            self._add_seg(p[i], p[(i + 1) % n], True, h, frozenset(names))
        self._polys.append((p, int(region), bool(hole), max_area))
        return self

    def add_line(
        self, points: ArrayLike2, name: str | None = None, *, h: float | None = None
    ) -> Domain:
        """Embedded polyline (liner, bolt, query line, material-free constraint).

        Its edges become mesh edges but do not split regions.
        """
        p = _as_points(points)
        if p.shape[0] < 2:
            raise MeshError("a line needs at least 2 points")
        names = frozenset({name}) if name else frozenset()
        for i in range(p.shape[0] - 1):
            self._add_seg(p[i], p[i + 1], False, h, names)
        return self

    def add_point(self, x: float, y: float, name: str | None = None) -> Domain:
        """Mesh vertex at (x, y); ``name`` creates a one-node node set."""
        self._points.append((float(x), float(y), name))
        return self

    def add_seed(self, x: float, y: float, region: int, max_area: float | None = None) -> Domain:
        """Explicit region seed (``region=0`` marks a hole); overrides polygon labels."""
        self._seeds.append(SeedSpec(float(x), float(y), int(region), max_area))
        return self

    def _add_seg(
        self, a: NDArray, b: NDArray, barrier: bool, h: float | None, names: frozenset[str]
    ) -> None:
        if h is not None and h <= 0:
            raise MeshError("h must be positive")
        self._segs.append(
            _RawSeg(
                (float(a[0]), float(a[1])),
                (float(b[0]), float(b[1])),
                barrier,
                float(h) if h is not None else np.inf,
                names,
            )
        )

    # --------------------------------------------------------------------- build
    def build(self) -> PSLG:
        if not self._polys and not self._seeds:
            raise MeshError("domain has no polygon")
        pts = [s.a for s in self._segs] + [s.b for s in self._segs]
        pts += [(x, y) for x, y, _ in self._points]
        allp = np.asarray(pts, dtype=float)
        diag = float(np.linalg.norm(allp.max(axis=0) - allp.min(axis=0)))
        if diag <= 0:
            raise MeshError("domain has zero extent")
        tol = self.tol if self.tol is not None else 1e-9 * diag

        verts, vid = _snap(allp, tol)
        ns_raw = len(self._segs)
        segs = np.column_stack([vid[:ns_raw], vid[ns_raw : 2 * ns_raw]]).astype(np.int64)
        point_ids = vid[2 * ns_raw :]
        barrier = np.array([s.barrier for s in self._segs], dtype=bool)
        seg_h = np.array([s.h for s in self._segs], dtype=float)
        names: list[frozenset[str]] = [s.names for s in self._segs]

        keep = segs[:, 0] != segs[:, 1]
        segs, barrier, seg_h = segs[keep], barrier[keep], seg_h[keep]
        names = [n for n, k in zip(names, keep) if k]

        for _ in range(8):
            verts, segs, barrier, seg_h, names, changed = _split_pass(
                verts, segs, barrier, seg_h, names, tol
            )
            if not changed:
                break
        else:
            raise MeshError("PSLG cleaning did not converge (pathological input?)")

        segs, barrier, seg_h, names = _merge_duplicates(segs, barrier, seg_h, names)

        seg_names: dict[str, list[int]] = {}
        seg_sign: dict[str, list[int]] = {}
        for i, nm in enumerate(names):
            for n, sg in nm.items():  # type: ignore[attr-defined]
                seg_names.setdefault(n, []).append(i)
                seg_sign.setdefault(n, []).append(sg)
        point_names = {nm: int(point_ids[i]) for i, (_, _, nm) in enumerate(self._points) if nm}
        polygons = tuple(
            PolygonSpec(p, r, hl, ma, abs(_signed_area(p))) for p, r, hl, ma in self._polys
        )
        return PSLG(
            verts=verts,
            segs=segs,
            barrier=barrier,
            seg_h=seg_h,
            seg_names={k: np.asarray(v, dtype=np.int64) for k, v in seg_names.items()},
            seg_sign={k: np.asarray(v, dtype=np.int8) for k, v in seg_sign.items()},
            point_names=point_names,
            polygons=polygons,
            seeds=tuple(self._seeds),
            tol=tol,
        )


# ============================================================================ helpers
def circle(xc: float, yc: float, r: float, n: int = 48) -> NDArray[np.float64]:
    """Counter-clockwise polygon approximating a circle (for tunnels, piles, ...)."""
    t = np.linspace(0.0, 2 * np.pi, n, endpoint=False)
    return np.column_stack([xc + r * np.cos(t), yc + r * np.sin(t)])


def arc(
    xc: float, yc: float, r: float, theta0: float, theta1: float, n: int = 24
) -> NDArray[np.float64]:
    """Polyline on a circular arc from ``theta0`` to ``theta1`` (radians), n segments."""
    t = np.linspace(theta0, theta1, n + 1)
    return np.column_stack([xc + r * np.cos(t), yc + r * np.sin(t)])


def _as_points(points: ArrayLike2) -> NDArray[np.float64]:
    p = np.asarray(points, dtype=float)
    if p.ndim != 2 or p.shape[1] != 2:
        raise MeshError(f"points must have shape (n, 2), got {p.shape}")
    if not np.all(np.isfinite(p)):
        raise MeshError("non-finite coordinates")
    return p


def _signed_area(p: NDArray[np.float64]) -> float:
    x, y = p[:, 0], p[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y))


def point_in_polygon(pts: NDArray[np.float64], poly: NDArray[np.float64]) -> NDArray[np.bool_]:
    """Even-odd ray casting, vectorised over ``pts`` (points on the boundary: undefined)."""
    x, y = pts[:, 0][:, None], pts[:, 1][:, None]
    x1, y1 = poly[:, 0][None, :], poly[:, 1][None, :]
    x2, y2 = np.roll(poly[:, 0], -1)[None, :], np.roll(poly[:, 1], -1)[None, :]
    cond = (y1 > y) != (y2 > y)
    with np.errstate(divide="ignore", invalid="ignore"):
        xint = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
    return np.asarray((cond & (x < xint)).sum(axis=1) % 2 == 1)


def _snap(p: NDArray[np.float64], tol: float) -> tuple[NDArray[np.float64], NDArray[np.int64]]:
    """Merge points closer than ``tol``; returns unique points and the index map."""
    n = p.shape[0]
    parent = np.arange(n)
    pairs = cKDTree(p).query_pairs(tol, output_type="ndarray")

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j in pairs:
        ri, rj = find(int(i)), find(int(j))
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)
    root = np.array([find(i) for i in range(n)])
    uniq, inv = np.unique(root, return_inverse=True)
    return p[uniq].copy(), inv.ravel().astype(np.int64)


def _split_pass(
    verts: NDArray[np.float64],
    segs: NDArray[np.int64],
    barrier: NDArray[np.bool_],
    seg_h: NDArray[np.float64],
    names: list[frozenset[str]],
    tol: float,
) -> tuple[NDArray, NDArray, NDArray, NDArray, list[frozenset[str]], bool]:
    """Split segments at crossings and at vertices lying on them (one pass)."""
    A, B = verts[segs[:, 0]], verts[segs[:, 1]]
    D = B - A
    L2 = np.einsum("ij,ij->i", D, D)
    ns = segs.shape[0]
    splits: list[list[tuple[float, int]]] = [[] for _ in range(ns)]
    new_pts: list[NDArray[np.float64]] = []
    nv = verts.shape[0]

    # (a) vertices on segment interiors
    for i0 in range(0, ns, 512):
        sl = slice(i0, min(i0 + 512, ns))
        rel = verts[None, :, :] - A[sl, None, :]  # (s, v, 2)
        t = np.einsum("svj,sj->sv", rel, D[sl]) / L2[sl, None]
        cross = rel[..., 0] * D[sl, None, 1] - rel[..., 1] * D[sl, None, 0]
        dist = np.abs(cross) / np.sqrt(L2[sl, None])
        L = np.sqrt(L2[sl, None])
        on = (dist < tol) & (t * L > tol) & ((1 - t) * L > tol)
        si, vi = np.nonzero(on)
        for s, v in zip(si + i0, vi):
            splits[s].append((float(t[s - i0, v]), int(v)))

    # (b) proper crossings
    for i0 in range(0, ns, 512):
        sl = slice(i0, min(i0 + 512, ns))
        r = D[sl, None, :]
        s_ = D[None, :, :]
        qp = A[None, :, :] - A[sl, None, :]
        rxs = r[..., 0] * s_[..., 1] - r[..., 1] * s_[..., 0]
        with np.errstate(divide="ignore", invalid="ignore"):
            t = (qp[..., 0] * s_[..., 1] - qp[..., 1] * s_[..., 0]) / rxs
            u = (qp[..., 0] * r[..., 1] - qp[..., 1] * r[..., 0]) / rxs
        La = np.sqrt(L2[sl, None])
        Lb = np.sqrt(L2[None, :])
        ok = (
            (np.abs(rxs) > 1e-14 * La * Lb)
            & (t * La > tol)
            & ((1 - t) * La > tol)
            & (u * Lb > tol)
            & ((1 - u) * Lb > tol)
        )
        si, sj = np.nonzero(ok)
        keep = si + i0 < sj  # each pair once
        for a_, b_ in zip(si[keep] + i0, sj[keep]):
            ta = float(t[a_ - i0, b_])
            ub = float(u[a_ - i0, b_])
            x = A[a_] + ta * D[a_]
            vid = nv + len(new_pts)
            new_pts.append(x)
            splits[a_].append((ta, vid))
            splits[b_].append((ub, vid))

    if not any(splits):
        return verts, segs, barrier, seg_h, names, False

    if new_pts:
        allv = np.vstack([verts, np.asarray(new_pts)])
        allv, vmap = _snap(allv, tol)
    else:
        allv, vmap = verts, np.arange(nv, dtype=np.int64)

    out_s, out_b, out_h, out_n = [], [], [], []
    for i in range(ns):
        chain = [int(vmap[segs[i, 0]])]
        for _, v in sorted(splits[i]):
            vv = int(vmap[v])
            if vv != chain[-1]:
                chain.append(vv)
        end = int(vmap[segs[i, 1]])
        if end != chain[-1]:
            chain.append(end)
        for a_, b_ in zip(chain[:-1], chain[1:]):
            if a_ != b_:
                out_s.append((a_, b_))
                out_b.append(barrier[i])
                out_h.append(seg_h[i])
                out_n.append(names[i])
    return (
        allv,
        np.asarray(out_s, dtype=np.int64),
        np.asarray(out_b, dtype=bool),
        np.asarray(out_h, dtype=float),
        out_n,
        True,
    )


def _merge_duplicates(
    segs: NDArray[np.int64],
    barrier: NDArray[np.bool_],
    seg_h: NDArray[np.float64],
    names: list[frozenset[str]],
) -> tuple[NDArray, NDArray, NDArray, list[dict[str, int]]]:
    """Merge coincident segments; each name keeps the direction of *its* input segment
    (``+1`` if the merged segment has the same direction, ``-1`` otherwise)."""
    key = np.sort(segs, axis=1)
    uniq, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    inv = inv.ravel()
    order = np.argsort(first)  # keep input order (and input orientation)
    rank = np.empty_like(order)
    rank[order] = np.arange(order.size)
    m = uniq.shape[0]
    out_s = segs[first[order]]
    out_b = np.zeros(m, dtype=bool)
    out_h = np.full(m, np.inf)
    out_n: list[dict[str, int]] = [{} for _ in range(m)]
    for i, g in enumerate(rank[inv]):
        out_b[g] |= barrier[i]
        out_h[g] = min(out_h[g], seg_h[i])
        sgn = 1 if segs[i, 0] == out_s[g, 0] else -1
        for n in names[i]:
            out_n[g].setdefault(n, sgn)
    return out_s, out_b, out_h, out_n

"""Unstructured triangular mesher: conforming Delaunay + Ruppert refinement.

Algorithm (written for this package; only the plain Delaunay triangulation comes from
``scipy.spatial.Delaunay``/Qhull):

1. **Segment recovery** — every input segment is split until each subsegment is an edge
   of the Delaunay triangulation and its diametral circle is empty (Gabriel property).
   Subsegments touching an input vertex are split on concentric power-of-two shells
   (Shewchuk), which stops the classic small-angle ping-pong of Ruppert's algorithm.
2. **Region labelling** — triangles are grouped into patches separated by polygon edges
   (graph connected components); each patch takes the region of the innermost polygon
   containing it, holes and the exterior are dropped.
3. **Ruppert refinement** — triangles in the domain whose radius–edge ratio exceeds
   ``1 / (2 sin θ_min)`` or that are larger than the size field are refined by inserting
   their circumcentre; a circumcentre that encroaches a subsegment is rejected and the
   subsegment is split instead. Insertions are done in batches (one Qhull call per
   round), with a spacing filter so that nearby candidates do not create short edges.
   Bad triangles whose smallest angle is a small input angle bounded by two segments
   cannot be improved and are left alone.
4. **Output** — CCW T3 connectivity, optional straight-sided T6 mid-side nodes, region ids,
   edge/node sets for every named polygon edge / line and node sets for named points,
   plus ``boundary`` and ``all``.

Because the result is a *conforming* Delaunay mesh, every input segment is a chain of
mesh edges (needed for embedded liners/bolts and for edge loads). Edge sets follow the
direction of the input polyline/polygon that defines the name, even where the segment
coincides with (and was merged into) a segment of another input.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components, reverse_cuthill_mckee
from scipy.spatial import Delaunay, cKDTree

from ..core.enums import ElemType
from ..core.errors import MeshError
from ..core.log import get_logger
from ..model.mesh import ElementBlock, Mesh
from .pslg import PSLG, Domain, point_in_polygon

log = get_logger("mesh")

SizeFn = Callable[[NDArray[np.float64], NDArray[np.float64]], NDArray[np.float64]]
_EXCLUDED = -1
_SQ3 = np.sqrt(3.0)


def unstructured_mesh(
    domain: Domain | PSLG,
    *,
    etype: ElemType = ElemType.T6,
    h: float | SizeFn | None = None,
    min_angle: float = 28.0,
    max_area: float | None = None,
    tag: str = "soil",
    max_points: int = 2_000_000,
    max_rounds: int = 1000,
    renumber: bool = True,
    checkpoint: Callable[[], None] | None = None,
) -> Mesh:
    """Generate a quality triangular mesh of ``domain``.

    Parameters
    ----------
    h:
        Target element size: a constant or ``h(x, y) -> size`` (vectorised), e.g. a
        :class:`~slipsurface.fe2d.mesh.sizing.DistanceSize` that grades the mesh towards
        an excavation contour. ``None`` → only quality refinement.
    min_angle:
        Minimum angle target in degrees (≤ 33.8; 28–30 is a good default). Input
        angles below it are preserved, not improved.
    max_area:
        Global area limit; polygons may set their own.
    renumber:
        Reverse Cuthill–McKee node numbering (smaller profile; the sparse direct
        solve is ~30 % faster than with insertion order).
    checkpoint:
        Optional callback between refinement rounds (e.g. cooperative cancellation).
    """
    if etype not in (ElemType.T3, ElemType.T6):
        raise MeshError("unstructured_mesh supports T3 and T6")
    if not 0.0 < min_angle <= 33.8:
        raise MeshError("min_angle must be in (0, 33.8] degrees")
    pslg = domain.build() if isinstance(domain, Domain) else domain
    hfun = _size_function(h)
    eng = _Refiner(pslg, hfun, min_angle, max_area, max_points)
    tri, label = eng.run(max_rounds, checkpoint)
    mesh = _assemble(eng, tri, label, etype, tag)
    return rcm_renumber(mesh) if renumber else mesh


def rcm_renumber(mesh: Mesh) -> Mesh:
    """Renumber nodes with reverse Cuthill–McKee on the element connectivity graph."""
    rows, cols = [], []
    for b in mesh.blocks:
        c = b.conn
        k = c.shape[1]
        rows.append(np.repeat(c, k, axis=1).ravel())
        cols.append(np.tile(c, (1, k)).ravel())
    r, c = np.concatenate(rows), np.concatenate(cols)
    graph = coo_matrix((np.ones(r.size, dtype=np.int8), (r, c)), shape=(mesh.nn, mesh.nn))
    perm = np.asarray(reverse_cuthill_mckee(graph.tocsr(), symmetric_mode=True), dtype=np.int64)
    inv = np.empty_like(perm)
    inv[perm] = np.arange(perm.size)
    return Mesh(
        mesh.coords[perm],
        tuple(ElementBlock(b.etype, inv[b.conn], b.region, b.tag) for b in mesh.blocks),
        {k: inv[v] for k, v in mesh.node_sets.items()},
        {k: inv[v] for k, v in mesh.edge_sets.items()},
    )


# ===================================================================== refinement
class _Refiner:
    def __init__(
        self,
        pslg: PSLG,
        hfun: SizeFn | None,
        min_angle: float,
        max_area: float | None,
        max_points: int,
    ) -> None:
        self.g = pslg
        self.hfun = hfun
        self.ratio_lim = 1.0 / (2.0 * np.sin(np.radians(min_angle)))
        self.max_area = np.inf if max_area is None else float(max_area)
        self.max_points = max_points
        self.P = pslg.verts.copy()
        self.n_input = self.P.shape[0]
        self.S = pslg.segs.copy()  # current subsegments
        self.S_base = np.arange(self.S.shape[0])  # parent input segment
        self.sharp_angle = self._sharp_angles()  # smallest input angle (rad), inf if none
        self.sharp = self.sharp_angle < np.radians(60.0) - 1e-9
        # input segments that bound a small input angle ("clusters")
        self.cluster_seg = self.sharp[self.S[:, 0]] | self.sharp[self.S[:, 1]]
        diag = float(np.linalg.norm(self.P.max(axis=0) - self.P.min(axis=0)))
        self.l_floor = 1e-9 * diag
        self.rounds = 0
        self.exempt_all = False

    # ------------------------------------------------------------ input analysis
    def _sharp_angles(self) -> NDArray[np.float64]:
        """Smallest angle between consecutive input segments at each input vertex."""
        out = np.full(self.n_input, np.inf)
        segs = self.g.segs
        if segs.size == 0:
            return out
        ends = np.concatenate([segs[:, 0], segs[:, 1]])
        other = np.concatenate([segs[:, 1], segs[:, 0]])
        d = self.P[other] - self.P[ends]
        ang = np.arctan2(d[:, 1], d[:, 0])
        order = np.lexsort((ang, ends))
        ends, ang = ends[order], ang[order]
        starts = np.flatnonzero(np.r_[True, ends[1:] != ends[:-1]])
        stops = np.r_[starts[1:], ends.size]
        for s, e in zip(starts, stops):
            if e - s < 2:
                continue
            a = ang[s:e]
            out[ends[s]] = float(np.diff(np.r_[a, a[0] + 2 * np.pi]).min())
        return out

    def _cluster_insertion_radius(self, sid: NDArray[np.int64]) -> NDArray[np.float64]:
        """Insertion radius of the vertex that splitting cluster subsegments would create.

        The matching subsegments of the other cluster segments are split on the same
        shell, so the new vertex ends up ``2 rho sin(phi/2)`` from its neighbour, where
        ``rho`` is the distance to the sharp apex and ``phi`` the apex angle.
        """
        _, mid, half = self._seg_geometry()
        base = self.g.segs[self.S_base[sid]]
        pa, pb = self.P[base[:, 0]], self.P[base[:, 1]]
        da = np.linalg.norm(mid[sid] - pa, axis=1)
        db = np.linalg.norm(mid[sid] - pb, axis=1)
        ra = np.where(self.sharp[base[:, 0]], da, np.inf)
        rb = np.where(self.sharp[base[:, 1]], db, np.inf)
        use_a = ra <= rb
        rho = np.where(use_a, ra, rb)
        phi = np.where(use_a, self.sharp_angle[base[:, 0]], self.sharp_angle[base[:, 1]])
        return np.minimum(half[sid], 2.0 * rho * np.sin(0.5 * np.minimum(phi, np.pi)))

    # ------------------------------------------------------------- main loop
    def run(self, max_rounds: int, checkpoint=None) -> tuple[Delaunay, NDArray[np.int64]]:
        for _ in range(max_rounds):
            if checkpoint is not None:
                checkpoint()
            self.rounds += 1
            if self.P.shape[0] > self.max_points:
                raise MeshError(
                    f"mesher exceeded max_points={self.max_points}; "
                    "check h / max_area or very small input features"
                )
            tri = Delaunay(self.P)
            simp = tri.simplices
            edge_keys = self._edge_keys(simp)

            # 1) subsegments: missing, encroached or too long -> split
            seg_split = self._subsegments_to_split(edge_keys)
            if seg_split.size:
                self._split_subsegments(seg_split)
                continue

            # 2) labels and 3) bad / big triangles
            label, tri_maxA = self._label(tri)
            cand, prio, qual_only, lmin = self._bad_triangles(simp, label, tri_maxA)
            if cand.size == 0 or self.exempt_all:
                log.info(
                    "unstructured mesh: %d rounds, %d vertices, %d triangles in domain",
                    self.rounds,
                    self.P.shape[0],
                    int((label != _EXCLUDED).sum()),
                )
                return tri, label
            self._insert_circumcentres(tri, label, cand, prio, qual_only, lmin)
        raise MeshError(f"mesher did not finish in {max_rounds} rounds")

    # ------------------------------------------------------------- utilities
    def _key(self, a: NDArray[np.int64], b: NDArray[np.int64]) -> NDArray[np.int64]:
        n = np.int64(self.P.shape[0])
        return np.minimum(a, b).astype(np.int64) * n + np.maximum(a, b)

    def _edge_keys(self, simp: NDArray) -> NDArray[np.int64]:
        k = np.concatenate([self._key(simp[:, i], simp[:, (i + 1) % 3]) for i in range(3)])
        return np.unique(k)

    def _seg_geometry(self) -> tuple[NDArray, NDArray, NDArray]:
        A, B = self.P[self.S[:, 0]], self.P[self.S[:, 1]]
        mid = 0.5 * (A + B)
        half = 0.5 * np.linalg.norm(B - A, axis=1)
        return A, mid, half

    def _encroached_by(
        self, pts: NDArray[np.float64], exclude_endpoints: bool
    ) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
        """Pairs (subsegment, point) with the point strictly inside the diametral circle."""
        if self.S.shape[0] == 0 or pts.shape[0] == 0:
            e = np.empty(0, dtype=np.int64)
            return e, e
        _, mid, half = self._seg_geometry()
        tree = cKDTree(pts)
        hits = tree.query_ball_point(mid, r=half)
        lens = np.fromiter((len(x) for x in hits), dtype=np.int64, count=len(hits))
        if lens.sum() == 0:
            e = np.empty(0, dtype=np.int64)
            return e, e
        sid = np.repeat(np.arange(self.S.shape[0]), lens)
        pid = np.fromiter((j for x in hits for j in x), dtype=np.int64, count=int(lens.sum()))
        d = np.linalg.norm(pts[pid] - mid[sid], axis=1)
        ok = d < half[sid] * (1.0 - 1e-9)
        if exclude_endpoints:
            ok &= (pid != self.S[sid, 0]) & (pid != self.S[sid, 1])
        return sid[ok], pid[ok]

    def _subsegments_to_split(self, edge_keys: NDArray[np.int64]) -> NDArray[np.int64]:
        keys = self._key(self.S[:, 0], self.S[:, 1])
        missing = ~np.isin(keys, edge_keys, assume_unique=False)
        sid, _ = self._encroached_by(self.P, exclude_endpoints=True)
        enc = np.zeros(self.S.shape[0], dtype=bool)
        enc[sid] = True
        _, mid, half = self._seg_geometry()
        target = self.g.seg_h[self.S_base].copy()
        if self.hfun is not None:
            target = np.minimum(target, self.hfun(mid[:, 0], mid[:, 1]))
        long_ = 2.0 * half > target
        split = (missing | enc | long_) & (2.0 * half > 2.0 * self.l_floor)
        return np.flatnonzero(split)

    def _split_subsegments(self, ids: NDArray[np.int64]) -> None:
        ids = np.unique(ids)
        a, b = self.S[ids, 0], self.S[ids, 1]
        A, B = self.P[a], self.P[b]
        L = np.linalg.norm(B - A, axis=1)
        a_in = a < self.n_input
        b_in = b < self.n_input
        t = np.full(ids.size, 0.5)
        # concentric shells around input vertices (distance = power of two)
        one = a_in ^ b_in
        if np.any(one):
            d = 2.0 ** np.round(np.log2(0.5 * L[one]))
            frac = np.clip(d / L[one], 0.25, 0.75)
            t[one] = np.where(a_in[one], frac, 1.0 - frac)
        newp = A + t[:, None] * (B - A)
        nid = np.arange(self.P.shape[0], self.P.shape[0] + ids.size)
        self.P = np.vstack([self.P, newp])
        keep = np.ones(self.S.shape[0], dtype=bool)
        keep[ids] = False
        self.S = np.vstack([self.S[keep], np.column_stack([a, nid]), np.column_stack([nid, b])])
        self.S_base = np.concatenate([self.S_base[keep], self.S_base[ids], self.S_base[ids]])

    # -------------------------------------------------------------- labelling
    def _label(self, tri: Delaunay) -> tuple[NDArray[np.int64], NDArray[np.float64]]:
        simp, nbr = tri.simplices, tri.neighbors
        nt = simp.shape[0]
        bar = self.S[self.g.barrier[self.S_base]]
        bkeys = np.unique(self._key(bar[:, 0], bar[:, 1])) if bar.size else np.empty(0, int)
        # edge opposite vertex j: (j+1, j+2)
        ok = np.empty((nt, 3), dtype=bool)
        for j in range(3):
            k = self._key(simp[:, (j + 1) % 3], simp[:, (j + 2) % 3])
            ok[:, j] = (nbr[:, j] >= 0) & ~np.isin(k, bkeys)
        rows = np.repeat(np.arange(nt), 3)[ok.ravel()]
        cols = nbr.ravel()[ok.ravel()]
        graph = coo_matrix((np.ones(rows.size), (rows, cols)), shape=(nt, nt))
        ncomp, comp = connected_components(graph, directed=False)

        X = self.P[simp]
        area = 0.5 * np.abs(
            (X[:, 1, 0] - X[:, 0, 0]) * (X[:, 2, 1] - X[:, 0, 1])
            - (X[:, 2, 0] - X[:, 0, 0]) * (X[:, 1, 1] - X[:, 0, 1])
        )
        cen = X.mean(axis=1)
        order = np.lexsort((-area, comp))
        _, first = np.unique(comp[order], return_index=True)
        rep = cen[order[first]]  # (ncomp, 2) a point well inside each patch

        comp_region = np.full(ncomp, _EXCLUDED, dtype=np.int64)
        comp_maxA = np.full(ncomp, np.inf)
        best_area = np.full(ncomp, np.inf)
        for poly in self.g.polygons:
            inside = point_in_polygon(rep, poly.coords) & (poly.area < best_area)
            best_area[inside] = poly.area
            comp_region[inside] = _EXCLUDED if poly.hole else poly.region
            comp_maxA[inside] = np.inf if poly.max_area is None else poly.max_area
        for sd in self.g.seeds:
            t = int(tri.find_simplex(np.array([[sd.x, sd.y]]))[0])
            if t < 0:
                continue
            c = comp[t]
            comp_region[c] = _EXCLUDED if sd.region == 0 else sd.region
            comp_maxA[c] = np.inf if sd.max_area is None else sd.max_area
        label = comp_region[comp]
        maxA = np.minimum(comp_maxA[comp], self.max_area)
        return label, maxA

    # -------------------------------------------------------------- triangles
    def _bad_triangles(
        self, simp: NDArray, label: NDArray[np.int64], maxA: NDArray[np.float64]
    ) -> tuple[NDArray[np.int64], NDArray[np.float64], NDArray[np.bool_], NDArray[np.float64]]:
        inside = np.flatnonzero(label != _EXCLUDED)
        if inside.size == 0:
            raise MeshError("no triangle lies inside the domain (check polygons / seeds)")
        s = simp[inside]
        X = self.P[s]
        e = np.stack(
            [
                np.linalg.norm(X[:, 2] - X[:, 1], axis=1),  # opposite v0
                np.linalg.norm(X[:, 0] - X[:, 2], axis=1),  # opposite v1
                np.linalg.norm(X[:, 1] - X[:, 0], axis=1),  # opposite v2
            ],
            axis=1,
        )
        area = 0.5 * np.abs(
            (X[:, 1, 0] - X[:, 0, 0]) * (X[:, 2, 1] - X[:, 0, 1])
            - (X[:, 2, 0] - X[:, 0, 0]) * (X[:, 1, 1] - X[:, 0, 1])
        )
        area = np.maximum(area, 1e-300)
        R = e.prod(axis=1) / (4.0 * area)
        jmin = e.argmin(axis=1)
        lmin = e[np.arange(s.shape[0]), jmin]
        ratio = R / lmin
        q_bad = ratio > self.ratio_lim * (1.0 + 1e-9)

        # unfixable: smallest angle is a sharp input corner bounded by two subsegments
        if q_bad.any():
            v = s[np.arange(s.shape[0]), jmin]
            v1 = s[np.arange(s.shape[0]), (jmin + 1) % 3]
            v2 = s[np.arange(s.shape[0]), (jmin + 2) % 3]
            skeys = self._key(self.S[:, 0], self.S[:, 1])
            corner = (v < self.n_input) & self.sharp[np.minimum(v, self.n_input - 1)]
            both = np.isin(self._key(v, v1), skeys) & np.isin(self._key(v, v2), skeys)
            q_bad &= ~(corner & both)
        q_bad &= lmin > self.l_floor

        size_ratio = area / maxA[inside]
        if self.hfun is not None:
            c = X.mean(axis=1)
            size_ratio = np.maximum(size_ratio, R * _SQ3 / self.hfun(c[:, 0], c[:, 1]))
        big = size_ratio > 1.0 + 1e-9
        sel = q_bad | big
        prio = np.maximum(np.where(q_bad, ratio / self.ratio_lim, 0.0), size_ratio)
        return inside[sel], prio[sel], (q_bad & ~big)[sel], lmin[sel]

    def _insert_circumcentres(
        self,
        tri: Delaunay,
        label: NDArray[np.int64],
        cand: NDArray[np.int64],
        prio: NDArray[np.float64],
        qual_only: NDArray[np.bool_],
        lmin: NDArray[np.float64],
    ) -> None:
        order = np.argsort(-prio, kind="stable")
        cand, qual_only, lmin = cand[order], qual_only[order], lmin[order]
        X = self.P[tri.simplices[cand]]
        c, R = _circumcentres(X)
        good = np.all(np.isfinite(c), axis=1)
        cand, c, R, qual_only, lmin = cand[good], c[good], R[good], qual_only[good], lmin[good]

        # circumcentres encroaching a subsegment: split that subsegment instead.
        # Exception (Shewchuk): a skinny triangle next to a small input angle does not
        # split a cluster subsegment if that would create an edge shorter than its own
        # shortest edge — such triangles are a consequence of the input and are kept.
        sid, pid = self._encroached_by(c, exclude_endpoints=False)
        enc = np.zeros(c.shape[0], dtype=bool)
        enc[pid] = True
        if sid.size:
            skip = qual_only[pid] & self.cluster_seg[self.S_base[sid]]
            if skip.any():
                rv = self._cluster_insertion_radius(sid[skip])
                skip[np.flatnonzero(skip)] = rv < lmin[pid[skip]]
            sid = sid[~skip]
        seg_split = np.unique(sid)

        # drop candidates outside the domain (numerical safety)
        loc = tri.find_simplex(c)
        out = (loc < 0) | (label[np.maximum(loc, 0)] == _EXCLUDED)
        ok = ~enc & ~out
        c, R = c[ok], R[ok]

        accepted = np.zeros(c.shape[0], dtype=bool)
        if c.shape[0]:
            blocked = np.zeros(c.shape[0], dtype=bool)
            tree = cKDTree(c)
            near = tree.query_ball_point(c, r=0.5 * R)
            for i in range(c.shape[0]):
                if blocked[i]:
                    continue
                accepted[i] = True
                blocked[near[i]] = True
        newp = c[accepted]
        if newp.shape[0] == 0 and seg_split.size == 0:
            self.exempt_all = True  # every remaining bad triangle is input-induced
        if newp.shape[0]:
            self.P = np.vstack([self.P, newp])
        if seg_split.size:
            self._split_subsegments(seg_split)


def _circumcentres(X: NDArray[np.float64]) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Circumcentres and radii of triangles X (n, 3, 2)."""
    a = X[:, 0]
    b = X[:, 1] - a
    c = X[:, 2] - a
    d = 2.0 * (b[:, 0] * c[:, 1] - b[:, 1] * c[:, 0])
    b2 = np.einsum("ij,ij->i", b, b)
    c2 = np.einsum("ij,ij->i", c, c)
    with np.errstate(divide="ignore", invalid="ignore"):
        ux = (c[:, 1] * b2 - b[:, 1] * c2) / d
        uy = (b[:, 0] * c2 - c[:, 0] * b2) / d
    u = np.column_stack([ux, uy])
    return a + u, np.linalg.norm(u, axis=1)


def _size_function(h: float | SizeFn | None) -> SizeFn | None:
    if h is None:
        return None
    if callable(h):
        fn = h

        def wrapped(x: NDArray, y: NDArray) -> NDArray:
            v = np.broadcast_to(np.asarray(fn(x, y), dtype=float), np.shape(x))
            if np.any(v <= 0) or not np.all(np.isfinite(v)):
                raise MeshError("size function must return positive finite values")
            return v

        return wrapped
    hv = float(h)
    if hv <= 0:
        raise MeshError("h must be positive")
    return lambda x, y: np.full(np.shape(x), hv)


# ======================================================================= output
def _assemble(
    eng: _Refiner, tri: Delaunay, label: NDArray[np.int64], etype: ElemType, tag: str
) -> Mesh:
    keep = label != _EXCLUDED
    conn = tri.simplices[keep].astype(np.int64)
    region = label[keep].astype(np.int32)
    P = eng.P

    # CCW orientation
    X = P[conn]
    a2 = (X[:, 1, 0] - X[:, 0, 0]) * (X[:, 2, 1] - X[:, 0, 1]) - (X[:, 2, 0] - X[:, 0, 0]) * (
        X[:, 1, 1] - X[:, 0, 1]
    )
    conn[a2 < 0] = conn[a2 < 0][:, [0, 2, 1]]

    # drop unused vertices (holes, isolated points outside), renumber
    used = np.zeros(P.shape[0], dtype=bool)
    used[conn.ravel()] = True
    new_id = -np.ones(P.shape[0], dtype=np.int64)
    new_id[used] = np.arange(int(used.sum()))
    coords = P[used]
    conn = new_id[conn]
    nv = coords.shape[0]

    # unique edges of the triangulation
    ea = np.concatenate([conn[:, 0], conn[:, 1], conn[:, 2]])
    eb = np.concatenate([conn[:, 1], conn[:, 2], conn[:, 0]])
    ekey = np.minimum(ea, eb) * nv + np.maximum(ea, eb)
    ukey, einv, ecount = np.unique(ekey, return_inverse=True, return_counts=True)
    einv = einv.ravel()
    ne_tri = conn.shape[0]

    if etype is ElemType.T6:
        lo, hi = ukey // nv, ukey % nv
        mids = 0.5 * (coords[lo] + coords[hi])
        mid_id = nv + np.arange(ukey.size)
        coords = np.vstack([coords, mids])
        m = mid_id[einv].reshape(3, ne_tri).T  # edges (0-1), (1-2), (2-0)
        conn = np.column_stack([conn, m])
    else:
        mid_id = None

    def edges_from_pairs(pa: NDArray, pb: NDArray) -> NDArray[np.int64]:
        k = np.minimum(pa, pb) * nv + np.maximum(pa, pb)
        pos = np.clip(np.searchsorted(ukey, k), 0, max(ukey.size - 1, 0))
        found = ukey[pos] == k
        pa, pb, pos = pa[found], pb[found], pos[found]
        if mid_id is not None:
            return np.column_stack([pa, pb, mid_id[pos]])
        return np.column_stack([pa, pb])

    node_sets: dict[str, NDArray[np.int64]] = {}
    edge_sets: dict[str, NDArray[np.int64]] = {}
    S = eng.S
    sa, sb = new_id[S[:, 0]], new_id[S[:, 1]]
    valid = (sa >= 0) & (sb >= 0)
    for name, base_ids in eng.g.seg_names.items():
        sel = valid & np.isin(eng.S_base, base_ids)
        # orient every subsegment along the direction of the input that carries the name
        sign = np.ones(eng.g.segs.shape[0], dtype=np.int8)
        sign[base_ids] = eng.g.seg_sign[name]
        flip = sign[eng.S_base[sel]] < 0
        pa = np.where(flip, sb[sel], sa[sel])
        pb = np.where(flip, sa[sel], sb[sel])
        e = edges_from_pairs(pa, pb)
        n_missing = int(np.isin(eng.S_base, base_ids).sum()) - e.shape[0]
        if n_missing:
            log.warning("set '%s': %d subsegment(s) outside the meshed domain", name, n_missing)
        edge_sets[name] = e.reshape(-1, etype.nodes_per_edge)
        node_sets[name] = np.unique(e)
    for name, vid in eng.g.point_names.items():
        nid = int(new_id[vid])
        if nid < 0:
            raise MeshError(f"named point '{name}' lies outside the meshed domain")
        node_sets[name] = np.array([nid], dtype=np.int64)

    bnd = np.flatnonzero(ecount == 1)
    be = edges_from_pairs(ukey[bnd] // nv, ukey[bnd] % nv)
    edge_sets["boundary"] = be
    node_sets["boundary"] = np.unique(be)
    node_sets["all"] = np.arange(coords.shape[0])

    blk = ElementBlock(etype, conn, region, tag)
    return Mesh(coords, (blk,), node_sets, edge_sets)

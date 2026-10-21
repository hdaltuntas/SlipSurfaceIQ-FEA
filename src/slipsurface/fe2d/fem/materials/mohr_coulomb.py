"""Mohr-Coulomb with tension cut-off — implicit return in principal stress space.

Sign convention: tension positive, sorted principal stresses s1 >= s2 >= s3.
With ``k = (1 + sin phi)/(1 - sin phi)`` and ``sc = 2 c sqrt(k)`` the yield surface is the
plane (scaled form of ``(s1 - s3) + (s1 + s3) sin phi - 2 c cos phi``)

    f_a = k s1 - s3 - sc            potential  g_a = m s1 - s3,  m = (1 + sin psi)/(1 - sin psi)

and the tension cut-off ``f_t = s1 - st`` (associated). In the sorted principal frame all
surfaces are planes, so the closest-point projection for any active set ``J`` is linear
(Clausen, Damkilde & Andersen 2006/2007):

    sigma = sigma_tr - D B dl,     A sigma = r     ->  dl = (A D B)^-1 (A sigma_tr - r)

The active set is found by enumeration in a fixed order — plane, edges (s1 = s2,
s2 = s3, tension edge, MC/tension intersection), then the four corner points (MC apex,
tension apex and the two MC/tension corners) — accepting the first set whose
multipliers are non-negative and whose stress is admissible. At the corner points the
stress is fixed by three constraints and acceptance is decided by whether the plastic
corrector lies in the cone spanned by *all* potentials active there.

The consistent tangent is ``D - D B (A D B)^-1 A D`` in the principal frame (exact for
planar surfaces) plus the spin term ``G_alg = G (sa - sb)/(sa_tr - sb_tr)`` for the
in-plane principal axes, rotated back to x-y. Out-of-plane ``szz`` is always principal.
"""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray

from ...core.enums import PlasticFlag
from .._jit import njit, prange
from .elastic import LinearElastic

APEX_TANGENT = 1e-3
"""Tangent at corner returns (apex, tension corners) as a fraction of D. The consistent
value is zero; a small positive floor keeps nodes that are held only by such points from
making the Newton system singular (it only affects the convergence path, not the
converged state)."""

_EL, _SH, _TE, _AP = (
    int(PlasticFlag.ELASTIC),
    int(PlasticFlag.SHEAR),
    int(PlasticFlag.TENSION),
    int(PlasticFlag.APEX),
)


# --------------------------------------------------------------------- small algebra
@njit
def _det3(M: NDArray) -> float:
    return (
        M[0, 0] * (M[1, 1] * M[2, 2] - M[1, 2] * M[2, 1])
        - M[0, 1] * (M[1, 0] * M[2, 2] - M[1, 2] * M[2, 0])
        + M[0, 2] * (M[1, 0] * M[2, 1] - M[1, 1] * M[2, 0])
    )


@njit
def _inv(M: NDArray, n: int, out: NDArray) -> bool:
    """Inverse of the leading n x n block of M (n <= 3) into out; False if singular."""
    if n == 1:
        if abs(M[0, 0]) < 1e-300:
            return False
        out[0, 0] = 1.0 / M[0, 0]
        return True
    if n == 2:
        d = M[0, 0] * M[1, 1] - M[0, 1] * M[1, 0]
        sc = abs(M[0, 0] * M[1, 1]) + abs(M[0, 1] * M[1, 0])
        if abs(d) <= 1e-12 * sc or sc == 0.0:
            return False
        out[0, 0] = M[1, 1] / d
        out[0, 1] = -M[0, 1] / d
        out[1, 0] = -M[1, 0] / d
        out[1, 1] = M[0, 0] / d
        return True
    d = _det3(M)
    sc = 0.0
    for i in range(3):
        for j in range(3):
            sc = max(sc, abs(M[i, j]))
    if sc == 0.0 or abs(d) <= 1e-12 * sc**3:
        return False
    out[0, 0] = (M[1, 1] * M[2, 2] - M[1, 2] * M[2, 1]) / d
    out[0, 1] = (M[0, 2] * M[2, 1] - M[0, 1] * M[2, 2]) / d
    out[0, 2] = (M[0, 1] * M[1, 2] - M[0, 2] * M[1, 1]) / d
    out[1, 0] = (M[1, 2] * M[2, 0] - M[1, 0] * M[2, 2]) / d
    out[1, 1] = (M[0, 0] * M[2, 2] - M[0, 2] * M[2, 0]) / d
    out[1, 2] = (M[0, 2] * M[1, 0] - M[0, 0] * M[1, 2]) / d
    out[2, 0] = (M[1, 0] * M[2, 1] - M[1, 1] * M[2, 0]) / d
    out[2, 1] = (M[0, 1] * M[2, 0] - M[0, 0] * M[2, 1]) / d
    out[2, 2] = (M[0, 0] * M[1, 1] - M[0, 1] * M[1, 0]) / d
    return True


@njit
def _in_cone(x: NDArray, V: NDArray, idx: NDArray, nv: int, tol: float) -> bool:
    """Is x a non-negative combination of 3 of the vectors V[idx[:nv]] (3-vectors)?"""
    M = np.empty((3, 3))
    Mi = np.empty((3, 3))
    for i in range(nv):
        for j in range(i + 1, nv):
            for l in range(j + 1, nv):
                for r in range(3):
                    M[r, 0] = V[idx[i], r]
                    M[r, 1] = V[idx[j], r]
                    M[r, 2] = V[idx[l], r]
                if not _inv(M, 3, Mi):
                    continue
                ok = True
                for r in range(3):
                    c = Mi[r, 0] * x[0] + Mi[r, 1] * x[1] + Mi[r, 2] * x[2]
                    if c < -tol:
                        ok = False
                        break
                if ok:
                    return True
    return False


# ------------------------------------------------------------------- GP kernel
@njit
def _return_principal(
    s_tr: NDArray,
    lam: float,
    G: float,
    k: float,
    m: float,
    sc: float,
    st: float,
    has_apex: bool,
    has_t: bool,
    s_out: NDArray,
    C_out: NDArray,
) -> int:
    """Return sorted principal trial stress; writes stress and 3x3 tangent; returns flag."""
    D = np.full((3, 3), lam)
    for i in range(3):
        D[i, i] = lam + 2.0 * G
    # surfaces: 0 a(s1,s3) 1 b(s2,s3) 2 c(s1,s2) 3 t1 4 t2 5 t3
    A = np.zeros((6, 3))
    rhs = np.zeros(6)
    A[0, 0], A[0, 2] = k, -1.0
    A[1, 1], A[1, 2] = k, -1.0
    A[2, 0], A[2, 1] = k, -1.0
    A[3, 0] = A[4, 1] = A[5, 2] = 1.0
    rhs[0] = rhs[1] = rhs[2] = sc
    rhs[3] = rhs[4] = rhs[5] = st
    # potentials 0..5 as above, 6..8 the remaining MC permutations (active at the apex)
    Bv = np.zeros((9, 3))
    Bv[0, 0], Bv[0, 2] = m, -1.0
    Bv[1, 1], Bv[1, 2] = m, -1.0
    Bv[2, 0], Bv[2, 1] = m, -1.0
    Bv[3, 0] = Bv[4, 1] = Bv[5, 2] = 1.0
    Bv[6, 1], Bv[6, 0] = m, -1.0
    Bv[7, 2], Bv[7, 1] = m, -1.0
    Bv[8, 2], Bv[8, 0] = m, -1.0
    DBv = np.zeros((9, 3))  # rows: D b_j
    for j in range(9):
        for r in range(3):
            DBv[j, r] = D[r, 0] * Bv[j, 0] + D[r, 1] * Bv[j, 1] + D[r, 2] * Bv[j, 2]

    scale = max(abs(sc), abs(s_tr[0]), abs(s_tr[1]), abs(s_tr[2]), 1e-12)
    if has_t:
        scale = max(scale, abs(st))
    tolf = 1e-10 * scale

    f_tr = k * s_tr[0] - s_tr[2] - sc
    ft_tr = s_tr[0] - st if has_t else -1.0
    if f_tr <= tolf and ft_tr <= tolf:
        for i in range(3):
            s_out[i] = s_tr[i]
            for j in range(3):
                C_out[i, j] = D[i, j]
        return _EL

    sets = np.full((6, 2), -1, dtype=np.int64)
    nset = np.zeros(6, dtype=np.int64)
    sets[0, 0] = 0
    nset[0] = 1  # MC plane
    sets[1, 0] = 3
    nset[1] = 1  # tension plane
    sets[2, 0], sets[2, 1] = 0, 1
    nset[2] = 2  # s1 = s2 edge
    sets[3, 0], sets[3, 1] = 0, 2
    nset[3] = 2  # s2 = s3 edge
    sets[4, 0], sets[4, 1] = 3, 4
    nset[4] = 2  # tension edge s1 = s2 = st
    sets[5, 0], sets[5, 1] = 0, 3
    nset[5] = 2  # MC / tension intersection
    Am = np.zeros((2, 3))
    DB = np.zeros((3, 2))
    M = np.zeros((3, 3))
    Mi = np.zeros((3, 3))
    r = np.zeros(2)
    dl = np.zeros(2)
    s = np.zeros(3)
    for si in range(6):
        n = nset[si]
        uses_t = False
        for a in range(n):
            if sets[si, a] >= 3:
                uses_t = True
        if uses_t and not has_t:
            continue
        for a in range(n):
            j = sets[si, a]
            for c in range(3):
                Am[a, c] = A[j, c]
                DB[c, a] = DBv[j, c]
        for a in range(n):
            for b in range(n):
                M[a, b] = Am[a, 0] * DB[0, b] + Am[a, 1] * DB[1, b] + Am[a, 2] * DB[2, b]
            r[a] = Am[a, 0] * s_tr[0] + Am[a, 1] * s_tr[1] + Am[a, 2] * s_tr[2] - rhs[sets[si, a]]
        if not _inv(M, n, Mi):
            continue
        ok = True
        for a in range(n):
            dl[a] = 0.0
            for b in range(n):
                dl[a] += Mi[a, b] * r[b]
            if dl[a] < -1e-12 * scale / max(G, 1e-300):
                ok = False
        if not ok:
            continue
        for c in range(3):
            s[c] = s_tr[c]
            for a in range(n):
                s[c] -= DB[c, a] * dl[a]
        # admissibility (sorted-independent)
        smax = max(s[0], s[1], s[2])
        smin = min(s[0], s[1], s[2])
        if k * smax - smin - sc > tolf * 10:
            continue
        if has_t and smax - st > tolf * 10:
            continue
        # consistent tangent  D - D B M^-1 A D
        for i in range(3):
            for j in range(3):
                acc = 0.0
                for a in range(n):
                    for b in range(n):
                        AD = Am[b, 0] * D[0, j] + Am[b, 1] * D[1, j] + Am[b, 2] * D[2, j]
                        acc += DB[i, a] * Mi[a, b] * AD
                C_out[i, j] = D[i, j] - acc
        for c in range(3):
            s_out[c] = s[c]
        return _TE if uses_t else _SH

    # ---- corner points: three constraints fix the stress
    idx = np.zeros(6, dtype=np.int64)
    x = np.zeros(3)
    for pt in range(4):
        if pt == 0:  # MC apex
            if not has_apex:
                continue
            rows = (0, 1, 2)
            nv = 6
            idx[0], idx[1], idx[2], idx[3], idx[4], idx[5] = 0, 1, 2, 6, 7, 8
            flag = _AP
        elif pt == 1:  # tension apex
            if not has_t:
                continue
            rows = (3, 4, 5)
            nv = 3
            idx[0], idx[1], idx[2] = 3, 4, 5
            flag = _TE
        elif pt == 2:  # s1 = s2 = st, s3 on MC
            if not has_t:
                continue
            rows = (0, 3, 4)
            nv = 4
            idx[0], idx[1], idx[2], idx[3] = 0, 1, 3, 4
            flag = _TE
        else:  # s1 = st, s2 = s3 on MC
            if not has_t:
                continue
            rows = (0, 2, 3)
            nv = 3
            idx[0], idx[1], idx[2] = 0, 2, 3
            flag = _TE
        for a in range(3):
            for c in range(3):
                M[a, c] = A[rows[a], c]
        if not _inv(M, 3, Mi):
            continue
        for c in range(3):
            s[c] = Mi[c, 0] * rhs[rows[0]] + Mi[c, 1] * rhs[rows[1]] + Mi[c, 2] * rhs[rows[2]]
        smax = max(s[0], s[1], s[2])
        smin = min(s[0], s[1], s[2])
        if k * smax - smin - sc > tolf * 10:
            continue
        if has_t and smax - st > tolf * 10:
            continue
        for c in range(3):
            x[c] = s_tr[c] - s[c]
        if not _in_cone(x, DBv, idx, nv, 1e-10):
            continue
        for c in range(3):
            s_out[c] = s[c]
            for j in range(3):
                C_out[c, j] = APEX_TANGENT * D[c, j]  # corner: (almost) zero stiffness
        return flag
    # non-associated flow (psi < phi): the trial can lie beyond the apex in a direction no
    # combination of flow vectors reaches (e.g. psi = 0 is isochoric). As in Clausen's
    # region scheme the apex region is "everything else": return to the admissible corner
    # point closest to the trial in the energy norm.
    Dinv = np.empty((3, 3))
    _inv(D, 3, Dinv)
    best = -1
    best_e = 1e300
    sb = np.zeros(3)
    for pt in range(4):
        if pt == 0 and not has_apex:
            continue
        if pt > 0 and not has_t:
            continue
        if pt == 0:
            rows = (0, 1, 2)
        elif pt == 1:
            rows = (3, 4, 5)
        elif pt == 2:
            rows = (0, 3, 4)
        else:
            rows = (0, 2, 3)
        for a in range(3):
            for c in range(3):
                M[a, c] = A[rows[a], c]
        if not _inv(M, 3, Mi):
            continue
        for c in range(3):
            s[c] = Mi[c, 0] * rhs[rows[0]] + Mi[c, 1] * rhs[rows[1]] + Mi[c, 2] * rhs[rows[2]]
        smax = max(s[0], s[1], s[2])
        smin = min(s[0], s[1], s[2])
        if k * smax - smin - sc > tolf * 10:
            continue
        if has_t and smax - st > tolf * 10:
            continue
        e = 0.0
        for a in range(3):
            for c in range(3):
                e += (s_tr[a] - s[a]) * Dinv[a, c] * (s_tr[c] - s[c])
        if e < best_e:
            best_e = e
            best = pt
            for c in range(3):
                sb[c] = s[c]
    if best >= 0:
        for c in range(3):
            s_out[c] = sb[c]
            for j in range(3):
                C_out[c, j] = APEX_TANGENT * D[c, j]
        return _AP if best == 0 else _TE
    for c in range(3):  # should not happen
        s_out[c] = s_tr[c]
        for j in range(3):
            C_out[c, j] = D[c, j]
    return 255


@njit
def principal_frame(sig: NDArray) -> tuple:
    """In-plane spectral decomposition of a (4,) stress. Returns the principal values
    ``p = (a, b, z)`` (a >= b in plane), ``cos/sin`` of the in-plane axis angle, the
    sorting permutation ``pos[orig] = sorted position`` and the sorted values ``ps``
    (descending, tension positive)."""
    sxx, syy, szz, txy = sig[0], sig[1], sig[2], sig[3]
    cen = 0.5 * (sxx + syy)
    rad = math.sqrt((0.5 * (sxx - syy)) ** 2 + txy * txy)
    th = 0.5 * math.atan2(2.0 * txy, sxx - syy)
    c, s = math.cos(th), math.sin(th)
    p = np.empty(3)
    p[0], p[1], p[2] = cen + rad, cen - rad, szz
    o = np.argsort(-p)
    pos = np.empty(3, dtype=np.int64)
    for i in range(3):
        pos[o[i]] = i
    ps = np.empty(3)
    for i in range(3):
        ps[i] = p[o[i]]
    return p, c, s, pos, ps


@njit
def from_principal(
    p: NDArray,
    c: float,
    s: float,
    pos: NDArray,
    rs: NDArray,
    Cs: NDArray,
    G: float,
    sig: NDArray,
    Dalg: NDArray,
) -> None:
    """Rotate the returned sorted principal stress ``rs`` and its 3x3 tangent ``Cs`` back
    to x-y (writes ``sig`` and the 4x4 ``Dalg``, including the in-plane spin term)."""
    q = np.empty(3)
    for i in range(3):
        q[i] = rs[pos[i]]
    sig[0] = q[0] * c * c + q[1] * s * s
    sig[1] = q[0] * s * s + q[1] * c * c
    sig[2] = q[2]
    sig[3] = (q[0] - q[1]) * s * c
    Cp = np.zeros((4, 4))
    for i in range(3):
        for j in range(3):
            Cp[i, j] = Cs[pos[i], pos[j]]
    dtr = p[0] - p[1]
    if abs(dtr) > 1e-10 * max(abs(p[0]) + abs(p[1]), 1e-300):
        Cp[3, 3] = G * (q[0] - q[1]) / dtr
    else:
        Cp[3, 3] = 0.5 * (Cp[0, 0] - Cp[0, 1])
    T = np.zeros((4, 4))
    T[0, 0], T[1, 0], T[3, 0] = c * c, s * s, s * c
    T[0, 1], T[1, 1], T[3, 1] = s * s, c * c, -s * c
    T[2, 2] = 1.0
    T[0, 3], T[1, 3], T[3, 3] = -2.0 * s * c, 2.0 * s * c, c * c - s * s
    TC = T @ Cp
    for i in range(4):
        for j in range(4):
            acc = 0.0
            for l in range(4):
                acc += TC[i, l] * T[j, l]
            Dalg[i, j] = acc


@njit
def _mc_gp(
    sig_tr: NDArray,
    lam: float,
    G: float,
    k: float,
    m: float,
    sc: float,
    st: float,
    has_apex: bool,
    has_t: bool,
    sig: NDArray,
    Dalg: NDArray,
) -> int:
    p, c, s, pos, ps = principal_frame(sig_tr)
    rs = np.empty(3)
    Cs = np.empty((3, 3))
    flag = _return_principal(ps, lam, G, k, m, sc, st, has_apex, has_t, rs, Cs)
    from_principal(p, c, s, pos, rs, Cs, G, sig, Dalg)
    return flag


@njit(parallel=True)
def _mc_batch(
    sig_tr: NDArray,
    lam: float,
    G: float,
    k: float,
    m: float,
    sc: float,
    st: float,
    has_apex: bool,
    has_t: bool,
    sig: NDArray,
    Dalg: NDArray,
    flag: NDArray,
) -> None:
    for i in prange(sig_tr.shape[0]):
        flag[i] = _mc_gp(sig_tr[i], lam, G, k, m, sc, st, has_apex, has_t, sig[i], Dalg[i])


# ------------------------------------------------------------------- model class
class MohrCoulomb(LinearElastic):
    """Elastic-perfectly plastic Mohr-Coulomb with optional tension cut-off.

    Parameters: E, nu, c [kPa], phi, psi [deg], sig_t (tensile strength, ``None`` →
    no cut-off: the MC apex ``c cot(phi)`` limits tension).
    Internal variable q[0]: accumulated equivalent plastic strain.
    """

    n_int = 1
    plastic = True

    def __init__(
        self,
        E: float,
        nu: float,
        c: float,
        phi: float,
        psi: float = 0.0,
        sig_t: float | None = None,
    ) -> None:
        super().__init__(E, nu, phi)
        if not 0.0 <= phi < 90.0 or not 0.0 <= psi <= phi:
            raise ValueError("need 0 <= psi <= phi < 90 degrees")
        if c < 0:
            raise ValueError("cohesion must be >= 0")
        self.c, self.phi, self.psi = float(c), float(phi), float(psi)
        sp, sq = math.sin(math.radians(phi)), math.sin(math.radians(psi))
        self.k = (1 + sp) / (1 - sp)
        self.m = (1 + sq) / (1 - sq)
        self.sc = 2.0 * self.c * math.sqrt(self.k)
        self.has_apex = phi > 0.0
        apex = self.sc / (self.k - 1.0) if self.has_apex else math.inf
        self.apex = apex
        if sig_t is None or sig_t >= apex:
            self.has_t, self.st = False, math.inf
        else:
            if sig_t < 0:
                raise ValueError("tensile strength must be >= 0")
            self.has_t, self.st = True, float(sig_t)
        self.symmetric = abs(psi - phi) < 1e-12
        self._lam = E * nu / ((1 + nu) * (1 - 2 * nu))
        self._Dinv = np.linalg.inv(self._D)

    def yield_function(self, sig: NDArray[np.float64]) -> NDArray[np.float64]:
        """max(f_MC, f_t) for (..., 4) stresses (scaled MC form)."""
        from ...post.recovery import principal_stresses

        p = principal_stresses(sig)
        f = self.k * p["s1"] - p["s3"] - self.sc
        if self.has_t:
            f = np.maximum(f, p["s1"] - self.st)
        return np.asarray(f)

    def integrate(
        self,
        sig_n: NDArray[np.float64],
        deps: NDArray[np.float64],
        q_n: NDArray[np.float64],
    ) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64], NDArray[np.uint8]]:
        sig_tr = np.ascontiguousarray(sig_n + deps @ self._D.T)
        n = sig_tr.shape[0]
        sig = np.empty_like(sig_tr)
        D = np.empty((n, 4, 4))
        flag = np.empty(n, dtype=np.uint8)
        st = self.st if self.has_t else 0.0
        _mc_batch(sig_tr, self._lam, self.G, self.k, self.m, self.sc, st,
                  self.has_apex, self.has_t, sig, D, flag)  # fmt: skip
        q = q_n.copy()
        pl = flag != 0
        if np.any(pl):
            dep = (sig_tr[pl] - sig[pl]) @ self._Dinv.T
            q[pl, 0] += equivalent_plastic_strain(dep)
        return sig, q, D, flag


def equivalent_plastic_strain(dep: NDArray[np.float64]) -> NDArray[np.float64]:
    """sqrt(2/3 e_p:e_p) of the deviatoric part (engineering shear in component 3)."""
    ev = dep[:, :3].sum(axis=1) / 3.0
    d = dep[:, :3] - ev[:, None]
    return np.asarray(np.sqrt(2.0 / 3.0 * ((d * d).sum(axis=1) + 0.5 * dep[:, 3] ** 2)))

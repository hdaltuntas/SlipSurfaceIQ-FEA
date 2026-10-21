"""Generalised Hoek-Brown (2002) — implicit return in principal stress space.

Sign convention: tension positive, sorted principal stresses s1 >= s2 >= s3 (s3 is the
major compression). With uniaxial strength ``sci`` and rock-mass constants ``mb, s, a``

    f = s1 - s3 - sci X^a,      X = s - mb s1 / sci  >= 0

so the tensile strength (apex, s1 = s2 = s3) is ``st = s sci / mb``. The plastic potential
is of Mohr-Coulomb type with a constant dilation angle psi,

    g = m s1 - s3,    m = (1 + sin psi) / (1 - sin psi),

as is usual for rock masses (Carranza-Torres 2004; Clausen & Damkilde 2008). Because g is
linear, every return is a straight line in principal space,

    sigma(t) = sigma_tr - D (t u + v),

with ``u = b`` (main surface) or ``u = (b_a + b_b)/2`` and a fixed ``v`` on the two edges
(s1 = s2: surfaces (1,3), (2,3); s2 = s3: surfaces (1,3), (1,2)), where the edge
condition fixes the difference of the two multipliers. The remaining scalar equation
``f(sigma(t)) = 0`` is monotone in t and solved by safeguarded Newton (bracketing). If no
non-negative edge solution exists the stress returns to the apex.

Consistent tangent (exact for a linear potential): ``D - D B (A^T D B)^-1 A^T D`` in the
principal frame, with A the yield gradients at the returned stress, plus the in-plane
spin term (shared with :mod:`.mohr_coulomb`).
"""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray

from ...core.enums import PlasticFlag
from .._jit import njit, prange
from .elastic import LinearElastic
from .mohr_coulomb import APEX_TANGENT, equivalent_plastic_strain, from_principal, principal_frame

_EL, _SH, _AP = int(PlasticFlag.ELASTIC), int(PlasticFlag.SHEAR), int(PlasticFlag.APEX)


@njit
def _f(s1: float, s3: float, sci: float, mb: float, s: float, a: float) -> float:
    X = s - mb * s1 / sci
    if X > 0.0:
        return s1 - s3 - sci * X**a
    return s1 - s3 - sci * X  # beyond the tensile strength: continuous, strictly positive


@njit
def _df1(s1: float, sci: float, mb: float, s: float, a: float) -> float:
    X = s - mb * s1 / sci
    if X <= 0.0:
        return 1e30
    return 1.0 + a * mb * X ** (a - 1.0)


@njit
def _phi(
    t: float, ps: NDArray, Du: NDArray, Dv: NDArray, sci: float, mb: float, s: float, a: float
) -> float:
    return _f(ps[0] - t * Du[0] - Dv[0], ps[2] - t * Du[2] - Dv[2], sci, mb, s, a)


@njit
def _line(
    ps: NDArray,
    Dp: NDArray,
    u: NDArray,
    v: NDArray,
    t_lo: float,
    sci: float,
    mb: float,
    s: float,
    a: float,
    out: NDArray,
) -> float:
    """Root t >= t_lo of f(ps - Dp (t u + v)) = 0; returns -1 if f(t_lo) <= 0 or none."""
    Du = Dp @ u
    Dv = Dp @ v
    tol = 1e-12 * sci
    f_lo = _phi(t_lo, ps, Du, Dv, sci, mb, s, a)
    if f_lo <= tol:
        return -1.0
    lo = t_lo
    step = max(abs(f_lo) / max(abs(Du[0] - Du[2]), 1e-300), 1e-300)
    hi = t_lo + step
    f_hi = _phi(hi, ps, Du, Dv, sci, mb, s, a)
    n = 0
    while f_hi > 0.0:
        lo, f_lo = hi, f_hi
        step *= 2.0
        hi = lo + step
        f_hi = _phi(hi, ps, Du, Dv, sci, mb, s, a)
        n += 1
        if n > 200:
            return -1.0
    t = hi if -f_hi < f_lo else lo
    for _ in range(200):
        ft = _phi(t, ps, Du, Dv, sci, mb, s, a)
        if abs(ft) <= tol:
            break
        if ft > 0.0:
            lo = t
        else:
            hi = t
        s1 = ps[0] - t * Du[0] - Dv[0]
        tn = 0.5 * (lo + hi)
        if s - mb * s1 / sci > 0.0:  # Newton where f is smooth, bisection beyond the apex
            dphi = -(_df1(s1, sci, mb, s, a) * Du[0] - Du[2])
            if dphi < 0.0:
                tn = t - ft / dphi
        if not lo < tn < hi:
            tn = 0.5 * (lo + hi)
        t = tn
        if hi - lo <= 1e-15 * max(abs(hi), 1e-300):
            break
    for i in range(3):
        out[i] = ps[i] - t * Du[i] - Dv[i]
    return t


@njit
def _tangent(Dp: NDArray, A: NDArray, B: NDArray, nact: int, C: NDArray) -> None:
    """C = Dp - Dp B (A^T Dp B)^-1 A^T Dp for nact = 1 or 2 active surfaces."""
    DB = np.ascontiguousarray(Dp @ np.ascontiguousarray(B[:, :nact]))
    At = np.ascontiguousarray(A[:, :nact].T)
    AD = At @ Dp
    M = At @ DB
    if nact == 1:
        det = M[0, 0]
        Mi = np.empty((1, 1))
        Mi[0, 0] = 1.0 / det if det != 0.0 else 0.0
    else:
        det = M[0, 0] * M[1, 1] - M[0, 1] * M[1, 0]
        Mi = np.empty((2, 2))
        if det != 0.0:
            Mi[0, 0], Mi[1, 1] = M[1, 1] / det, M[0, 0] / det
            Mi[0, 1], Mi[1, 0] = -M[0, 1] / det, -M[1, 0] / det
    C[:, :] = Dp - DB @ Mi @ AD
    if det == 0.0 or not np.all(np.isfinite(C)):
        C[:, :] = APEX_TANGENT * Dp


@njit
def _hb_principal(
    ps: NDArray,
    lam: float,
    G: float,
    sci: float,
    mb: float,
    s: float,
    a: float,
    m: float,
    rs: NDArray,
    Cs: NDArray,
) -> int:
    Dp = np.full((3, 3), lam)
    for i in range(3):
        Dp[i, i] += 2.0 * G
    st = s * sci / mb
    tol = 1e-12 * sci
    if _f(ps[0], ps[2], sci, mb, s, a) <= tol and ps[0] <= st:
        rs[:] = ps
        Cs[:, :] = Dp
        return _EL
    # ---- apex region: the trial point lies in the cone of the plastic correctors of
    # the three surfaces meeting there (psi = 0: no volume change, so a mean stress
    # above the tensile strength cannot be returned anywhere else)
    if m - 1.0 < 1e-12:
        at_apex = (ps[0] + ps[1] + ps[2]) / 3.0 >= st - tol
    else:
        B3 = np.array([[m, 0.0, m], [0.0, m, -1.0], [-1.0, -1.0, 0.0]])
        dl3 = np.linalg.solve(Dp @ B3, ps - st)
        at_apex = dl3.min() >= -1e-12 * max(np.abs(dl3).max(), 1e-300)
    if at_apex:
        rs[:] = st
        Cs[:, :] = APEX_TANGENT * Dp
        return _AP
    A = np.zeros((3, 2))
    B = np.zeros((3, 2))
    zero = np.zeros(3)
    # ---- main surface
    b = np.array([m, 0.0, -1.0])
    t = _line(ps, Dp, b, zero, 0.0, sci, mb, s, a, rs)
    if t >= 0.0:
        s2 = ps[1] - t * (Dp[1] @ b)
        if rs[0] >= s2 - tol and s2 >= rs[2] - tol and s - mb * rs[0] / sci >= 0.0:
            rs[1] = s2
            A[0, 0], A[2, 0] = _df1(rs[0], sci, mb, s, a), -1.0
            B[:, 0] = b
            _tangent(Dp, A, B, 1, Cs)
            return _SH
        first12 = rs[0] < s2
    else:
        first12 = ps[0] - ps[1] < ps[1] - ps[2]
    # ---- edges: the multiplier difference follows from the edge condition; the edge
    # suggested by the violated ordering is tried first, the other one second
    ba = np.array([m, 0.0, -1.0])
    for k in range(2):
        edge12 = first12 if k == 0 else not first12
        if edge12:  # s1 = s2: surfaces (1,3), (2,3)
            bb = np.array([0.0, m, -1.0])
            delta = (ps[0] - ps[1]) / (2.0 * G * m)
        else:  # s2 = s3: surfaces (1,3), (1,2)
            bb = np.array([m, -1.0, 0.0])
            delta = (ps[1] - ps[2]) / (2.0 * G)
        u = 0.5 * (ba + bb)
        v = 0.5 * delta * (ba - bb)
        t = _line(ps, Dp, u, v, abs(delta), sci, mb, s, a, rs)
        if t < 0.0 or rs[0] < rs[2] - tol or s - mb * rs[0] / sci < 0.0:
            continue
        if edge12:
            rs[1] = rs[0]
        else:
            rs[1] = rs[2]
        d1 = _df1(rs[0], sci, mb, s, a)
        A[:, :] = 0.0
        A[0, 0], A[2, 0] = d1, -1.0
        if edge12:
            A[1, 1], A[2, 1] = d1, -1.0
        else:
            A[0, 1], A[1, 1] = d1, -1.0
        B[:, 0], B[:, 1] = ba, bb
        _tangent(Dp, A, B, 2, Cs)
        return _SH
    # ---- apex
    rs[:] = st
    Cs[:, :] = APEX_TANGENT * Dp
    return _AP


@njit
def _hb_gp(
    sig_tr: NDArray,
    lam: float,
    G: float,
    sci: float,
    mb: float,
    s: float,
    a: float,
    m: float,
    sig: NDArray,
    Dalg: NDArray,
) -> int:
    p, c, sn, pos, ps = principal_frame(sig_tr)
    rs = np.empty(3)
    Cs = np.empty((3, 3))
    flag = _hb_principal(ps, lam, G, sci, mb, s, a, m, rs, Cs)
    from_principal(p, c, sn, pos, rs, Cs, G, sig, Dalg)
    return flag


@njit(parallel=True)
def _hb_batch(
    sig_tr: NDArray,
    lam: float,
    G: float,
    sci: float,
    mb: float,
    s: float,
    a: float,
    m: float,
    sig: NDArray,
    Dalg: NDArray,
    flag: NDArray,
) -> None:
    for i in prange(sig_tr.shape[0]):
        flag[i] = _hb_gp(sig_tr[i], lam, G, sci, mb, s, a, m, sig[i], Dalg[i])


def hb_parameters(GSI: float, mi: float, D: float = 0.0) -> tuple[float, float, float]:
    """Rock-mass constants (mb, s, a) of the generalised criterion (Hoek et al. 2002)."""
    if not 0.0 < GSI <= 100.0 or mi <= 0.0 or not 0.0 <= D <= 1.0:
        raise ValueError("need 0 < GSI <= 100, mi > 0, 0 <= D <= 1")
    mb = mi * math.exp((GSI - 100.0) / (28.0 - 14.0 * D))
    s = math.exp((GSI - 100.0) / (9.0 - 3.0 * D))
    a = 0.5 + (math.exp(-GSI / 15.0) - math.exp(-20.0 / 3.0)) / 6.0
    return mb, s, a


class HoekBrown(LinearElastic):
    """Elastic-perfectly plastic generalised Hoek-Brown with MC-type dilation psi.

    Parameters: E, nu, sci [kPa], mb, s, a (see :func:`hb_parameters`), psi [deg].
    Internal variable q[0]: accumulated equivalent plastic strain.
    """

    n_int = 1
    plastic = True
    symmetric = False

    def __init__(
        self, E: float, nu: float, sci: float, mb: float, s: float, a: float, psi: float = 0.0
    ) -> None:
        super().__init__(E, nu, None)
        if sci <= 0 or mb <= 0 or s < 0 or not 0.0 < a < 1.0 or not 0.0 <= psi < 90.0:
            raise ValueError("Hoek-Brown: need sci > 0, mb > 0, s >= 0, 0 < a < 1, psi >= 0")
        self.sci, self.mb, self.s, self.a, self.psi = float(sci), float(mb), float(s), float(a), psi
        sq = math.sin(math.radians(psi))
        self.m = (1 + sq) / (1 - sq)
        self.st = self.s * self.sci / self.mb
        self._lam = E * nu / ((1 + nu) * (1 - 2 * nu))
        self._Dinv = np.linalg.inv(self._D)

    def yield_function(self, sig: NDArray[np.float64]) -> NDArray[np.float64]:
        from ...post.recovery import principal_stresses

        p = principal_stresses(sig)
        X = self.s - self.mb * p["s1"] / self.sci
        f = p["s1"] - p["s3"] - self.sci * np.where(X > 0, np.maximum(X, 0.0) ** self.a, X)
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
        _hb_batch(sig_tr, self._lam, self.G, self.sci, self.mb, self.s, self.a, self.m,
                  sig, D, flag)  # fmt: skip
        q = q_n.copy()
        pl = flag != 0
        if np.any(pl):
            dep = (sig_tr[pl] - sig[pl]) @ self._Dinv.T
            q[pl, 0] += equivalent_plastic_strain(dep)
        return sig, q, D, flag

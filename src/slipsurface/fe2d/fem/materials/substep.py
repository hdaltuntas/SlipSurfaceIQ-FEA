"""Explicit stress integration with automatic substepping and error control.

Sloan (1987); Sloan, Abbo & Sheng (2001). Used as the fall-back integrator for models
without a closed-form return (generalised Hoek-Brown in Faz 4) and to cross-check the
implicit returns. A model provides, for single Gauss points (4-vectors, tension +):

* ``f(sig, q)``           yield function
* ``df(sig, q)``          d f / d sigma (``df . dsig`` with engineering shear)
* ``dg(sig, q)``          d g / d sigma (plastic strain direction, engineering shear)
* ``hardening(sig, q)``   ``(H, h)``: ``-df/dq . h`` and the internal-variable rate per
  unit multiplier (``dq = dlam h``)

Algorithm per Gauss point:

1. elastic trial; if ``f <= FTOL`` the step is elastic;
2. the elastic fraction ``alpha`` of the strain increment is found with the Pegasus
   method (including elasto-plastic unloading that later reloads);
3. the plastic part is integrated with modified Euler substeps; the local error
   ``||dsig_2 - dsig_1|| / (2 ||sig||)`` must be below ``STOL``, the substep size adapts as
   ``0.9 sqrt(STOL / R)`` (bounded to [0.1, 1.1]);
4. after each accepted substep the yield-surface drift is removed by the consistent
   correction ``sig -= f / (a.D.b + H) D b``.

The returned tangent is the continuum elasto-plastic matrix at the final state (the
consistent tangent of an explicit scheme is not available), so global Newton
convergence with this integrator is linear-superlinear rather than quadratic.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

Vec = NDArray[np.float64]


@dataclass(frozen=True)
class SubstepSettings:
    stol: float = 1e-6  # relative local error tolerance
    ftol: float = 1e-9  # yield-surface tolerance (relative to the stress scale)
    dt_min: float = 1e-6
    max_substeps: int = 10_000
    drift_iter: int = 5


_DEFAULT = SubstepSettings()


class YieldModel:
    """Callbacks used by :func:`integrate_substep` (see module docstring)."""

    def f(self, sig: Vec, q: Vec) -> float:  # pragma: no cover - interface
        raise NotImplementedError

    def df(self, sig: Vec, q: Vec) -> Vec:  # pragma: no cover
        raise NotImplementedError

    def dg(self, sig: Vec, q: Vec) -> Vec:  # pragma: no cover
        raise NotImplementedError

    def hardening(self, sig: Vec, q: Vec) -> tuple[float, Vec]:
        return 0.0, np.zeros_like(q)


def _plastic_increment(m: YieldModel, D: NDArray, sig: Vec, q: Vec, deps: Vec) -> tuple[Vec, Vec]:
    a, b = m.df(sig, q), m.dg(sig, q)
    H, h = m.hardening(sig, q)
    Db = D @ b
    den = a @ Db + H
    De = D @ deps
    lam = max(a @ De / den, 0.0) if den > 0 else 0.0
    return De - lam * Db, lam * h


def _pegasus(m: YieldModel, D: NDArray, sig: Vec, q: Vec, deps: Vec, a0: float, a1: float,
             ftol: float) -> float:  # fmt: skip
    f0 = m.f(sig + a0 * (D @ deps), q)
    f1 = m.f(sig + a1 * (D @ deps), q)
    for _ in range(100):
        if f1 == f0:
            break
        a = a1 - f1 * (a1 - a0) / (f1 - f0)
        fa = m.f(sig + a * (D @ deps), q)
        if abs(fa) <= ftol:
            return float(a)
        if fa * f1 < 0:
            a0, f0 = a1, f1
        else:
            f0 = f0 * f1 / (f1 + fa)
        a1, f1 = a, fa
    return float(a1)


def elastic_fraction(m: YieldModel, D: NDArray, sig: Vec, q: Vec, deps: Vec, ftol: float) -> float:
    """Fraction alpha of ``deps`` that is purely elastic (Sloan et al. 2001)."""
    f0 = m.f(sig, q)
    f1 = m.f(sig + D @ deps, q)
    if f1 <= ftol:
        return 1.0
    if f0 < -ftol:
        return _pegasus(m, D, sig, q, deps, 0.0, 1.0, ftol)
    # on the surface: loading or elasto-plastic unloading?
    a = m.df(sig, q)
    De = D @ deps
    cos = a @ De / max(np.linalg.norm(a) * np.linalg.norm(De), 1e-300)
    if cos >= -1e-6:
        return 0.0
    # unloading then reloading: bracket the crossing on a fine subdivision
    n = 10
    a_prev = 0.0
    for i in range(1, n + 1):
        ai = i / n
        if m.f(sig + ai * De, q) > ftol:
            return _pegasus(m, D, sig, q, deps, a_prev, ai, ftol)
        a_prev = ai
    return 1.0


def integrate_substep(
    m: YieldModel,
    D: NDArray[np.float64],
    sig_n: Vec,
    q_n: Vec,
    deps: Vec,
    s: SubstepSettings | None = None,
) -> tuple[Vec, Vec, NDArray[np.float64], int, int]:
    """Integrate one Gauss point. Returns (sig, q, D_ep, plastic(0/1), n_substeps)."""
    s = s or _DEFAULT
    scale = max(float(np.abs(sig_n).max()), float(np.abs(D @ deps).max()), 1.0)
    ftol = s.ftol * scale
    alpha = elastic_fraction(m, D, sig_n, q_n, deps, ftol)
    sig = sig_n + alpha * (D @ deps)
    q = q_n.copy()
    if alpha >= 1.0:
        return sig, q, D.copy(), 0, 0
    rest = (1.0 - alpha) * deps
    T, dT, n = 0.0, 1.0, 0
    while T < 1.0 - 1e-14:
        dT = min(dT, 1.0 - T)
        de = dT * rest
        ds1, dq1 = _plastic_increment(m, D, sig, q, de)
        ds2, dq2 = _plastic_increment(m, D, sig + ds1, q + dq1, de)
        sig_new = sig + 0.5 * (ds1 + ds2)
        q_new = q + 0.5 * (dq1 + dq2)
        R = 0.5 * np.linalg.norm(ds2 - ds1) / max(np.linalg.norm(sig_new), scale * 1e-12)
        n += 1
        if n > s.max_substeps:
            raise RuntimeError("substepping did not finish (max_substeps)")
        if R > s.stol and dT > s.dt_min:
            dT = max(0.9 * np.sqrt(s.stol / R), 0.1) * dT
            dT = max(dT, s.dt_min)
            continue
        # drift correction back onto the yield surface
        for _ in range(s.drift_iter):
            fv = m.f(sig_new, q_new)
            if abs(fv) <= ftol:
                break
            a, b = m.df(sig_new, q_new), m.dg(sig_new, q_new)
            H, h = m.hardening(sig_new, q_new)
            Db = D @ b
            dl = fv / (a @ Db + H)
            sig_new = sig_new - dl * Db
            q_new = q_new + dl * h
        sig, q = sig_new, q_new
        T += dT
        fac = 0.9 * np.sqrt(s.stol / R) if R > 0 else 1.1
        dT = min(max(fac, 0.1), 1.1) * dT
    a, b = m.df(sig, q), m.dg(sig, q)
    H, _ = m.hardening(sig, q)
    Db, aD = D @ b, a @ D
    Dep = D - np.outer(Db, aD) / (aD @ b + H)
    return sig, q, Dep, 1, n


def batch(
    m: YieldModel,
    D: NDArray[np.float64],
    sig_n: NDArray[np.float64],
    q_n: NDArray[np.float64],
    deps: NDArray[np.float64],
    s: SubstepSettings | None = None,
) -> tuple[NDArray, NDArray, NDArray, NDArray[np.uint8]]:
    """Gauss-point loop (plain Python: intended as a fall-back, not a production path)."""
    n = sig_n.shape[0]
    sig = np.empty_like(sig_n)
    q = np.empty_like(q_n)
    Dt = np.empty((n, 4, 4))
    flag = np.zeros(n, dtype=np.uint8)
    for i in range(n):
        sig[i], q[i], Dt[i], flag[i], _ = integrate_substep(m, D, sig_n[i], q_n[i], deps[i], s)
    return sig, q, Dt, flag

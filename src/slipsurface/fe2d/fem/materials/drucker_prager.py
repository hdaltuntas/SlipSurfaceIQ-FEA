"""Drucker-Prager and von Mises — closed-form radial return (verification models).

    f = sqrt(J2) + alpha p - (k + H ep),    g = sqrt(J2) + beta p,    p = tr(sigma)/3

(tension positive). ``alpha = beta = 0`` is von Mises with ``k = sigma_y / sqrt(3)`` and
linear isotropic hardening ``H`` (in sqrt(J2) units per unit ``ep``). For the cone

    dgamma = f_tr / (G + K alpha beta + H)
    s = s_tr (1 - G dgamma / sqrt(J2_tr)),   p = p_tr - K beta dgamma

and the apex (``sqrt(J2_tr) < G dgamma``) returns to ``p = k / alpha``. The consistent
tangent is derived by linearising these expressions (checked against finite
differences in the tests).

Matching to Mohr-Coulomb (c, phi): ``"plane_strain"`` (collapse load in plane strain,
associated), ``"outer"`` (triaxial compression) or ``"inner"`` (triaxial extension).
"""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray

from ...core.enums import PlasticFlag
from .elastic import LinearElastic
from .mohr_coulomb import equivalent_plastic_strain

_M = np.array([1.0, 1.0, 1.0, 0.0])
_PD = np.array(  # engineering strain -> deviatoric strain (tensor shear)
    [
        [2 / 3, -1 / 3, -1 / 3, 0.0],
        [-1 / 3, 2 / 3, -1 / 3, 0.0],
        [-1 / 3, -1 / 3, 2 / 3, 0.0],
        [0.0, 0.0, 0.0, 0.5],
    ]
)
_W = np.array([1.0, 1.0, 1.0, 2.0])  # J2 = 1/2 s^T diag(W) s


def dp_parameters(c: float, phi: float, psi: float, match: str) -> tuple[float, float, float]:
    """(alpha, beta, k) for f = sqrt(J2) + alpha p - k from MC parameters (degrees)."""
    tp, tq = math.tan(math.radians(phi)), math.tan(math.radians(psi))
    sp, sq = math.sin(math.radians(phi)), math.sin(math.radians(psi))
    cp = math.cos(math.radians(phi))
    if match == "plane_strain":
        den = math.sqrt(9 + 12 * tp * tp)
        return 3 * tp / den, 3 * tq / math.sqrt(9 + 12 * tq * tq), 3 * c / den
    if match == "outer":
        return (
            3 * 2 * sp / (math.sqrt(3) * (3 - sp)),
            3 * 2 * sq / (math.sqrt(3) * (3 - sq)),
            6 * c * cp / (math.sqrt(3) * (3 - sp)),
        )
    if match == "inner":
        return (
            3 * 2 * sp / (math.sqrt(3) * (3 + sp)),
            3 * 2 * sq / (math.sqrt(3) * (3 + sq)),
            6 * c * cp / (math.sqrt(3) * (3 + sp)),
        )
    raise ValueError(f"unknown Drucker-Prager match '{match}'")


class DruckerPrager(LinearElastic):
    n_int = 1
    plastic = True

    def __init__(
        self,
        E: float,
        nu: float,
        alpha: float,
        beta: float,
        k: float,
        H: float = 0.0,
        phi_deg: float | None = None,
    ) -> None:
        super().__init__(E, nu, phi_deg)
        if alpha < 0 or beta < 0 or k < 0:
            raise ValueError("alpha, beta, k must be >= 0")
        self.alpha, self.beta, self.k0, self.H = float(alpha), float(beta), float(k), float(H)
        self.symmetric = abs(alpha - beta) < 1e-14
        self._Dinv = np.linalg.inv(self._D)

    @classmethod
    def from_mc(
        cls,
        E: float,
        nu: float,
        c: float,
        phi: float,
        psi: float = 0.0,
        match: str = "plane_strain",
    ) -> DruckerPrager:
        a, b, k = dp_parameters(c, phi, psi, match)
        return cls(E, nu, a, b, k, 0.0, phi)

    @classmethod
    def von_mises(cls, E: float, nu: float, sy: float, H: float = 0.0) -> VonMises:
        return VonMises(E, nu, sy, H)

    def yield_function(self, sig: NDArray[np.float64], ep: NDArray | float = 0.0) -> NDArray:
        p = sig[..., :3].sum(axis=-1) / 3.0
        s = sig - p[..., None] * _M
        rho = np.sqrt(0.5 * (s * s * _W).sum(axis=-1))
        return np.asarray(rho + self.alpha * p - (self.k0 + self.H * np.asarray(ep)))

    def integrate(
        self,
        sig_n: NDArray[np.float64],
        deps: NDArray[np.float64],
        q_n: NDArray[np.float64],
    ) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64], NDArray[np.uint8]]:
        G, K = self.G, self.K
        a, b, H = self.alpha, self.beta, self.H
        sig_tr = sig_n + deps @ self._D.T
        n = sig_tr.shape[0]
        ep = q_n[:, 0]
        p_tr = sig_tr[:, :3].sum(axis=1) / 3.0
        s_tr = sig_tr - p_tr[:, None] * _M
        rho = np.sqrt(0.5 * (s_tr * s_tr * _W).sum(axis=1))
        f_tr = rho + a * p_tr - (self.k0 + H * ep)
        tol = 1e-10 * np.maximum(np.abs(self.k0) + np.abs(p_tr) + rho, 1e-12)
        pl = f_tr > tol

        sig = sig_tr.copy()
        D = np.broadcast_to(self._D, (n, 4, 4)).copy()
        flag = np.zeros(n, dtype=np.uint8)
        q = q_n.copy()
        if not np.any(pl):
            return sig, q, D, flag

        i = np.flatnonzero(pl)
        den = G + K * a * b + H
        dg = f_tr[i] / den
        cone = rho[i] - G * dg > 0.0
        # ---- cone
        ic, dgc, rc = i[cone], dg[cone], rho[i][cone]
        fac = 1.0 - G * dgc / rc
        sig[ic] = s_tr[ic] * fac[:, None] + (p_tr[ic] - K * b * dgc)[:, None] * _M
        q[ic, 0] = ep[ic] + dgc
        flag[ic] = PlasticFlag.SHEAR
        # tangent
        st = s_tr[ic]
        nh = st * _W / (2.0 * rc[:, None])  # d rho = nh . ds
        dS = 2.0 * G * _PD  # ds_tr = dS deps
        drho = nh @ dS  # (m, 4)
        ddg = (drho + a * K * _M) / den  # (m, 4)
        Dc = (
            fac[:, None, None] * dS[None]
            + np.einsum(
                "mi,mj->mij", st, G * dgc[:, None] / rc[:, None] ** 2 * drho - G / rc[:, None] * ddg
            )
            + np.einsum("i,mj->mij", _M, K * _M[None, :] - K * b * ddg)
        )
        D[ic] = Dc
        # ---- apex (perfect plasticity at the apex; small residual stiffness)
        ia = i[~cone]
        if ia.size:
            if a <= 0.0:
                raise RuntimeError("von Mises return reached the apex (should not happen)")
            # hardening at the apex is ignored (apex of the current surface)
            p_ap = (self.k0 + H * ep[ia]) / a
            sig[ia] = p_ap[:, None] * _M
            dev = (p_tr[ia] - p_ap) / K  # plastic volumetric strain
            q[ia, 0] = ep[ia] + np.abs(dev)
            D[ia] = 1e-8 * self._D
            flag[ia] = PlasticFlag.APEX
        return sig, q, D, flag


class DPYield:
    """Drucker-Prager callbacks for the explicit substepping integrator."""

    def __init__(self, model: DruckerPrager) -> None:
        self.m = model

    def _sj(self, sig: NDArray[np.float64]) -> tuple[NDArray, float, float]:
        p = sig[:3].sum() / 3.0
        s = sig - p * _M
        return s, p, max(float(np.sqrt(0.5 * (s * s * _W).sum())), 1e-300)

    def f(self, sig: NDArray[np.float64], q: NDArray[np.float64]) -> float:
        s, p, rho = self._sj(sig)
        return rho + self.m.alpha * p - (self.m.k0 + self.m.H * q[0])

    def df(self, sig: NDArray[np.float64], q: NDArray[np.float64]) -> NDArray[np.float64]:
        s, _, rho = self._sj(sig)
        return np.asarray(s * _W / (2 * rho) + self.m.alpha / 3.0 * _M)

    def dg(self, sig: NDArray[np.float64], q: NDArray[np.float64]) -> NDArray[np.float64]:
        s, _, rho = self._sj(sig)
        return np.asarray(s * _W / (2 * rho) + self.m.beta / 3.0 * _M)

    def hardening(
        self, sig: NDArray[np.float64], q: NDArray[np.float64]
    ) -> tuple[float, NDArray[np.float64]]:
        # q[0] = multiplier (sqrt(J2)-conjugate plastic strain): dq = dlam
        return self.m.H, np.ones(1)


class VonMises(DruckerPrager):
    """von Mises with linear isotropic hardening; ``sy`` is the uniaxial yield stress,
    ``H`` the hardening modulus in uniaxial stress per unit equivalent plastic strain."""

    def __init__(self, E: float, nu: float, sy: float, H: float = 0.0) -> None:
        # sqrt(J2) = sy / sqrt(3); ep here is the multiplier dgamma (sqrt(J2)-conjugate)
        super().__init__(E, nu, 0.0, 0.0, sy / math.sqrt(3.0), H / 3.0)
        self.sy = float(sy)


__all__ = ["DPYield", "DruckerPrager", "VonMises", "dp_parameters", "equivalent_plastic_strain"]

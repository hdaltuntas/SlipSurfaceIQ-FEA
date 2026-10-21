"""Modified Cam-Clay — implicit return (Borja & Lee 1990), vectorised over Gauss points.

Compression-positive invariants ``p' = -tr(sigma)/3``, ``q = sqrt(3 J2)``:

    f = q^2 / M^2 + p' (p' - p_c)
    p' + a = (p'_n + a) exp(beta * deps_v^e),  beta = (1 + e0) / kappa  (logarithmic elasticity)
    p_c = p_c,n exp(theta * deps_v^p),  theta = (1 + e0) / (lambda - kappa)
    G = 3 K (1 - 2 nu) / (2 (1 + nu)),  K = beta (p'_n + a)            (constant within a step)

with ``deps_v`` compression positive. The plastic correction is associated:
``deps_v^p = dlam (2 p' - p_c)``, ``deps_s^p = dlam 2 q / M^2`` so that the deviatoric
stress returns radially, ``q = q_tr / (1 + 6 G dlam / M^2)``. The 3x3 local Newton on
``(p', p_c, dlam)`` converges quadratically; the consistent tangent follows from implicit
differentiation of the local system.

Internal variables: ``q[0]`` equivalent plastic strain, ``q[1]`` preconsolidation pressure
``p_c`` (0 = not yet initialised: the first call sets ``p_c`` from the current stress and
``OCR``: ``p_c = OCR (p' + q^2 / (M^2 p'))``). The small shift ``a = p_min`` of the
logarithmic elasticity keeps the stiffness finite at p' = 0 (stress-free start, gravity
analysis, undrained unloading towards p' = 0) while the stress update stays continuous.
"""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray

from ...core.enums import PlasticFlag
from ...core.errors import LocalIntegrationError
from .elastic import isotropic_D

_M = np.array([1.0, 1.0, 1.0, 0.0])
_W = np.array([1.0, 1.0, 1.0, 2.0])
_PD = np.array(  # engineering strain -> deviatoric (tensor) strain
    [
        [2 / 3, -1 / 3, -1 / 3, 0.0],
        [-1 / 3, 2 / 3, -1 / 3, 0.0],
        [-1 / 3, -1 / 3, 2 / 3, 0.0],
        [0.0, 0.0, 0.0, 0.5],
    ]
)


class ModifiedCamClay:
    n_int = 2
    plastic = True
    symmetric = False  # the algorithmic tangent of MCC is not symmetric in general

    def __init__(
        self,
        nu: float,
        M: float,
        lam: float,
        kappa: float,
        e0: float,
        OCR: float = 1.0,
        p_min: float = 1.0,
        p_ref: float = 100.0,
    ) -> None:
        if not (0 < kappa < lam) or M <= 0 or e0 <= 0 or OCR < 1.0 or not -1 < nu < 0.5:
            raise ValueError("MCC: need 0 < kappa < lambda, M > 0, e0 > 0, OCR >= 1")
        self.nu, self.M, self.lam, self.kappa, self.e0 = nu, M, lam, kappa, e0
        self.OCR, self.p_min, self.p_ref = OCR, p_min, p_ref
        self.beta = (1.0 + e0) / kappa
        self.theta = (1.0 + e0) / (lam - kappa)
        self.g_ratio = 3.0 * (1.0 - 2.0 * nu) / (2.0 * (1.0 + nu))  # G = g_ratio * K

    # elastic matrix at the reference pressure (initial-stiffness iterations, K0 default)
    def elastic_D(self) -> NDArray[np.float64]:
        K = self.beta * self.p_ref
        E = 9 * K * self.g_ratio * K / (3 * K + self.g_ratio * K)
        return isotropic_D(E, self.nu)

    def k0_default(self) -> float:
        # Jaky with the critical-state friction angle (triaxial compression)
        sphi = 3 * self.M / (6 + self.M)
        return 1.0 - sphi

    def yield_function(self, sig: NDArray, pc: NDArray) -> NDArray:
        p, q = _pq(sig)
        return np.asarray(q * q / self.M**2 + p * (p - pc))

    def initial_pc(self, sig: NDArray) -> NDArray:
        p, q = _pq(sig)
        p = np.maximum(p, self.p_min)
        return np.asarray(self.OCR * (p + q * q / (self.M**2 * p)))

    def integrate(
        self,
        sig_n: NDArray[np.float64],
        deps: NDArray[np.float64],
        q_n: NDArray[np.float64],
    ) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64], NDArray[np.uint8]]:
        M2 = self.M**2
        n = sig_n.shape[0]
        q_out = q_n.copy()
        pc_n = q_n[:, 1].copy()
        fresh = pc_n <= 0
        if np.any(fresh):
            pc_n[fresh] = self.initial_pc(sig_n[fresh])
            q_out[fresh, 1] = pc_n[fresh]
        a_sh = self.p_min
        p_n, _ = _pq(sig_n)
        p_n = np.maximum(p_n, 0.0)  # admissible states have p' >= 0
        s_n = sig_n - (sig_n[:, :3].sum(axis=1) / 3.0)[:, None] * _M
        K_n = self.beta * (p_n + a_sh)
        G = self.g_ratio * K_n
        dev = -deps[:, :3].sum(axis=1)  # compression positive volumetric increment
        if np.abs(self.beta * dev).max(initial=0.0) > 30.0:  # e^30: no meaningful state
            raise LocalIntegrationError("MCC: volumetric strain increment too large")
        p_tr = (p_n + a_sh) * np.exp(self.beta * dev) - a_sh
        s_tr = s_n + 2.0 * G[:, None] * (deps @ _PD.T)
        snorm = np.sqrt((s_tr * s_tr * _W).sum(axis=1))
        q_tr = math.sqrt(1.5) * snorm
        f_tr = q_tr**2 / M2 + p_tr * (p_tr - pc_n)

        sig = -p_tr[:, None] * _M + s_tr
        D = np.empty((n, 4, 4))
        # elastic tangent: dp = beta p_tr d(dev), ds = 2G PD deps
        D[:] = 2.0 * G[:, None, None] * _PD[None]
        D += (self.beta * (p_tr + a_sh))[:, None, None] * np.outer(_M, _M)[None]
        flag = np.zeros(n, dtype=np.uint8)
        tol = 1e-10 * np.maximum(pc_n * pc_n, 1e-12)
        pl = np.flatnonzero(f_tr > tol)
        if pl.size == 0:
            return sig, q_out, D, flag

        # ---------------------------------------------------- local Newton (p, pc, dlam)
        pn, pcn, Gp, qt, dv = p_n[pl], pc_n[pl], G[pl], q_tr[pl], dev[pl]
        p, pc, dl = p_tr[pl].copy(), pcn.copy(), np.zeros(pl.size)
        b, th = self.beta, self.theta
        for _ in range(50):
            if not (np.all(np.isfinite(p)) and np.all(np.isfinite(pc))):
                raise LocalIntegrationError("MCC local Newton diverged")
            a = 1.0 + 6.0 * Gp * dl / M2
            q = qt / a
            evp = dl * (2 * p - pc)
            E1 = (pn + a_sh) * np.exp(np.clip(b * (dv - evp), -50.0, 50.0)) - a_sh
            E2 = pcn * np.exp(np.clip(th * evp, -50.0, 50.0))
            r = np.stack([p - E1, pc - E2, q * q / M2 + p * (p - pc)], axis=1)
            J = np.empty((pl.size, 3, 3))
            # d(evp)/d(p, pc, dl) = (2 dl, -dl, 2p - pc)
            de = np.stack([2 * dl, -dl, 2 * p - pc], axis=1)
            J[:, 0, :] = b * (E1 + a_sh)[:, None] * de
            J[:, 0, 0] += 1.0
            J[:, 1, :] = -th * E2[:, None] * de
            J[:, 1, 1] += 1.0
            dq_ddl = -qt * 6.0 * Gp / M2 / a**2
            J[:, 2, 0] = 2 * p - pc
            J[:, 2, 1] = -p
            J[:, 2, 2] = 2 * q / M2 * dq_ddl
            dx = np.linalg.solve(J, -r[..., None])[..., 0]
            p, pc, dl = p + dx[:, 0], pc + dx[:, 1], np.maximum(dl + dx[:, 2], 0.0)
            p = np.maximum(p, 1e-12 * pcn)
            pc = np.maximum(pc, 1e-12 * pcn)
            if np.all(np.abs(r) <= 1e-10 * np.maximum(pcn, 1.0)[:, None] ** np.array([1, 1, 2])):
                break
        else:
            raise LocalIntegrationError("MCC local Newton did not converge")
        a = 1.0 + 6.0 * Gp * dl / M2
        q = qt / a
        nhat = s_tr[pl] / np.maximum(snorm[pl], 1e-300)[:, None]
        sig[pl] = -p[:, None] * _M + math.sqrt(2.0 / 3.0) * q[:, None] * nhat
        q_out[pl, 1] = pc
        q_out[pl, 0] += dl * 2 * q / M2  # deviatoric plastic strain measure
        flag[pl] = PlasticFlag.SHEAR

        # ------------------------------------------------------- consistent tangent
        evp = dl * (2 * p - pc)
        E1 = (pn + a_sh) * np.exp(b * (dv - evp)) - a_sh
        E2 = pcn * np.exp(th * evp)
        de = np.stack([2 * dl, -dl, 2 * p - pc], axis=1)
        J = np.empty((pl.size, 3, 3))
        J[:, 0, :] = b * (E1 + a_sh)[:, None] * de
        J[:, 0, 0] += 1.0
        J[:, 1, :] = -th * E2[:, None] * de
        J[:, 1, 1] += 1.0
        dq_ddl = -qt * 6.0 * Gp / M2 / a**2
        J[:, 2, 0] = 2 * p - pc
        J[:, 2, 1] = -p
        J[:, 2, 2] = 2 * q / M2 * dq_ddl
        # dR / d(dev, q_tr)
        dR = np.zeros((pl.size, 3, 2))
        dR[:, 0, 0] = -b * (E1 + a_sh)
        dR[:, 2, 1] = 2 * q / M2 * (1.0 / a)
        dx = -np.linalg.solve(J, dR)  # (m, 3, 2): d(p, pc, dl)/d(dev, q_tr)
        dp = dx[:, 0, :]
        dq = dx[:, 2, :] * dq_ddl[:, None]
        dq[:, 1] += 1.0 / a
        # strain derivatives of the inputs
        PDT = _PD  # ds_tr = 2G PD deps
        d_dev = -_M  # d(dev)/deps
        d_qtr = math.sqrt(1.5) * 2.0 * Gp[:, None] * ((nhat * _W) @ PDT)  # (m, 4)
        dp_de = dp[:, 0:1] * d_dev[None] + dp[:, 1:2] * d_qtr
        dq_de = dq[:, 0:1] * d_dev[None] + dq[:, 1:2] * d_qtr
        c = math.sqrt(2.0 / 3.0)
        dn = (np.eye(4)[None] - np.einsum("mi,mj->mij", nhat, nhat * _W)) / np.maximum(
            snorm[pl], 1e-300
        )[:, None, None]
        dn_de = np.einsum("mij,mjk->mik", dn, 2.0 * Gp[:, None, None] * PDT[None])
        D[pl] = (
            -np.einsum("i,mj->mij", _M, dp_de)
            + c * np.einsum("mi,mj->mij", nhat, dq_de)
            + c * q[:, None, None] * dn_de
        )
        return sig, q_out, D, flag


def _pq(sig: NDArray[np.float64]) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Compression-positive mean stress and deviatoric invariant q of (..., 4) stresses."""
    p = -sig[..., :3].sum(axis=-1) / 3.0
    s = sig + p[..., None] * _M
    q = np.sqrt(1.5 * (s * s * _W).sum(axis=-1))
    return p, q

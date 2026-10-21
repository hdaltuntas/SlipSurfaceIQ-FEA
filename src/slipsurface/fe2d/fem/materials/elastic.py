"""Isotropic linear elasticity (plane strain / axisymmetric, 4-component)."""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray


def isotropic_D(E: float, nu: float) -> NDArray[np.float64]:
    """4x4 elastic matrix for ``[sxx, syy, szz, txy]`` with engineering shear strain."""
    lam = E * nu / ((1.0 + nu) * (1.0 - 2.0 * nu))
    G = E / (2.0 * (1.0 + nu))
    D = np.zeros((4, 4))
    D[:3, :3] = lam
    D[0, 0] = D[1, 1] = D[2, 2] = lam + 2.0 * G
    D[3, 3] = G
    return D


class LinearElastic:
    n_int = 0

    def __init__(self, E: float, nu: float, phi_deg: float | None = None) -> None:
        self.E = float(E)
        self.nu = float(nu)
        self._phi = phi_deg
        self._D = isotropic_D(self.E, self.nu)

    @property
    def G(self) -> float:
        return self.E / (2.0 * (1.0 + self.nu))

    @property
    def K(self) -> float:
        return self.E / (3.0 * (1.0 - 2.0 * self.nu))

    def elastic_D(self) -> NDArray[np.float64]:
        return self._D

    def integrate(
        self,
        sig_n: NDArray[np.float64],
        deps: NDArray[np.float64],
        q_n: NDArray[np.float64],
    ) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64], NDArray[np.uint8]]:
        sig = sig_n + deps @ self._D.T
        D = np.broadcast_to(self._D, (sig.shape[0], 4, 4))
        return sig, q_n, D, np.zeros(sig.shape[0], dtype=np.uint8)

    def k0_default(self) -> float:
        if self._phi is not None:
            return 1.0 - math.sin(math.radians(self._phi))
        return self.nu / (1.0 - self.nu)

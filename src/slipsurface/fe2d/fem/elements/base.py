"""Common isoparametric continuum element machinery.

Every continuum element supplies its shape functions on the reference domain; the
vectorised :meth:`IsoElement.precompute` turns a whole block into Gauss-point arrays
(B matrices, integration weights, Gauss point coordinates) in one shot. No per-element
Python loop is executed.

B matrix rows: ``[exx, eyy, ezz, gxy]``; columns: ``[ux0, uy0, ux1, uy1, ...]``.
Plane strain: the ezz row is zero. Axisymmetric (x = r, y = z): ezz = e_theta = sum N_i u_ri / r
and the integration weight carries r (quantities are per radian).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from ...core.enums import Analysis
from ...core.errors import MeshError
from .quadrature import Rule


@dataclass(frozen=True, eq=False)
class GeomCache:
    """Gauss-point geometry of one element block (computed once per stage)."""

    B: NDArray[np.float64]  # (ne, ngp, 4, 2*nen)
    wdet: NDArray[np.float64]  # (ne, ngp)  w * detJ * t
    N: NDArray[np.float64]  # (ngp, nen)
    xg: NDArray[np.float64]  # (ne, ngp, 2) Gauss point coordinates

    @property
    def ne(self) -> int:
        return int(self.B.shape[0])

    @property
    def ngp(self) -> int:
        return int(self.B.shape[1])


class ElementKernel(Protocol):
    nen: int

    def rule(self, order: str = "default") -> Rule: ...

    def precompute(
        self,
        coords: NDArray[np.float64],
        conn: NDArray[np.int64],
        analysis: Analysis,
        order: str = "default",
    ) -> GeomCache: ...


class IsoElement:
    """Base class: subclasses implement :meth:`shape` and :meth:`rule`."""

    nen: int = 0
    name: str = ""

    def shape(self, xi: NDArray[np.float64]) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Return ``N (npt, nen)`` and ``dN/dxi (npt, nen, 2)`` at reference points ``xi``."""
        raise NotImplementedError

    def rule(self, order: str = "default") -> Rule:
        raise NotImplementedError

    def precompute(
        self,
        coords: NDArray[np.float64],
        conn: NDArray[np.int64],
        analysis: Analysis,
        order: str = "default",
    ) -> GeomCache:
        rule = self.rule(order)
        N, dN = self.shape(rule.points)  # (g, n), (g, n, 2)
        X = coords[conn]  # (e, n, 2)

        # J[e,g,i,j] = d x_j / d xi_i
        J = np.einsum("gni,enj->egij", dN, X, optimize=True)
        detJ = J[..., 0, 0] * J[..., 1, 1] - J[..., 0, 1] * J[..., 1, 0]
        if np.any(detJ <= 0.0):
            e_bad = int(np.flatnonzero((detJ <= 0.0).any(axis=1))[0])
            raise MeshError(f"{self.name}: non-positive Jacobian in element {e_bad}")
        inv = np.empty_like(J)
        inv[..., 0, 0] = J[..., 1, 1]
        inv[..., 1, 1] = J[..., 0, 0]
        inv[..., 0, 1] = -J[..., 0, 1]
        inv[..., 1, 0] = -J[..., 1, 0]
        inv /= detJ[..., None, None]
        dNdx = np.einsum("egij,gnj->egni", inv, dN, optimize=True)  # (e, g, n, 2)

        xg = np.einsum("gn,enj->egj", N, X, optimize=True)
        ne, ngp, nen = X.shape[0], rule.ngp, self.nen
        B = np.zeros((ne, ngp, 4, 2 * nen))
        B[:, :, 0, 0::2] = dNdx[..., 0]
        B[:, :, 1, 1::2] = dNdx[..., 1]
        B[:, :, 3, 0::2] = dNdx[..., 1]
        B[:, :, 3, 1::2] = dNdx[..., 0]

        wdet = detJ * rule.weights[None, :]
        if analysis is Analysis.AXISYMMETRIC:
            r = xg[..., 0]
            if np.any(r <= 0.0):
                raise MeshError("axisymmetric analysis requires x = r > 0 at all Gauss points")
            B[:, :, 2, 0::2] = N[None, :, :] / r[..., None]
            wdet = wdet * r
        return GeomCache(B=B, wdet=wdet, N=N, xg=xg)

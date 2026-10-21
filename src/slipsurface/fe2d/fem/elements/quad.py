"""Q4 (bilinear, B-bar) and Q8 (serendipity) quadrilaterals.

Node order: corners 0-1-2-3 counter-clockwise at (-1,-1), (1,-1), (1,1), (-1,1); Q8
mid-sides 4 (0-1), 5 (1-2), 6 (2-3), 7 (3-0).

Q4 uses 2x2 Gauss points with the B-bar method (Hughes 1980): the volumetric part of
B is replaced by its element average, which removes volumetric locking in undrained and
plastic (isochoric) flow. In plane strain only the in-plane volumetric strain
``exx + eyy`` is averaged (``ezz`` stays exactly zero); in axisymmetry the full trace.

Q8 uses 2x2 reduced integration by default (recommended for plasticity; the spurious
mode of a single element cannot propagate in a mesh) and 3x3 with ``order="high"``.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from ...core.enums import Analysis
from .base import GeomCache, IsoElement
from .quadrature import Rule, quad_rule

_XI = np.array([[-1.0, -1.0], [1.0, -1.0], [1.0, 1.0], [-1.0, 1.0]])


class Quad4(IsoElement):
    nen = 4
    name = "Q4"

    def __init__(self, bbar: bool = True) -> None:
        self.bbar = bbar

    def shape(self, xi: NDArray[np.float64]) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        xi = np.atleast_2d(xi)
        s, t = xi[:, 0:1], xi[:, 1:2]
        a, b = _XI[:, 0][None, :], _XI[:, 1][None, :]
        N = 0.25 * (1 + a * s) * (1 + b * t)
        dN = np.empty((xi.shape[0], 4, 2))
        dN[:, :, 0] = 0.25 * a * (1 + b * t)
        dN[:, :, 1] = 0.25 * b * (1 + a * s)
        return N, dN

    def rule(self, order: str = "default") -> Rule:
        return quad_rule(2 if order == "default" else 3)

    def precompute(
        self,
        coords: NDArray[np.float64],
        conn: NDArray[np.int64],
        analysis: Analysis,
        order: str = "default",
    ) -> GeomCache:
        g = super().precompute(coords, conn, analysis, order)
        if not self.bbar:
            return g
        B = g.B.copy()
        rows = 3 if analysis is Analysis.AXISYMMETRIC else 2
        bv = B[:, :, :rows, :].sum(axis=2)  # (ne, ngp, nd) volumetric row
        bv_bar = np.einsum("eg,egd->ed", g.wdet, bv) / g.wdet.sum(axis=1)[:, None]
        corr = (bv_bar[:, None, :] - bv) / rows
        B[:, :, :rows, :] += corr[:, :, None, :]
        return GeomCache(B=B, wdet=g.wdet, N=g.N, xg=g.xg)


class Quad8(IsoElement):
    nen = 8
    name = "Q8"

    def shape(self, xi: NDArray[np.float64]) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        xi = np.atleast_2d(xi)
        s, t = xi[:, 0], xi[:, 1]
        n = xi.shape[0]
        N = np.empty((n, 8))
        dN = np.empty((n, 8, 2))
        for i, (a, b) in enumerate(_XI):  # corners
            N[:, i] = 0.25 * (1 + a * s) * (1 + b * t) * (a * s + b * t - 1)
            dN[:, i, 0] = 0.25 * a * (1 + b * t) * (2 * a * s + b * t)
            dN[:, i, 1] = 0.25 * b * (1 + a * s) * (a * s + 2 * b * t)
        # mid-sides 4 (t=-1), 6 (t=+1): xi = 0 lines; 5 (s=+1), 7 (s=-1)
        for i, b in ((4, -1.0), (6, 1.0)):
            N[:, i] = 0.5 * (1 - s * s) * (1 + b * t)
            dN[:, i, 0] = -s * (1 + b * t)
            dN[:, i, 1] = 0.5 * b * (1 - s * s)
        for i, a in ((5, 1.0), (7, -1.0)):
            N[:, i] = 0.5 * (1 + a * s) * (1 - t * t)
            dN[:, i, 0] = 0.5 * a * (1 - t * t)
            dN[:, i, 1] = -t * (1 + a * s)
        return N, dN

    def rule(self, order: str = "default") -> Rule:
        return quad_rule(2 if order == "default" else 3)


def quad_corner_extrapolation(rule: Rule) -> NDArray[np.float64]:
    """(4, ngp) bilinear least-squares extrapolation from Gauss points to the corners."""
    p = rule.points
    A = np.column_stack([np.ones(len(p)), p[:, 0], p[:, 1], p[:, 0] * p[:, 1]])
    C = np.column_stack([np.ones(4), _XI[:, 0], _XI[:, 1], _XI[:, 0] * _XI[:, 1]])
    return np.asarray(C @ np.linalg.pinv(A))

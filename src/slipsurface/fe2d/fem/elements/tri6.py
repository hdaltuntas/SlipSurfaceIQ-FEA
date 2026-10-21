"""T6 — 6-node quadratic triangle (LST), the default continuum element.

Node order: corners 0, 1, 2 (counter-clockwise), mid-sides 3 (0-1), 4 (1-2), 5 (2-0).
Default rule: 3 Gauss points (exact for B^T D B on straight-sided elements).
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from .base import IsoElement
from .quadrature import Rule, tri_rule


class Tri6(IsoElement):
    nen = 6
    name = "T6"

    def shape(self, xi: NDArray[np.float64]) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        xi = np.atleast_2d(xi)
        s, t = xi[:, 0], xi[:, 1]
        L1, L2, L3 = 1.0 - s - t, s, t
        N = np.column_stack(
            [
                L1 * (2 * L1 - 1),
                L2 * (2 * L2 - 1),
                L3 * (2 * L3 - 1),
                4 * L1 * L2,
                4 * L2 * L3,
                4 * L3 * L1,
            ]
        )
        # dL/ds = (-1, 1, 0), dL/dt = (-1, 0, 1)
        dN = np.empty((xi.shape[0], 6, 2))
        dN[:, 0, 0] = -(4 * L1 - 1)
        dN[:, 0, 1] = -(4 * L1 - 1)
        dN[:, 1, 0] = 4 * L2 - 1
        dN[:, 1, 1] = 0.0
        dN[:, 2, 0] = 0.0
        dN[:, 2, 1] = 4 * L3 - 1
        dN[:, 3, 0] = 4 * (L1 - L2)
        dN[:, 3, 1] = -4 * L2
        dN[:, 4, 0] = 4 * L3
        dN[:, 4, 1] = 4 * L2
        dN[:, 5, 0] = -4 * L3
        dN[:, 5, 1] = 4 * (L1 - L3)
        return N, dN

    def rule(self, order: str = "default") -> Rule:
        return tri_rule(3 if order == "default" else 6)

    @staticmethod
    def corner_extrapolation(rule: Rule) -> NDArray[np.float64]:
        """Matrix E (3, ngp) mapping GP values to corner values by a linear fit.

        For the 3-point rule this is the exact inverse of the linear interpolation at the
        Gauss points; for larger rules it is the least-squares linear fit.
        """
        p = rule.points
        A = np.column_stack([1.0 - p[:, 0] - p[:, 1], p[:, 0], p[:, 1]])  # (g, 3)
        return np.linalg.pinv(A)  # (3, g)

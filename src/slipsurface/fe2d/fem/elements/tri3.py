"""T3 — 3-node linear triangle (CST).

Suitable for seepage and testing. Locks volumetrically in undrained / plastic flow.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from .base import IsoElement
from .quadrature import Rule, tri_rule


class Tri3(IsoElement):
    nen = 3
    name = "T3"

    def shape(self, xi: NDArray[np.float64]) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        xi = np.atleast_2d(xi)
        s, t = xi[:, 0], xi[:, 1]
        N = np.column_stack([1.0 - s - t, s, t])
        dN = np.empty((xi.shape[0], 3, 2))
        dN[:, :, 0] = [-1.0, 1.0, 0.0]
        dN[:, :, 1] = [-1.0, 0.0, 1.0]
        return N, dN

    def rule(self, order: str = "default") -> Rule:
        return tri_rule(1 if order == "default" else 3)

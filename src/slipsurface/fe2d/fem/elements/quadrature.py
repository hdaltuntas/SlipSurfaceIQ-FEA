"""Quadrature rules.

Triangle rules are on the reference triangle (0,0)-(1,0)-(0,1); weights sum to its area 1/2.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, eq=False)
class Rule:
    points: NDArray[np.float64]  # (ngp, dim)
    weights: NDArray[np.float64]  # (ngp,)
    degree: int

    @property
    def ngp(self) -> int:
        return int(self.weights.shape[0])


def tri_rule(npts: int) -> Rule:
    """Symmetric triangle rules: 1 (deg 1), 3 (deg 2), 6 (deg 4, Dunavant), 7 (deg 5)."""
    if npts == 1:
        return Rule(np.array([[1 / 3, 1 / 3]]), np.array([0.5]), 1)
    if npts == 3:
        p = np.array([[1 / 6, 1 / 6], [2 / 3, 1 / 6], [1 / 6, 2 / 3]])
        return Rule(p, np.full(3, 1 / 6), 2)
    if npts == 6:
        a, wa = 0.445948490915965, 0.223381589678011
        b, wb = 0.091576213509771, 0.109951743655322
        p = np.array(
            [[a, a], [1 - 2 * a, a], [a, 1 - 2 * a], [b, b], [1 - 2 * b, b], [b, 1 - 2 * b]]
        )
        return Rule(p, 0.5 * np.array([wa, wa, wa, wb, wb, wb]), 4)
    if npts == 7:
        a1, b1, w1 = 0.059715871789770, 0.470142064105115, 0.132394152788506
        a2, b2, w2 = 0.797426985353087, 0.101286507323456, 0.125939180544827
        p = np.array(
            [
                [1 / 3, 1 / 3],
                [b1, b1],
                [a1, b1],
                [b1, a1],
                [b2, b2],
                [a2, b2],
                [b2, a2],
            ]
        )
        w = np.array([0.225, w1, w1, w1, w2, w2, w2])
        return Rule(p, 0.5 * w, 5)
    raise ValueError(f"no triangle rule with {npts} points")


@lru_cache(maxsize=16)
def gauss_legendre(n: int) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """1D Gauss-Legendre on [-1, 1]."""
    x, w = np.polynomial.legendre.leggauss(n)
    return x, w


def quad_rule(n: int) -> Rule:
    """Tensor-product n x n Gauss rule on [-1, 1]^2."""
    x, w = gauss_legendre(n)
    X, Y = np.meshgrid(x, x, indexing="ij")
    W = np.outer(w, w)
    return Rule(np.column_stack([X.ravel(), Y.ravel()]), W.ravel(), 2 * n - 1)

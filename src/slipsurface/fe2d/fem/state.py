"""Solver state container with commit/rollback semantics."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray


@dataclass
class SolverState:
    u: NDArray[np.float64]  # (ndof,) total displacement
    sig: dict[str, NDArray[np.float64]]  # block tag -> (ne, ngp, 4) effective stress
    q: dict[str, NDArray[np.float64]] = field(default_factory=dict)
    eps_p: dict[str, NDArray[np.float64]] = field(default_factory=dict)
    pore: dict[str, NDArray[np.float64]] = field(default_factory=dict)
    plastic: dict[str, NDArray[np.uint8]] = field(default_factory=dict)
    u_ref: NDArray[np.float64] | None = None  # displacement datum for reporting

    def commit(self) -> SolverState:
        return copy.deepcopy(self)

    def reported_u(self) -> NDArray[np.float64]:
        return self.u if self.u_ref is None else self.u - self.u_ref

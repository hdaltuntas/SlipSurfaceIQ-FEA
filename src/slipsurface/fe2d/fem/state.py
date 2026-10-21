"""Solver state container with commit/rollback semantics.

Displacements are stored per node, ``u[nn, 3] = (ux, uy, theta)``, because the global DOF
numbering changes whenever the active element set changes. Element state arrays always
cover the full blocks; inactive elements keep zero stress.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray


@dataclass
class SolverState:
    u: NDArray[np.float64]  # (nn, 3) total nodal displacement / rotation
    sig: dict[str, NDArray[np.float64]]  # continuum tag -> (ne, ngp, 4) effective stress
    q: dict[str, NDArray[np.float64]] = field(default_factory=dict)  # (ne, ngp, nq)
    plastic: dict[str, NDArray[np.uint8]] = field(default_factory=dict)  # (ne, ngp)
    struct: dict[str, dict[str, NDArray[np.float64]]] = field(default_factory=dict)
    struct_flag: dict[str, NDArray[np.uint8]] = field(default_factory=dict)
    active: dict[str, NDArray[np.bool_]] = field(default_factory=dict)  # block tag -> (ne,)
    u_ref: NDArray[np.float64] | None = None  # (nn, 3) displacement datum for reporting

    def commit(self) -> SolverState:
        return copy.deepcopy(self)

    def reported_u(self) -> NDArray[np.float64]:
        return self.u if self.u_ref is None else self.u - self.u_ref

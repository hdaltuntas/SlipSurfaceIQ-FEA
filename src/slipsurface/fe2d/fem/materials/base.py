"""Constitutive model interface.

All models work on batches of Gauss points so the solver never loops in Python:
``integrate(sig_n (ngp,4), deps (ngp,4), q_n (ngp,n_int)) -> sig, q, D_alg (ngp,4,4), flag``.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np
from numpy.typing import NDArray


class ConstitutiveModel(Protocol):
    n_int: int

    def elastic_D(self) -> NDArray[np.float64]: ...

    def integrate(
        self,
        sig_n: NDArray[np.float64],
        deps: NDArray[np.float64],
        q_n: NDArray[np.float64],
    ) -> tuple[
        NDArray[np.float64], NDArray[np.float64], NDArray[np.float64], NDArray[np.uint8]
    ]: ...

    def k0_default(self) -> float: ...

"""Sparse direct linear solvers behind one small interface.

Default: SciPy SuperLU (``splu``) with a symmetric-friendly column ordering.
Optional: Intel MKL PARDISO through ``pypardiso`` (``pip install slipsurface-fe2d[fast]``).
"""

from __future__ import annotations

from typing import Protocol

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
from numpy.typing import NDArray

from ..core.errors import SingularSystemError


class Factorization(Protocol):
    def solve(self, b: NDArray[np.float64]) -> NDArray[np.float64]: ...


PIVOT_TOL = 1e-12
"""A pivot smaller than ``PIVOT_TOL`` x its original diagonal entry signals a mechanism."""

_SINGULAR_MSG = "stiffness matrix is singular — check boundary conditions (rigid body mode?)"


class _SuperLU:
    def __init__(self, K: sp.spmatrix) -> None:
        Kc = sp.csc_matrix(K)
        try:
            self._lu = spla.splu(
                Kc,
                permc_spec="MMD_AT_PLUS_A",
                diag_pivot_thresh=0.0,
                options={"SymmetricMode": True},
            )
        except RuntimeError as exc:  # "Factor is exactly singular"
            raise SingularSystemError(_SINGULAR_MSG) from exc
        # Round-off turns an exact zero pivot into a tiny one. With diagonal pivoting each
        # pivot is compared with the diagonal entry it came from. SciPy: Pr A Pc = L U with
        # Pc[i, perm_c[i]] = 1, i.e. original column i sits at position perm_c[i].
        piv = np.abs(self._lu.U.diagonal())
        diag_at_pos = np.empty(Kc.shape[0])
        diag_at_pos[self._lu.perm_c] = np.abs(Kc.diagonal())
        ratio = piv / np.maximum(diag_at_pos, np.finfo(float).tiny)
        if np.any(ratio < PIVOT_TOL):
            raise SingularSystemError(_SINGULAR_MSG)

    def solve(self, b: NDArray[np.float64]) -> NDArray[np.float64]:
        x = self._lu.solve(b)
        if not np.all(np.isfinite(x)):
            raise SingularSystemError("non-finite solution — stiffness is (near) singular")
        return x


class _Pardiso:
    def __init__(self, K: sp.spmatrix) -> None:
        import pypardiso  # type: ignore[import-not-found]

        self._solver = pypardiso.PyPardisoSolver()
        self._K = sp.csr_matrix(K)
        self._solver.factorize(self._K)

    def solve(self, b: NDArray[np.float64]) -> NDArray[np.float64]:
        return np.asarray(self._solver.solve(self._K, b))


def _pardiso_available() -> bool:
    try:
        import pypardiso  # type: ignore[import-not-found]  # noqa: F401
    except Exception:
        return False
    return True


def factorize(K: sp.spmatrix, method: str = "auto") -> Factorization:
    if method == "pardiso" or (method == "auto" and _pardiso_available()):
        return _Pardiso(K)
    return _SuperLU(K)

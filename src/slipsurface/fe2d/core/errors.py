"""Exception hierarchy (L0)."""

from __future__ import annotations


class SlipSurfaceError(Exception):
    """Base class for all SlipSurface 2D errors."""


class ModelError(SlipSurfaceError):
    """Inconsistent or invalid model definition (missing material, unknown set, ...)."""


class MeshError(SlipSurfaceError):
    """Invalid mesh: inverted elements, bad connectivity, unknown node/edge sets."""


class SolverError(SlipSurfaceError):
    """Numerical failure inside the solver (singular stiffness, ...)."""


class SingularSystemError(SolverError):
    """Global stiffness is singular — usually an under-constrained model (rigid body mode)."""


class NonConvergence(SolverError):
    """Nonlinear iteration did not converge; ``lam`` is the last converged load factor."""

    def __init__(self, lam: float, message: str | None = None) -> None:
        self.lam = lam
        super().__init__(message or f"no convergence; last converged load factor = {lam:.4f}")

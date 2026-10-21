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

    def __init__(self, lam: float, message: str | None = None, history: object = None) -> None:
        self.lam = lam
        self.history = history  # StageHistory of the failed stage (step records)
        super().__init__(message or f"no convergence; last converged load factor = {lam:.4f}")


class LocalIntegrationError(SolverError):
    """A constitutive update failed for the given strain increment (e.g. the local Newton
    of an implicit return diverged). The global solver treats the iterate as divergent and
    backtracks / cuts the load step."""

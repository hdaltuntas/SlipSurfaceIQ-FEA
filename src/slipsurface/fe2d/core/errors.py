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


class MaterialIntegrationError(SolverError):
    """A local constitutive return failed; its trial state must not be committed."""

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        self.details = details
        super().__init__(message)


class NonConvergence(SolverError):
    """Nonlinear failure; ``lam`` is last committed, ``history`` holds attempts if available."""

    def __init__(
        self, lam: float, message: str | None = None, *, history: object | None = None
    ) -> None:
        self.lam = lam
        # The nonlinear layer supplies StageHistory; L0 must not import L3.
        self.history = history
        super().__init__(message or f"no convergence; last converged load factor = {lam:.4f}")


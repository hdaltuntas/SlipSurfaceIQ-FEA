"""Optional, GUI-independent progress and cooperative cancellation contract."""
from __future__ import annotations

from dataclasses import dataclass

from ..core.errors import SolverError


class SolveCancelled(SolverError):
    """The caller cancelled a solve; this is neither convergence nor collapse."""


@dataclass(frozen=True)
class SolveProgress:
    stage: str
    stage_index: int
    stage_count: int
    lam: float = 0.0
    iteration: int = 0
    residual: float | None = None
    accepted: bool = False
    completed: bool = False

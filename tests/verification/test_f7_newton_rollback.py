"""F7: exact commit/rollback contract of adaptive Newton load increments.

The one-DOF manufactured nonlinear stage has equilibrium f_int = u and
f_ext = 1, so the exact final state is u=1 at lambda=1. Its local integrator
intentionally refuses trial increments larger than 0.30 to simulate a
constitutive return failure. Rejected trial states must never be committed;
the solver must cut the increment, retry, and still reach the exact solution.

This is a deterministic *driver* contract, not a surrogate for real
Mohr–Coulomb excavation convergence or geotechnical field verification.
"""

from __future__ import annotations

import numpy as np
import pytest

from slipsurface.fe2d.core.errors import MaterialIntegrationError, NonConvergence
from slipsurface.fe2d.fem.nonlinear import Problem, solve_stage
from slipsurface.fe2d.model.stages import SolverSettings


class UnitFactor:
    Kfp = np.zeros((1, 0))

    def solve(self, rhs):
        return np.asarray(rhs, dtype=float).copy()


class BoundedIncrement:
    """Manufactured constitutive state with explicit trial/committed separation."""

    def __init__(self, max_increment):
        self.max_increment = float(max_increment)
        self.committed = 0.0
        self.commits = []
        self.rejected_trials = []

    def integrate(self, delta):
        delta = float(delta[0])
        if abs(delta) > self.max_increment + 1e-12:
            self.rejected_trials.append((self.committed, delta))
            raise MaterialIntegrationError(
                "intentional overlarge trial",
                details={"max_increment": self.max_increment},
            )
        trial = self.committed + delta
        return trial, np.array([trial], dtype=float)

    def commit(self, trial, total):
        self.committed = float(trial)
        self.commits.append((float(trial), float(total[0])))

    def problem(self):
        return Problem(
            ndof=1,
            free=np.array([0], dtype=np.int64),
            prescribed=np.array([], dtype=np.int64),
            integrate=self.integrate,
            factor=lambda _kind, _trial: UnitFactor(),
            commit=self.commit,
        )


def settings():
    return SolverSettings(
        method="NR",
        dlam0=0.5,
        dlam_min=0.01,
        dlam_max=0.5,
        tol_force=1e-9,
        tol_energy=1e-9,
    )


def test_rejected_constitutive_trials_do_not_modify_committed_state():
    mock = BoundedIncrement(0.30)
    trial, delta, history = solve_stage(
        mock.problem(),
        f_ext=np.array([1.0]),
        f0=np.array([0.0]),
        du_presc=np.zeros(0),
        settings=settings(),
        linear=False,
    )
    assert mock.rejected_trials, "The first 0.5 step must be rejected"
    assert all(0 <= state <= 1.0 for state, _ in mock.rejected_trials)
    assert all(abs(increment) > 0.30 for _, increment in mock.rejected_trials)
    assert trial == pytest.approx(1.0, abs=1e-9)
    assert delta[0] == pytest.approx(1.0, abs=1e-9)
    assert mock.committed == pytest.approx(1.0, abs=1e-9)
    assert history.steps[-1].converged
    assert history.steps[-1].lam == pytest.approx(1.0)
    assert any(not record.converged for record in history.steps)
    assert all(
        record.termination == "material_return"
        for record in history.steps if not record.converged
    )
    assert len(mock.commits) == history.n_steps
    assert all(
        next_state > previous_state
        for (previous_state, _), (next_state, _) in zip(mock.commits[:-1], mock.commits[1:])
    )
    assert all(state == pytest.approx(total) for state, total in mock.commits)


def test_failure_below_minimum_step_never_commits_trial_state():
    mock = BoundedIncrement(1e-8)
    strict = SolverSettings(
        method="NR",
        dlam0=0.5,
        dlam_min=0.05,
        dlam_max=0.5,
        tol_force=1e-9,
        tol_energy=1e-9,
    )
    with pytest.raises(NonConvergence) as caught:
        solve_stage(
            mock.problem(), np.array([1.0]), np.array([0.0]),
            np.zeros(0), strict, linear=False,
        )
    assert caught.value.lam == pytest.approx(0.0)
    assert mock.committed == 0.0
    assert mock.commits == []
    assert caught.value.history is not None
    assert all(not attempt.converged for attempt in caught.value.history.steps)
    assert any(
        attempt.termination == "material_return"
        for attempt in caught.value.history.steps
    )

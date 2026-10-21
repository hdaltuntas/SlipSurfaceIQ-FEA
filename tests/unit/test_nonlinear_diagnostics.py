"""Failure histories distinguish cutback causes and preserve committed state."""

from dataclasses import asdict

import numpy as np
import pytest

from slipsurface.fe2d.core.errors import (
    MaterialIntegrationError,
    NonConvergence,
    SingularSystemError,
)
from slipsurface.fe2d.fem.nonlinear import Problem, StageHistory, StepRecord, solve_stage
from slipsurface.fe2d.model.stages import SolverSettings


@pytest.mark.parametrize(
    "cause", ["stagnation", "max_iterations", "singular_tangent", "material_return"]
)
def test_failed_attempts_keep_history_and_rollback(cause):
    committed = [0.0]

    def integrate(du):
        total = committed[0] + du[0]
        if cause == "material_return" and total > 0.4:
            raise MaterialIntegrationError("test local return", details={"test_trial": total})
        # Load capacity 0.4. Larger trial loads cannot reach equilibrium.
        return total, np.array([min(total, 0.4)])

    class Factor:
        Kfp = np.zeros((1, 0))

        def solve(self, rhs):
            if cause == "singular_tangent" and committed[0] >= 0.25:
                raise SingularSystemError("test capacity")
            return rhs

    def commit(trial, total):
        committed[0] = trial

    p = Problem(
        1, np.array([0]), np.array([], dtype=int), integrate, lambda kind, trial: Factor(), commit
    )
    settings = SolverSettings(
        dlam0=0.25,
        dlam_min=0.02,
        dlam_max=0.25,
        max_iter=2 if cause == "max_iterations" else 30,
        tol_force=1e-8,
        tol_energy=1e-8,
    )
    with pytest.raises(NonConvergence) as caught:
        solve_stage(p, np.ones(1), np.zeros(1), np.zeros(0), settings, False)
    exc = caught.value
    hist = exc.history
    assert hist.n_steps > 0
    assert 0 < exc.lam <= 0.4
    assert committed[0] == pytest.approx(exc.lam)
    failed = [step for step in hist.steps if not step.converged]
    assert failed and all(step.termination == cause for step in failed)
    for step in hist.steps:
        assert len(step.residuals) == len(step.force_norms) == len(step.energy_ratios)
        assert step.energy_ratios[0] is None
        np.testing.assert_allclose(np.asarray(step.residuals) * step.lam, step.force_norms)
    assert hist.steps[-1].converged is False
    if cause in ("material_return", "singular_tangent"):
        assert all(step.detail for step in failed)
    if cause == "material_return":
        assert all(step.material_failure["test_trial"] > 0.4 for step in failed)
        assert all(step.material_failure is None for step in hist.steps if step.converged)


def test_old_step_records_have_diagnostic_defaults():
    record = StepRecord(**{"lam": 0.5, "iterations": 2, "residuals": [1.0, 0.0], "converged": True})
    assert record.termination == ""
    assert record.material_failure is None
    assert record.force_norms == record.energy_ratios == []
    assert StepRecord(**asdict(record)) == record


def test_local_return_failure_can_recover_by_cutback():
    committed = [0.0]

    def integrate(du):
        if abs(du[0]) > 0.2:
            raise MaterialIntegrationError("increment too large")
        total = committed[0] + du[0]
        return total, np.array([total])

    class Factor:
        Kfp = np.zeros((1, 0))

        def solve(self, rhs):
            return rhs

    def commit(trial, total):
        assert trial == pytest.approx(total[0])
        committed[0] = trial

    p = Problem(
        1, np.array([0]), np.array([], dtype=int), integrate, lambda kind, trial: Factor(), commit
    )
    _, du, hist = solve_stage(
        p, np.ones(1), np.zeros(1), np.zeros(0), SolverSettings(dlam0=0.5), False
    )
    assert committed[0] == pytest.approx(1.0)
    assert du[0] == pytest.approx(1.0)
    assert any(s.termination == "material_return" for s in hist.steps)
    assert hist.steps[-1].converged
    accepted = np.array([s.lam for s in hist.steps if s.converged])
    increments = np.diff(np.r_[0.0, accepted])
    assert hist.steps[0].lam == 0.5 and not hist.steps[0].converged
    assert increments[0] == 0.125  # two halvings before the first accepted step
    assert increments[1] == pytest.approx(1.5 * increments[0])  # fast step grows again


def test_zero_committed_tangent_uses_elastic_predictor_for_unloading():
    kinds = []

    class Factor:
        Kfp = np.zeros((1, 0))

        def solve(self, rhs):
            return rhs / 2.0

    def factor(kind, trial):
        kinds.append(kind)
        if kind == "committed":
            raise SingularSystemError("perfectly plastic corner")
        return Factor()

    p = Problem(
        1,
        np.array([0]),
        np.array([], dtype=int),
        lambda du: (du.copy(), 2 * du),
        factor,
        lambda trial, total: None,
    )
    _, du, hist = solve_stage(
        p, -np.ones(1), np.zeros(1), np.zeros(0), SolverSettings(dlam0=1.0), False
    )
    np.testing.assert_allclose(du, [-0.5])
    assert kinds == ["committed", "elastic"]
    assert hist.steps[-1].converged


def test_elastic_fallback_is_not_used_for_a_singular_newton_tangent():
    kinds = []

    class Factor:
        Kfp = np.zeros((1, 0))

        def solve(self, rhs):
            return rhs

    def factor(kind, trial):
        kinds.append(kind)
        if kind == "tangent":
            raise SingularSystemError("actual tangent singular")
        return Factor()

    p = Problem(
        1,
        np.array([0]),
        np.array([], dtype=int),
        lambda du: (du.copy(), 3 * du),
        factor,
        lambda trial, total: None,
    )
    with pytest.raises(NonConvergence) as caught:
        solve_stage(
            p, np.ones(1), np.zeros(1), np.zeros(0), SolverSettings(dlam0=1.0, dlam_min=0.1), False
        )
    assert caught.value.history.steps[-1].termination == "singular_tangent"
    assert "tangent" in kinds
    assert "elastic" not in kinds


def test_linear_failure_keeps_diagnostic_history():
    class Factor:
        def solve(self, rhs):
            return np.zeros_like(rhs)

    p = Problem(
        1,
        np.array([0]),
        np.array([], dtype=int),
        lambda du: (None, np.zeros(1)),
        lambda kind, trial: Factor(),
        lambda trial, total: pytest.fail("failed trial must not commit"),
    )
    with pytest.raises(NonConvergence, match="linear stage") as caught:
        solve_stage(p, np.ones(1), np.zeros(1), np.zeros(0), SolverSettings(), True)
    assert caught.value.lam == 0
    assert caught.value.history.steps[-1].termination == "stagnation"


@pytest.mark.parametrize("wrapped", [False, True])
def test_srf_local_failure_is_not_a_collapse_bracket(monkeypatch, wrapped):
    from slipsurface.fe2d import api
    from slipsurface.fe2d.fem.static import StaticSolver
    from slipsurface.fe2d.mesh import rectangle

    def fail(*args, **kwargs):
        if wrapped:
            hist = StageHistory(
                [
                    StepRecord(
                        0.1,
                        0,
                        [],
                        False,
                        "material_return",
                        detail="local test failure",
                        material_failure={"test_trial": 1.0},
                    )
                ]
            )
            raise NonConvergence(0.0, history=hist)
        raise MaterialIntegrationError("local test failure", details={"test_trial": 1.0})

    m = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=rectangle(1.0, 1.0, 1, 1),
        materials={"m": api.MaterialSpec.mohr_coulomb("m", 3e4, 0.3, 10.0, 30.0, 0.0)},
        region_material={1: "m"},
        initial=api.InitialStress("none"),
        fixities=(api.Fixity("bottom", True, True),),
    )
    monkeypatch.setattr(StaticSolver, "solve_increment", fail)
    with pytest.raises(MaterialIntegrationError, match="local.*failure|local.*failed") as caught:
        api.strength_reduction(m)
    assert caught.value.details == {"test_trial": 1.0}

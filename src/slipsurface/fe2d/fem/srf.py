"""Shear strength reduction (SRF): factor of safety by bisection.

For a trial factor F the strength of every Mohr-Coulomb / Drucker-Prager material is
reduced (``c/F``, ``tan(phi)/F``, ``psi -> min(psi, phi_F)``). Each trial starts from the
state at the end of the selected stage: the committed stresses are returned onto the
reduced yield surfaces and the resulting out-of-balance force is applied in load steps
by the Newton-Raphson stage solver. A trial *fails* when the step size drops below
``dlam_min`` (non-convergence). The bracket ``[F_lo converged, F_hi failed]`` is
narrowed by bisection until ``F_hi - F_lo < tol``; the factor of safety is ``F_lo``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np
from numpy.typing import NDArray

from ..core.errors import ModelError, NonConvergence, SolverError
from ..core.log import get_logger
from ..model.model import Model
from ..model.stages import Stage
from .static import SolveResult, StageResult, StaticSolver

log = get_logger("srf")


@dataclass
class SRFTrial:
    F: float
    converged: bool
    lam: float  # load factor reached (1 if converged)
    max_disp: float  # max |u| change relative to the base state


@dataclass
class SRFResult:
    factor: float  # factor of safety (last converged F)
    F_failed: float  # smallest failed F
    trials: list[SRFTrial] = field(default_factory=list)
    base: SolveResult | None = None  # analysis up to the selected stage
    at_factor: StageResult | None = None  # converged state at F = factor
    u_failed: NDArray[np.float64] | None = None  # (nn, 2) last converged step at F_failed


def strength_reduction(
    model: Model,
    stage: int | str = -1,
    tol: float = 0.01,
    F_first: float = 1.0,
    growth: float = 1.25,
    F_max: float = 20.0,
    dlam_min: float = 2e-3,
) -> SRFResult:
    """Factor of safety of ``model`` after ``stage`` (index or name; default: last).

    ``dlam_min``: smallest load-factor step of a trial before it is declared failed
    (coarser than for ordinary stages; the bisection tolerance dominates the accuracy).
    """
    solver = StaticSolver(model)
    if model.stages:
        idx = stage if isinstance(stage, int) else [s.name for s in model.stages].index(stage)
        idx = idx % len(model.stages)
        base = solver.run(stop_after=idx)
        st_def: Stage = model.stages[idx]
    else:
        base = solver.run()
        st_def = Stage("initial")
    assert solver.state is not None
    base_state = solver.state.commit()
    override = dict(getattr(solver, "override", {}))
    if not any(m.model in ("mohr_coulomb", "drucker_prager") for m in model.materials.values()):
        raise ModelError("strength reduction needs Mohr-Coulomb or Drucker-Prager materials")
    trials: list[SRFTrial] = []
    best: dict[str, object] = {}
    trial_settings = replace(model.settings, dlam_min=max(dlam_min, model.settings.dlam_min))

    def trial(F: float) -> bool:
        mats = {k: v.with_strength_factor(F) for k, v in model.materials.items()}
        lay = solver.layout(override, materials=mats)
        state = base_state.commit()
        solver._D_committed = None
        solver.project(state, lay)
        f_ext = solver.stage_external_force(st_def, lay)
        try:
            state, _ = solver.solve_increment(
                state, lay, f_ext, np.zeros(solver.dofmap.prescribed.size), trial_settings
            )
            ok, lam = True, 1.0
        except NonConvergence as exc:
            ok, lam = False, exc.lam
        except SolverError:
            ok, lam = False, 0.0
        du = solver.dofmap.nodal(state.u - base_state.u)
        trials.append(SRFTrial(F, ok, lam, float(np.nanmax(np.linalg.norm(du, axis=1)))))
        log.info("SRF trial F=%.4f %s (lam=%.3f)", F, "ok" if ok else "FAILED", lam)
        if ok and ("F" not in best or F > best["F"]):  # type: ignore[operator]
            best.update(F=F, res=solver._result(f"SRF F={F:.4f}", state, f_ext, {}))
        if not ok:
            best.setdefault("fail_u", {})
            best["fail_u"][F] = du  # type: ignore[index]
        return ok

    # ---- bracket
    if trial(F_first):
        lo, hi = F_first, F_first * growth
        while trial(hi):
            lo, hi = hi, hi * growth
            if hi > F_max:
                raise SolverError(f"no failure up to F = {F_max}")
    else:
        hi, lo = F_first, F_first / growth
        while not trial(lo):
            hi, lo = lo, lo / growth
            if lo < 0.05:
                raise SolverError("model fails even with strongly increased strength")
    # ---- bisection
    while hi - lo > tol:
        mid = 0.5 * (lo + hi)
        if trial(mid):
            lo = mid
        else:
            hi = mid
    fail_u = best.get("fail_u", {}).get(hi)  # type: ignore[union-attr]
    return SRFResult(
        factor=lo,
        F_failed=hi,
        trials=trials,
        base=base,
        at_factor=best.get("res"),  # type: ignore[arg-type]
        u_failed=fail_u,
    )

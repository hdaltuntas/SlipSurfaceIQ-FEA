"""Incremental-iterative solution of one stage (Newton-Raphson family).

For a load factor lambda in [0, 1] the out-of-balance force is

    R(u, lambda) = lambda f_ext + (1 - lambda) f0 - f_int(u)

where ``f0`` is the internal force of the committed state at the start of the stage
(excavation-type unbalanced forces arise naturally). Inside a step the stresses are
always integrated from the last *committed* state with the total step strain, so no
spurious unloading occurs between iterations. A step that does not converge is rolled
back and retried with half the increment; a step converging in ``fast_iter`` iterations
or fewer lets the next increment grow by 1.5.

The first iteration of every step is a predictor with the tangent of the last
converged state; prescribed-displacement increments enter it in linearised form
(``R0 - K_fp du_p``), so displacement-controlled steps start from a smooth field instead
of a boundary-layer strain spike.

Tangent options (``SolverSettings.method``):

* ``"NR"``      consistent tangent, refactorised every iteration (quadratic convergence)
* ``"mNR"``     tangent of the last converged state, factorised once per step
* ``"hybrid"``  mNR, switching to NR inside a step when ``||R_i|| / ||R_i-1|| > ratio``
* ``"initial"`` elastic stiffness, factorised once per stage

A step is abandoned early when its residual stagnates or diverges. Local material
failures cut the load step; the requested Newton method is never silently changed.

Convergence needs both ``||R|| / f_ref < tol_force`` and
``|du_i . R_i| / |du_0 . R_0| < tol_energy``; ``f_ref`` is the norm of the stage's change
of external force on the free DOFs, of the reaction change, or (displacement-driven
stages) of the total reaction at the driven DOFs, whichever is largest.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from ..core.errors import MaterialIntegrationError, NonConvergence, SingularSystemError
from ..core.log import get_logger
from ..model.stages import SolverSettings

log = get_logger("nonlinear")

Arr = NDArray[np.float64]


@dataclass
class StepRecord:
    lam: float
    iterations: int
    residuals: list[float]  # relative force residual per iteration
    converged: bool
    termination: str = ""  # empty when reading records written before diagnostics existed
    force_norms: list[float] = field(default_factory=list)
    energy_ratios: list[float | None] = field(default_factory=list)
    detail: str = ""
    material_failure: dict | None = None
    worst_dofs: NDArray[np.int64] | None = None


@dataclass
class StageHistory:
    steps: list[StepRecord] = field(default_factory=list)

    @property
    def n_steps(self) -> int:
        return sum(1 for s in self.steps if s.converged)

    @property
    def n_iterations(self) -> int:
        return sum(s.iterations for s in self.steps)


@dataclass
class Problem:
    """Callbacks the stage solver needs (provided by :class:`StaticSolver`)."""

    ndof: int
    free: NDArray[np.int64]
    prescribed: NDArray[np.int64]
    # integrate(du_step) -> (trial state object, f_int (ndof,))  from the committed state
    integrate: Callable[[Arr], tuple[object, Arr]]
    # factor(kind, trial) -> object with .solve(rhs_free) and .Kfp (free x prescribed);
    # kind: "tangent" | "committed" | "elastic"
    factor: Callable[[str, object | None], object]
    # commit(trial, du_total_so_far): make a converged step the new committed state
    commit: Callable[[object, Arr], None]
    progress: Callable | None = None


def solve_stage(
    prob: Problem,
    f_ext: Arr,
    f0: Arr,
    du_presc: Arr,
    settings: SolverSettings,
    linear: bool,
    lam_end: float = 1.0,
) -> tuple[object, Arr, StageHistory]:
    """Drive lambda from 0 to ``lam_end`` (< 1: load split). Returns (final trial state,
    total du, history).

    ``du_presc``: increment of prescribed displacements over the whole stage.
    Raises :class:`NonConvergence` (with the last converged lambda) if the step size
    falls below ``dlam_min``.
    """
    free, pres = prob.free, prob.prescribed
    s = settings
    hist = StageHistory()
    lam = 0.0
    dlam = 1.0 if linear else min(s.dlam0, 1.0)
    du_total = np.zeros(prob.ndof)
    d_fext = (f_ext - f0)[free]
    n_dfext = float(np.linalg.norm(d_fext))
    f_scale = max(float(np.linalg.norm(f_ext)), float(np.linalg.norm(f0)), 1e-30)
    driven = pres[du_presc != 0.0] if pres.size else pres  # displacement-driven DOFs
    last_trial: object | None = None
    initial_fact = None

    while lam < lam_end - 1e-12:
        lam_t = min(lam_end, lam + dlam)
        if lam_end - lam_t < 1e-9:
            lam_t = lam_end
        dpres = (lam_t - lam) * du_presc if pres.size else np.zeros(0)
        du = du_total.copy()
        res_hist: list[float] = []
        force_norms: list[float] = []
        energy_ratios: list[float | None] = []
        termination = "max_iterations"
        detail = ""
        material_failure = None
        converged = False
        fact = None
        use_nr = s.method == "NR"
        g0 = 0.0
        ddu = np.zeros(free.size)
        trial: object | None = None
        prev_rel = np.inf
        Rf: Arr | None = None
        it = 0
        try:
            for it in range(s.max_iter + 1):
                if prob.progress is not None:
                    prob.progress(lam_t, it)
                trial, fint = prob.integrate(du - du_total)
                R = lam_t * f_ext + (1.0 - lam_t) * f0 - fint
                Rf = R[free]
                f_reac = (fint - f0)[pres] if pres.size else np.zeros(0)
                f_ref = max(
                    n_dfext * lam_t,
                    float(np.linalg.norm(f_reac)),
                    float(np.linalg.norm(fint[driven])) if driven.size else 0.0,
                    1e-10 * f_scale,
                )
                residual_norm = float(np.linalg.norm(Rf))
                rel = residual_norm / f_ref
                # A held prestressed stage may have zero load change, but assembled
                # internal forces still cancel only to floating-point precision. Do
                # not cut steps trying to resolve numerical noise below that scale.
                roundoff = 64 * np.finfo(float).eps * max(f_scale, float(np.linalg.norm(fint)))
                res_hist.append(rel)
                if prob.progress is not None:
                    prob.progress(lam_t, it, rel)
                force_norms.append(residual_norm)
                e_rel = abs(float(ddu @ Rf)) / max(abs(g0), 1e-300) if it > 0 else None
                energy_ratios.append(e_rel)
                if (
                    it == 0
                    and (rel < 1e-3 * s.tol_force or residual_norm <= roundoff)
                    and not driven.size
                ):
                    converged = True
                    termination = "initial_equilibrium"
                    break
                if it > 0:
                    if residual_norm <= roundoff:
                        converged = True
                        termination = "roundoff"
                        break
                    if rel < s.tol_force and e_rel is not None and e_rel < s.tol_energy:
                        converged = True
                        termination = "force_and_energy"
                        break
                    if linear and rel < 1e-8:
                        converged = True
                        termination = "linear_force"
                        break
                if not np.isfinite(rel) or rel > 1e8:
                    termination = "nonfinite_or_divergent"
                    break
                if it == s.max_iter:
                    break
                # stagnation / divergence: give up early and cut the step
                if it >= 6 and rel > 0.8 * res_hist[it - 4] and rel > s.tol_force:
                    termination = "stagnation"
                    break
                # ---- tangent / factorisation
                if s.method == "hybrid" and it >= 2 and rel > s.hybrid_ratio * prev_rel:
                    use_nr = True
                if s.method == "initial" or linear:
                    if initial_fact is None:
                        initial_fact = prob.factor("elastic", None)
                    fact = initial_fact
                elif it == 0 or (not use_nr and fact is None):
                    # predictor (and mNR): tangent of the last converged state
                    try:
                        fact = prob.factor("committed", None)
                    except SingularSystemError:
                        if it != 0:
                            raise
                        # A perfectly plastic corner can have exactly zero tangent.
                        # An elastic predictor permits unloading from it; subsequent
                        # NR iterations still use the actual constitutive tangent.
                        fact = prob.factor("elastic", None)
                elif use_nr:
                    fact = prob.factor("tangent", trial)
                if it == 0:
                    # linearised prescribed-displacement increment: R0 - K_fp du_p
                    rhs = Rf
                    if dpres.size and np.any(dpres != 0.0):
                        rhs = Rf - fact.Kfp @ dpres  # type: ignore[attr-defined]
                    ddu = fact.solve(rhs)  # type: ignore[attr-defined]
                    g0 = float(ddu @ rhs)
                    if pres.size:
                        du[pres] += dpres
                else:
                    ddu = fact.solve(Rf)  # type: ignore[attr-defined]
                    if s.line_search:
                        ddu = _line_search(prob, du - du_total, ddu, Rf, lam_t, f_ext, f0, free)
                du[free] += ddu
                prev_rel = rel
        except (SingularSystemError, MaterialIntegrationError) as exc:
            if linear:
                raise
            converged = False
            termination = (
                "material_return"
                if isinstance(exc, MaterialIntegrationError)
                else "singular_tangent"
            )
            detail = str(exc)
            if isinstance(exc, MaterialIntegrationError):
                material_failure = exc.details
        hist.steps.append(
            StepRecord(
                lam_t,
                it,
                res_hist,
                converged,
                termination,
                force_norms,
                energy_ratios,
                detail,
                material_failure,
                free[np.argsort(-np.abs(Rf))[:8]] if not converged and Rf is not None else None,
            )
        )
        if not converged:
            if linear:
                raise NonConvergence(
                    lam, f"linear stage did not converge (rel={res_hist[-1]:.2e})", history=hist
                )
            dlam *= 0.5
            log.debug(
                "step to lam=%.4f failed after %d its (residuals %s); dlam -> %.3g",
                lam_t,
                it,
                " ".join(f"{r:.1e}" for r in res_hist[-8:]),
                dlam,
            )
            if dlam < s.dlam_min:
                raise NonConvergence(lam, history=hist)
            continue
        du_total = du
        last_trial = trial
        prob.commit(trial, du_total)
        lam = lam_t
        if prob.progress is not None:
            prob.progress(lam, it, res_hist[-1], True)
        if it <= s.fast_iter:
            dlam = min(dlam * 1.5, s.dlam_max)
    assert last_trial is not None
    return last_trial, du_total, hist


def _line_search(
    prob: Problem,
    du_step: Arr,
    ddu: Arr,
    R0f: Arr,
    lam: float,
    f_ext: Arr,
    f0: Arr,
    free: NDArray[np.int64],
) -> Arr:
    """Secant line search on g(s) = ddu . R(u + s ddu) (at most 3 extra evaluations)."""
    g0 = float(ddu @ R0f)
    if g0 <= 0.0:
        return ddu
    s_prev, g_prev = 0.0, g0
    s_cur = 1.0
    for _ in range(3):
        trial_du = du_step.copy()
        trial_du[free] += s_cur * ddu
        try:
            _, fint = prob.integrate(trial_du)
        except MaterialIntegrationError:
            s_cur = max(0.5 * s_cur, 0.1)  # shorten the step and stop searching
            break
        g = float(ddu @ (lam * f_ext + (1 - lam) * f0 - fint)[free])
        if abs(g) <= 0.8 * abs(g0):
            break
        if g == g_prev:
            break
        s_new = s_cur - g * (s_cur - s_prev) / (g - g_prev)
        s_prev, g_prev = s_cur, g
        s_cur = float(np.clip(s_new, 0.1, 1.0))
    return s_cur * ddu

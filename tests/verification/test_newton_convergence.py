"""Kapı 2 — quadratic convergence of full Newton-Raphson with the consistent tangent.

Cylinder under internal pressure (P2 geometry) with (a) associated Tresca and (b)
non-associated Mohr-Coulomb (unsymmetric tangent, LU). In the asymptotic range the
relative residuals satisfy r_{i+1} ≈ C r_i^2, i.e. the slope of log r_{i+1} against
log r_i is ≈ 2. Modified Newton on the same problem converges only linearly (≈ 1).
"""

from __future__ import annotations

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.mesh import rectangle

FLOOR = 1e-11  # below this round-off dominates


def _history(mat, p_in, p_out, method):
    mesh = rectangle(1.0, 0.1, 40, 2, ElemType.T6, origin=(1.0, 0.0), grade_x=2.0)
    model = api.Model(
        analysis=api.Analysis.AXISYMMETRIC,
        mesh=mesh,
        materials={"m": mat},
        region_material={1: "m"},
        fixities=(api.Fixity("bottom", False, True), api.Fixity("top", False, True)),
        initial=api.InitialStress("field", field=(-p_out, -p_out, -p_out, 0.0)),
        stages=[
            api.Stage("p", loads=(api.EdgeLoad("left", qn=p_in), api.EdgeLoad("right", qn=p_out)))
        ],
        settings=api.SolverSettings(
            method=method, tol_force=1e-11, tol_energy=1e-20, dlam0=0.25, max_iter=200
        ),
    )
    return api.run(model).last.history


def _loglog(hist):
    """Slope of log r_{i+1} vs log r_i for the last asymptotic pair of each step."""
    out = []
    for st in hist.steps:
        r = np.asarray(st.residuals)
        pairs = [(r[i], r[i + 1]) for i in range(r.size - 1) if r[i] < 0.5 and r[i + 1] > FLOOR]
        if len(pairs) >= 2:
            (a0, a1), (b0, b1) = pairs[-2], pairs[-1]
            out.append((np.log(b1) - np.log(a1)) / (np.log(b0) - np.log(a0)))
    return np.asarray(out)


CASES = {
    "tresca": (api.MaterialSpec.mohr_coulomb("m", 2.1e5, 0.3, 100.0, 0.0, 0.0), 125.0, 0.0),
    "mc_nonassoc": (api.MaterialSpec.mohr_coulomb("m", 2.1e5, 0.3, 30.0, 30.0, 5.0), 180.0, 100.0),
}


@pytest.mark.parametrize("case", list(CASES))
def test_full_newton_is_quadratic(case):
    mat, p_in, p_out = CASES[case]
    hist = _history(mat, p_in, p_out, "NR")
    k = _loglog(hist)
    assert k.size >= 1
    assert np.all(k > 1.6), k  # ≈ 2
    # few iterations per step
    assert max(st.iterations for st in hist.steps) <= 8


def test_modified_newton_is_linear():
    mat, p_in, p_out = CASES["tresca"]
    hist = _history(mat, p_in, p_out, "mNR")
    k = _loglog(hist)
    assert k.size >= 1 and np.median(k) < 1.3
    assert _history(mat, p_in, p_out, "hybrid").n_iterations < hist.n_iterations


def test_all_methods_reach_the_same_solution():
    """NR, mNR, hybrid, initial stiffness and NR + line search: same converged state."""
    mat, p_in, p_out = CASES["mc_nonassoc"]
    u = {}
    for method, ls in [("NR", False), ("NR", True), ("mNR", False), ("hybrid", False),
                       ("initial", False)]:  # fmt: skip
        mesh = rectangle(1.0, 0.1, 20, 2, ElemType.T6, origin=(1.0, 0.0), grade_x=2.0)
        model = api.Model(
            analysis=api.Analysis.AXISYMMETRIC,
            mesh=mesh,
            materials={"m": mat},
            region_material={1: "m"},
            fixities=(api.Fixity("bottom", False, True), api.Fixity("top", False, True)),
            initial=api.InitialStress("field", field=(-p_out, -p_out, -p_out, 0.0)),
            stages=[
                api.Stage(
                    "p", loads=(api.EdgeLoad("left", qn=p_in), api.EdgeLoad("right", qn=p_out))
                )
            ],
            settings=api.SolverSettings(
                method=method,
                line_search=ls,
                tol_force=1e-8,
                tol_energy=1e-12,
                max_iter=300,
                dlam0=0.1,
                dlam_max=0.1,
            ),  # fmt: skip
        )
        u[(method, ls)] = api.run(model).last.u
    ref = u[("NR", False)]
    for k, v in u.items():
        assert np.abs(v - ref).max() < 1e-5 * np.abs(ref).max(), k

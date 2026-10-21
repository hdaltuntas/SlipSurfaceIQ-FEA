"""C1/C2 — Modified Cam-Clay triaxial compression, drained and undrained (method A).

Axisymmetric element test (as P5): normally consolidated sample under isotropic effective
stress p0, constant cell pressure, axial displacement imposed in stages.

* **C1, drained** — reference: the MCC rate equations along the drained stress path
  (dp' = dq/3) integrated with a tight-tolerance ODE solver (continuous
  ``K = (p' + a)(1+e0)/kappa``, a = p_min,
  ``G = 3K(1-2nu)/(2(1+nu))``). Criterion: q at the same axial strain < 1 %. The deviation
  is the first-order time-integration error of the hypoelastic shear modulus (frozen at
  the start of each step); it halves with the load step.
* **C2, undrained (A)** — reference: closed-form effective stress path of an NC sample,
  ``p'/p0 = (M^2 / (M^2 + eta^2))^Lambda``, ``Lambda = (lambda - kappa) / lambda`` (solved
  with the small elasticity shift a = p_min included).
  Criterion: p' at the same stress ratio < 2 %; the total mean stress p' + p_excess must
  equal p0 + q/3 (equilibrium with the constant cell pressure).
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import Drainage, ElemType
from slipsurface.fe2d.mesh import rectangle

NU, M, LAM, KAP, E0, P0 = 0.25, 1.2, 0.2, 0.04, 1.0, 200.0
P_MIN = 1.0  # shift of the logarithmic elasticity (library default)
BETA, THETA = (1 + E0) / KAP, (1 + E0) / (LAM - KAP)
G_RATIO = 3 * (1 - 2 * NU) / (2 * (1 + NU))


def _run(eps, drainage, dlam):
    mesh = rectangle(1.0, 1.0, 1, 1, ElemType.T6)
    mat = api.MaterialSpec.mcc("clay", NU, M, LAM, KAP, E0, p_ref=P0, drainage=drainage,
                               p_min=P_MIN)  # fmt: skip
    stages = [
        api.Stage(
            f"e{i}",
            loads=(api.EdgeLoad("right", qn=P0),),
            displacements=(api.Displacement("top", uy=-float(e)),),
        )
        for i, e in enumerate(eps)
    ]
    model = api.Model(
        analysis=api.Analysis.AXISYMMETRIC,
        mesh=mesh,
        materials={"clay": mat},
        region_material={1: "clay"},
        fixities=(api.Fixity("left", True, False), api.Fixity("bottom", False, True)),
        initial=api.InitialStress("field", field=(-P0, -P0, -P0, 0.0)),
        stages=stages,
        settings=api.SolverSettings(tol_force=1e-8, tol_energy=1e-10, dlam0=dlam, dlam_max=dlam),
    )
    return api.run(model)


def _pq(sig):
    s = sig.reshape(-1, 4)
    p = -s[:, :3].sum(axis=1) / 3
    d = s + p[:, None] * np.array([1.0, 1.0, 1.0, 0.0])
    q = np.sqrt(1.5 * (d * d * np.array([1.0, 1.0, 1.0, 2.0])).sum(axis=1))
    return p, q


def _drained_reference():
    """Axial strain as a function of q along the drained path (dp = dq / 3)."""

    def rhs(q, y):
        p, pc, _ = y
        dp = 1.0 / 3.0
        K = BETA * (p + P_MIN)
        dev, des, dpc = dp / K, 1.0 / (3 * G_RATIO * K), 0.0
        if q > 0:  # NC: loading on the yield surface from the start
            lam = (2 * p - pc + 6 * q / M**2) * dp / (p * THETA * pc * (2 * p - pc))
            dev += lam * (2 * p - pc)
            des += lam * 2 * q / M**2
            dpc = THETA * pc * lam * (2 * p - pc)
        return [dp, dpc, des + dev / 3]

    q_cs = 3 * M * P0 / (3 - M)
    sol = solve_ivp(rhs, [0, 0.999 * q_cs], [P0, P0, 0.0], rtol=1e-10, atol=1e-12,
                    dense_output=True, max_step=q_cs / 2000)  # fmt: skip
    qq = np.linspace(0.0, 0.999 * q_cs, 20001)
    return sol.sol(qq)[2], qq


def _undrained_p(eta, lam_):
    """p' on the undrained NC path at stress ratio eta: zero volume change,
    kappa ln((p'+a)/(p0+a)) + (lambda-kappa) ln(p_c/p0) = 0, p_c = p'(1 + eta^2/M^2).
    For a -> 0: p'/p0 = (M^2 / (M^2 + eta^2))^Lambda."""
    from scipy.optimize import brentq

    def g(p, e):
        return KAP * np.log((p + P_MIN) / (P0 + P_MIN)) + (LAM - KAP) * np.log(
            p * (1 + e**2 / M**2) / P0
        )

    return np.array([brentq(g, 1e-6, P0, args=(e,)) for e in np.atleast_1d(eta)])


def test_c1_drained_triaxial():
    eps = np.linspace(0.005, 0.15, 30)
    res = _run(eps, Drainage.DRAINED, dlam=0.04)
    ea_ref, q_ref = _drained_reference()
    errs = []
    for st, ea in zip(res.stages, eps):
        p, q = _pq(st.sig["soil"])
        qr = np.interp(ea, ea_ref, q_ref)
        errs.append(np.abs(q - qr).max() / qr)
        assert np.allclose(p, P0 + q / 3, rtol=1e-8)  # drained path
    assert max(errs) < 0.01, errs
    p, q = _pq(res.last.sig["soil"])
    assert q.min() > 0.8 * M * p.max()  # approaching the critical state line


def test_c2_undrained_triaxial_method_a():
    eps = np.linspace(0.001, 0.05, 25)
    res = _run(eps, Drainage.UNDRAINED_A, dlam=0.25)
    lam_ = (LAM - KAP) / LAM
    for st in res.stages:
        p, q = _pq(st.sig["soil"])
        p_ref = _undrained_p(q / p, lam_)
        assert np.abs(p - p_ref).max() / p_ref.min() < 0.02
        pe = st.excess_pore["soil"].ravel()
        assert np.allclose(p + pe, P0 + q / 3, rtol=1e-8)
    p, q = _pq(res.last.sig["soil"])
    assert q.mean() / p.mean() == pytest.approx(M, rel=0.03)  # near critical state
    assert res.last.excess_pore["soil"].min() > 0.4 * P0  # NC clay: positive excess

"""Constitutive models: admissibility, closest point, consistent tangents, substepping."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.optimize import minimize

from slipsurface.fe2d.fem.materials import DruckerPrager, MohrCoulomb, VonMises
from slipsurface.fe2d.fem.materials.drucker_prager import DPYield
from slipsurface.fe2d.fem.materials.substep import SubstepSettings, batch, integrate_substep

MC_CASES = [
    (10.0, 30.0, 30.0, None),
    (10.0, 30.0, 30.0, 2.0),
    (10.0, 30.0, 5.0, None),
    (10.0, 30.0, 10.0, 3.0),
    (5.0, 0.0, 0.0, None),
    (0.0, 35.0, 35.0, None),
]


def _fd_tangent(model, sig_n, deps, q_n, h=1e-7):
    D = np.zeros((4, 4))
    for j in range(4):
        e = np.zeros(4)
        e[j] = h
        sp = model.integrate(sig_n[None], (deps + e)[None], q_n[None])[0][0]
        sm = model.integrate(sig_n[None], (deps - e)[None], q_n[None])[0][0]
        D[:, j] = (sp - sm) / (2 * h)
    return D


@pytest.mark.parametrize("c,phi,psi,st", MC_CASES)
def test_mohr_coulomb_return_and_tangent(c, phi, psi, st, rng):
    mc = MohrCoulomb(1e4, 0.3, c, phi, psi, st)
    n = 400
    sig_n = rng.normal(0, 20, (n, 4)) * np.array([1, 1, 1, 0.3]) - 30.0 * np.array([1, 1, 1, 0])
    sig_n, _, _, _ = mc.integrate(sig_n, np.zeros((n, 4)), np.zeros((n, 1)))  # admissible
    deps = rng.normal(0, 1, (n, 4)) * 4e-3
    sig, q, D, fl = mc.integrate(sig_n, deps, np.zeros((n, 1)))
    assert np.all(fl != 255)
    assert mc.yield_function(sig).max() < 1e-8 * 100
    assert np.all(q[fl == 0, 0] == 0) and np.all(q[fl > 0, 0] >= 0)
    for i in np.flatnonzero(fl == 1)[:25]:  # plane / edge returns: exact tangent
        Dfd = _fd_tangent(mc, sig_n[i], deps[i], np.zeros(1))
        assert np.abs(Dfd - D[i]).max() < 1e-5 * np.abs(mc._D).max()
    if psi == phi:  # associated: closest point in the energy norm
        Dinv = np.linalg.inv(mc._D)
        for i in np.flatnonzero(fl > 0)[:10]:
            tr = sig_n[i] + mc._D @ deps[i]

            def obj(x, tr=tr):
                return (tr - x) @ Dinv @ (tr - x)

            # Independent convex QP in principal stresses. Six linear MC planes
            # avoid finite-difference optimization of a nonsmooth spectral max.
            # An infeasible/unsuccessful optimizer is never a reference solution.
            trial = np.linalg.eigvalsh([[tr[0], tr[3], 0], [tr[3], tr[1], 0], [0, 0, tr[2]]])
            scale = max(np.abs(trial).max(), c, 1.0)
            trial = trial / scale
            compliance = np.full((3, 3), -0.3)
            np.fill_diagonal(compliance, 1.0)
            A, b = [], []
            sp, cp = math.sin(math.radians(phi)), math.cos(math.radians(phi))
            for j in range(3):
                for k in range(3):
                    if j == k:
                        continue
                    row = np.zeros(3)
                    row[j], row[k] = 1 + sp, -(1 - sp)
                    A.append(row)
                    b.append(2 * c * cp / scale)
            if st is not None:
                A.extend(np.eye(3))
                b.extend([st / scale] * 3)
            A, b = np.asarray(A), np.asarray(b)

            def energy(x, trial=trial, compliance=compliance):
                d = x - trial
                return d @ compliance @ d

            def gradient(x, trial=trial, compliance=compliance):
                return 2 * compliance @ (x - trial)

            cons = {"type": "ineq", "fun": lambda x, b=b, A=A: b - A @ x, "jac": lambda x, A=A: -A}
            r = minimize(energy, np.zeros(3), jac=gradient, constraints=[cons], method="SLSQP",
                         options={"ftol": 1e-12, "maxiter": 500})  # fmt: skip
            assert r.success, r.message
            assert np.max(A @ r.x - b) < 1e-9
            reference = r.fun * scale**2 / 1e4
            assert obj(sig[i]) <= reference * (1 + 1e-4) + 1e-12


@pytest.mark.parametrize(
    "model",
    [
        DruckerPrager.from_mc(1e4, 0.3, 10, 30, 10),
        DruckerPrager.from_mc(1e4, 0.3, 10, 30, 30, "outer"),
        VonMises(2e5, 0.3, 250.0, 1e4),
    ],
)
def test_drucker_prager_tangent(model, rng):
    n = 200
    deps = rng.normal(0, 1, (n, 4)) * 5e-3
    sig, q, D, fl = model.integrate(np.zeros((n, 4)), deps, np.zeros((n, 1)))
    assert model.yield_function(sig, q[:, 0]).max() < 1e-9 * 100
    for i in np.flatnonzero(fl == 1)[:20]:
        Dfd = _fd_tangent(model, np.zeros(4), deps[i], np.zeros(1), h=1e-8)
        assert np.abs(Dfd - D[i]).max() < 1e-5 * np.abs(model._D).max()


def test_von_mises_hardening_in_shear():
    vm = VonMises(2e5, 0.3, 250.0, 1e4)
    sig, q = np.zeros((1, 4)), np.zeros((1, 1))
    for _ in range(20):
        sig, q, _, _ = vm.integrate(sig, np.array([[0, 0, 0, 1e-3]]), q)
    gp = 0.02 - sig[0, 3] / vm.G
    assert sig[0, 3] == pytest.approx((250 + 1e4 * gp / math.sqrt(3)) / math.sqrt(3), rel=1e-10)


def test_dp_parameters_plane_strain_tresca_limit():
    dp = DruckerPrager.from_mc(1e4, 0.3, 10.0, 0.0)
    assert dp.alpha == 0.0 and dp.k0 == pytest.approx(10.0)  # sqrt(J2) = c


@pytest.mark.parametrize("H", [0.0, 2e3])
def test_substepping_matches_implicit_on_fine_path(H, rng):
    """Explicit Sloan integration vs. the closed-form return on a fine strain path."""
    dp = DruckerPrager(1e4, 0.3, 0.4, 0.15, 10.0, H)
    ym = DPYield(dp)
    path = np.cumsum(rng.normal(0, 1, (400, 4)) * 1e-4 + [-2e-4, 1e-4, 0, 1.5e-4], axis=0)
    s_imp, q_imp = np.zeros((1, 4)), np.zeros((1, 1))
    s_exp, q_exp = np.zeros(4), np.zeros(1)
    prev = np.zeros(4)
    for e in path:
        de = e - prev
        prev = e
        s_imp, q_imp, _, _ = dp.integrate(s_imp, de[None], q_imp)
        s_exp, q_exp, _, _, _ = integrate_substep(ym, dp._D, s_exp, q_exp, de)
    scale = np.abs(s_imp).max()
    assert np.abs(s_exp - s_imp[0]).max() < 5e-3 * scale
    assert abs(ym.f(s_exp, q_exp)) < 1e-6 * scale


def test_substepping_large_increment_error_control():
    """One large increment: tighter STOL converges to the fine-path solution."""
    dp = DruckerPrager(1e4, 0.3, 0.4, 0.15, 10.0, 3e3)
    ym = DPYield(dp)
    de = np.array([-0.02, 0.01, 0.0, 0.015])
    ref = np.zeros((1, 4))
    q = np.zeros((1, 1))
    for _ in range(20000):
        ref, q, _, _ = dp.integrate(ref, (de / 20000)[None], q)
    errs = []
    for stol in (1e-3, 1e-5, 1e-7):
        s, _, _, pl, nsub = integrate_substep(ym, dp._D, np.zeros(4), np.zeros(1), de,
                                              SubstepSettings(stol=stol))  # fmt: skip
        assert pl == 1 and nsub >= 1
        errs.append(np.abs(s - ref[0]).max() / np.abs(ref).max())
    assert errs[2] <= errs[0] + 1e-12 and errs[2] < 1e-3


def test_substep_batch_elastic_and_unloading():
    dp = DruckerPrager(1e4, 0.3, 0.4, 0.4, 10.0)
    ym = DPYield(dp)
    sig0 = np.zeros((3, 4))
    de = np.array([[1e-5, 0, 0, 0], [0, 0, 0, 5e-3], [0, 0, 0, -5e-3]])
    s, q, D, fl = batch(ym, dp._D, sig0, np.zeros((3, 1)), de)
    assert fl.tolist() == [0, 1, 1]
    # from a yielded state, reverse shear: elastic unloading first, then reverse yield
    s1, q1, _, _, _ = integrate_substep(ym, dp._D, s[1], q[1], np.array([0, 0, 0, -1e-2]))
    assert s1[3] < 0 and abs(ym.f(s1, q1)) < 1e-6 * 10

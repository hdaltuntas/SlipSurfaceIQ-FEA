"""Constitutive models: admissibility, closest point, consistent tangents, substepping."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest
from scipy.optimize import minimize

from slipsurface.fe2d.core.enums import PlasticFlag
from slipsurface.fe2d.core.errors import MaterialIntegrationError
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


@pytest.mark.parametrize("strain", [1e-9, 1e-5, 1e-2])
def test_zero_dilation_apex_failure_never_returns_elastic_trial(strain):
    """Isochoric shear potentials cannot remove positive hydrostatic trial stress.

    Previously this returned flag 255 with f_MC > 0, which global equilibrium
    could accept. A local failure must reject the entire batch, without mutation.
    """
    mc = MohrCoulomb(3e4, 0.3, 0, 30, 0)
    sig_n, q_n = np.zeros((2, 4)), np.zeros((2, 1))
    deps = np.array([[-strain, -strain, -strain, 0.0], [strain, strain, strain, 0.0]])
    before = [a.copy() for a in (sig_n, deps, q_n)]
    with pytest.raises(MaterialIntegrationError, match=r"batch indices \[1\]") as caught:
        mc.integrate(sig_n, deps, q_n)
    details = caught.value.details
    assert details["failed_count"] == 1
    point = details["points"][0]
    assert point["reason"] == "zero_dilation_trial_above_apex"
    assert point["trial_mean"] > details["apex"] + point["mean_apex_tolerance"]
    # The diagnostic is self-contained: replay reproduces the same rejection.
    saved = json.loads(json.dumps(details, allow_nan=False))
    with pytest.raises(MaterialIntegrationError):
        MohrCoulomb(**saved["params"]).integrate(
            np.array([point["sig_n"]]), np.array([point["deps"]]), np.array([point["q_n"]])
        )
    for a, b in zip((sig_n, deps, q_n), before):
        np.testing.assert_array_equal(a, b)


def test_return_failure_payload_is_bounded():
    mc = MohrCoulomb(3e4, 0.3, 0, 30, 0)
    with pytest.raises(MaterialIntegrationError) as caught:
        mc.integrate(np.zeros((20, 4)), np.tile([1e-4, 1e-4, 0, 0], (20, 1)), np.zeros((20, 1)))
    assert caught.value.details["failed_count"] == 20
    assert len(caught.value.details["points"]) == 8


@pytest.mark.parametrize(
    "case",
    json.loads(
        (Path(__file__).parents[1] / "verification/data/material_return_failures.json").read_text(
            encoding="utf-8"
        )
    ),
    ids=lambda case: case["case"],
)
def test_recorded_returns_have_trace_obstruction_even_with_subdivisions(case):
    data = case["details"]
    point = data["points"][0]
    mc = MohrCoulomb(**data["params"])
    sig_n = np.array([point["sig_n"]])
    deps = np.array([point["deps"]])
    q_n = np.array([point["q_n"]])
    assert mc.yield_function(sig_n)[0] < 1e-8
    for count in (1, 128):
        sig, q = sig_n.copy(), q_n.copy()
        completed = 0
        with pytest.raises(MaterialIntegrationError) as caught:
            for _ in range(count):
                sig, q, _, _ = mc.integrate(sig, deps / count, q)
                completed += 1
        assert completed < count
        assert caught.value.details["points"][0]["reason"] == "zero_dilation_trial_above_apex"
        # Every accepted partial return respects the original trace balance.
        expected_mean = np.mean((sig_n + completed / count * deps @ mc.elastic_D().T)[0, :3])
        assert np.mean(sig[0, :3]) == pytest.approx(expected_mean, abs=1e-9)


def test_zero_dilation_compressive_shear_still_has_admissible_return():
    mc = MohrCoulomb(3e4, 0.3, 0, 30, 0)
    sig, _, _, flag = mc.integrate(
        np.array([[-100.0, -100.0, -100.0, 0.0]]),
        np.array([[0.0, 0.0, 0.0, 0.02]]),
        np.zeros((1, 1)),
    )
    assert flag[0] == 1
    assert mc.yield_function(sig)[0] < 1e-8


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


@pytest.mark.parametrize("psi,st", [(0.0, None), (5.0, None), (0.0, 5.0)])
def test_mohr_coulomb_apex_region_non_associated(psi, st, rng):
    """Explicit tensile flow accepts tension; the uncut isochoric model rejects it."""
    mc = MohrCoulomb(3e4, 0.3, 10.0, 30.0, psi, st, rankine_at_apex=st is None)
    n = 50000
    tr = rng.normal(0, 100, (n, 4))
    deps = tr @ np.linalg.inv(mc._D).T
    sig, _, _, fl = mc.integrate(np.zeros((n, 4)), deps, np.zeros((n, 1)))
    assert not np.any(fl == 255)
    assert mc.yield_function(sig).max() < 1e-9 * 100
    bad = np.array([[-62.68490516, 126.43094959, 10.15193833, -48.74336934]])
    mc0 = MohrCoulomb(3e4, 0.3, 10.0, 30.0, 0.0)
    with pytest.raises(MaterialIntegrationError):
        mc0.integrate(np.zeros((1, 4)), bad @ np.linalg.inv(mc0._D).T, np.zeros((1, 1)))


def test_mcc_return_tangent_and_unloading(rng):
    from slipsurface.fe2d.fem.materials import ModifiedCamClay

    mcc = ModifiedCamClay(0.25, 1.2, 0.2, 0.04, 1.0, OCR=1.2)
    n = 300
    p0 = rng.uniform(50, 300, n)
    sig_n = np.zeros((n, 4))
    sig_n[:, :3] = -p0[:, None]
    sig_n[:, :3] += rng.normal(0, 0.15, (n, 3)) * p0[:, None]
    sig_n[:, 3] = rng.normal(0, 0.1, n) * p0
    q_n = np.zeros((n, 2))
    deps = rng.normal(0, 1, (n, 4)) * 4e-3
    sig, q, D, fl = mcc.integrate(sig_n, deps, q_n)
    pc0 = mcc.initial_pc(sig_n)
    assert np.allclose(q[:, 1][fl == 0], pc0[fl == 0])  # fresh points get p_c from OCR
    f = mcc.yield_function(sig, q[:, 1])
    assert f.max() < 1e-8 * q[:, 1].max() ** 2
    pl = np.flatnonzero(fl > 0)
    assert pl.size > 20 and np.abs(f[pl]).max() < 1e-8 * q[:, 1].max() ** 2
    qn1 = np.column_stack([np.zeros(n), pc0])
    for i in pl[:25]:
        Dfd = _fd_tangent(mcc, sig_n[i], deps[i], qn1[i], h=1e-8)
        assert np.abs(Dfd - D[i]).max() < 1e-5 * np.abs(D[i]).max()
    # elastic unloading from a plastic state: hardening frozen, stress back inside
    s2, q2, _, fl2 = mcc.integrate(sig[pl], -0.3 * deps[pl], q[pl])
    back = fl2 == 0
    assert back.sum() > 0.5 * pl.size
    assert np.array_equal(q2[back, 1], q[pl][back, 1])


def _hb_cases():
    from slipsurface.fe2d.fem.materials import HoekBrown, hb_parameters

    out = []
    for gsi, mi, psi in [(50, 10, 0.0), (75, 25, 10.0), (30, 7, 5.0)]:
        mb, s, a = hb_parameters(gsi, mi)
        out.append(HoekBrown(5e6, 0.25, 5e4, mb, s, a, psi))
    return out


@pytest.mark.parametrize("case", [0, 1, 2])
def test_hoek_brown_return_and_tangent(case, rng):
    hb = _hb_cases()[case]
    n = 400
    sig_n = np.zeros((n, 4))
    sig_n[:, :3] = -rng.uniform(0, 2e4, (n, 1)) - rng.uniform(0, 3e3, (n, 3))
    sig_n[:, 3] = rng.normal(0, 2e3, n)
    deps = rng.normal(0, 1, (n, 4)) * 3e-3
    deps[: n // 4, :3] += 2e-3  # some returns towards the tensile apex
    if hb.psi == 0:
        # Preserve random shear but keep mean compression; tension obstruction is
        # checked separately instead of demanding an impossible plastic flow.
        deps[:, :3] -= deps[:, :3].mean(axis=1, keepdims=True)
    sig, q, D, fl = hb.integrate(sig_n, deps, np.zeros((n, 1)))
    f = hb.yield_function(sig)
    assert f.max() < 1e-8 * hb.sci
    from slipsurface.fe2d.post.recovery import principal_stresses

    ps = principal_stresses(sig)
    assert ps["s1"].max() <= hb.st * (1 + 1e-9) + 1e-9
    assert set(np.unique(fl)) >= {0, int(PlasticFlag.SHEAR)}
    # returned point: the plastic strain follows the MC-type potential g = m s1 - s3
    # (checked through the consistent tangent against finite differences)
    sh = np.flatnonzero(fl == PlasticFlag.SHEAR)
    for i in sh[:30]:
        Dfd = _fd_tangent(hb, sig_n[i], deps[i], np.zeros(1), h=1e-9)
        assert np.abs(Dfd - D[i]).max() < 1e-4 * np.abs(hb._D).max(), i


def test_hoek_brown_closest_point_is_idempotent(rng):
    hb = _hb_cases()[0]
    sig_n = np.zeros((200, 4))
    sig_n[:, :3] = -1e4
    deps = rng.normal(0, 1, (200, 4)) * 5e-3
    deps[:, :3] -= deps[:, :3].mean(axis=1, keepdims=True)
    sig, *_ = hb.integrate(sig_n, deps, np.zeros((200, 1)))
    sig2, _, _, fl2 = hb.integrate(sig, np.zeros_like(deps), np.zeros((200, 1)))
    assert np.allclose(sig2, sig, rtol=0, atol=1e-8 * hb.sci)

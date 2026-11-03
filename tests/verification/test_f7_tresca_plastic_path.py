"""F7: independent Tresca (phi=0 Mohr-Coulomb) shear-path verification.

For purely deviatoric engineering shear gamma_xy, sigma_n = -p I,
the elastic trial shear is tau=G*gamma_xy. With c>0, phi=psi=0,
the MC yield criterion is sigma1-sigma3-2c=2(|tau|-c), hence the
perfectly plastic plateau has |tau|=c and unchanged mean stress.
This analytical test is separate from global FEM convergence tests.
"""

from __future__ import annotations

import numpy as np
import pytest

from slipsurface.fe2d.core.enums import PlasticFlag
from slipsurface.fe2d.fem.materials import MohrCoulomb


def test_tresca_pure_shear_exact_plastic_plateau_and_unload():
    e, nu, cohesion = 20000.0, 0.25, 15.0
    shear_modulus = e / (2 * (1 + nu))
    model = MohrCoulomb(e, nu, cohesion, 0.0, 0.0)
    initial = np.array([[-100.0, -100.0, -100.0, 0.0]])
    q0 = np.zeros((1, 1))
    gamma = 4.0 * cohesion / shear_modulus
    strain = np.array([[0.0, 0.0, 0.0, gamma]])
    sigma, q, tangent, flag = model.integrate(initial, strain, q0)
    assert flag[0] == PlasticFlag.SHEAR
    assert sigma[0, 3] == pytest.approx(cohesion, rel=1e-6)
    assert np.mean(sigma[0, :3]) == pytest.approx(-100.0, abs=1e-8)
    assert model.yield_function(sigma)[0] == pytest.approx(0.0, abs=1e-7)
    assert q[0, 0] > 0.0
    assert np.isfinite(tangent).all()
    # Integration is pure: no mutation of caller-owned committed state.
    assert initial[0, 3] == 0.0
    assert q0[0, 0] == 0.0
    # An unloading step stays elastic and decreases shear by G*dgamma.
    dgamma = -cohesion / (2 * shear_modulus)
    unloaded, q_unloaded, _, unloading_flag = model.integrate(
        sigma, np.array([[0.0, 0.0, 0.0, dgamma]]), q
    )
    assert unloading_flag[0] == PlasticFlag.ELASTIC
    assert unloaded[0, 3] == pytest.approx(cohesion / 2, rel=1e-6)
    assert q_unloaded[0, 0] == pytest.approx(q[0, 0])


def test_tresca_multiple_increments_match_single_plastic_shear_increment():
    model = MohrCoulomb(20000.0, 0.25, 15.0, 0.0, 0.0)
    initial = np.array([[-100.0, -100.0, -100.0, 0.0]])
    total = np.array([[0.0, 0.0, 0.0, 0.008]])
    one_shot, _, _, _ = model.integrate(initial, total, np.zeros((1, 1)))
    state, q = initial.copy(), np.zeros((1, 1))
    for _ in range(16):
        state, q, _, _ = model.integrate(state, total / 16, q)
    assert np.allclose(state, one_shot, rtol=1e-6, atol=1e-6)
    assert state[0, 3] == pytest.approx(15.0, rel=1e-6)
    assert q[0, 0] > 0.0

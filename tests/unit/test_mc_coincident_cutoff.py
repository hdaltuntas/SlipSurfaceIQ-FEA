"""Explicit Rankine flow at the MC apex: analytic stress and exact tangent.

For psi=0, MC corrections are isochoric. Trial mean stress above the common
apex needs Rankine flow. At sigma1=sig_t=c*cot(phi), MC admissibility also
requires sigma2=sigma3=sig_t, so the returned stress is fixed analytically.
"""

import numpy as np
import pytest

from slipsurface.fe2d.core.enums import PlasticFlag
from slipsurface.fe2d.core.errors import MaterialIntegrationError
from slipsurface.fe2d.fem.materials.mohr_coulomb import MohrCoulomb

DIRECTIONS = [
    [1.0, 1.0, 1.0, 0.0],
    [3.0, -1.0, -1.0, 0.0],
    [10.0, -8.0, -1.0, 0.0],
    [1.0, 1.0, -1.0, 5.0],
]


@pytest.mark.parametrize("c", [0.0, 10.0])
@pytest.mark.parametrize("direction", DIRECTIONS)
def test_coincident_cutoff_returns_fixed_apex_with_exact_derivative(c, direction):
    plain = MohrCoulomb(3e4, 0.3, c, 30.0, 0.0)
    mc = MohrCoulomb(3e4, 0.3, c, 30.0, 0.0, sig_t=plain.apex)
    assert mc.has_t
    initial = np.array([[mc.apex, mc.apex, mc.apex, 0.0]])
    deps = np.array([direction]) * 1e-4
    qn = np.zeros((1, 1))
    # Without Rankine flow there is no admissible isochoric return for this trial.
    with pytest.raises(MaterialIntegrationError):
        plain.integrate(initial, deps, qn)
    stress, q, tangent, flags = mc.integrate(initial, deps, qn)
    np.testing.assert_allclose(stress, initial, atol=1e-10)
    assert flags[0] == PlasticFlag.TENSION
    assert q[0, 0] >= 0
    assert mc.yield_function(stress)[0] < 1e-9
    np.testing.assert_array_equal(tangent, 0.0)
    for j in range(4):
        eps = np.zeros((1, 4))
        eps[0, j] = 1e-8
        sp = mc.integrate(initial, deps + eps, qn)[0]
        sm = mc.integrate(initial, deps - eps, qn)[0]
        np.testing.assert_allclose((sp - sm) / 2e-8, tangent[0, :, j][None], atol=1e-6)


def test_explicit_cutoff_is_kept_at_apex_but_not_above_it():
    plain = MohrCoulomb(3e4, 0.3, 10.0, 30.0, 0.0)
    assert MohrCoulomb(3e4, 0.3, 10.0, 30.0, 0.0, sig_t=plain.apex).has_t
    assert not MohrCoulomb(3e4, 0.3, 10.0, 30.0, 0.0, sig_t=plain.apex + 1.0).has_t
    assert not plain.has_t


def test_associated_mc_apex_tangent_is_also_exactly_zero():
    mc = MohrCoulomb(3e4, 0.3, 0.0, 30.0, 30.0)
    stress, _, tangent, flags = mc.integrate(
        np.zeros((1, 4)), np.array([[1e-4, 1e-4, 1e-4, 0.0]]), np.zeros((1, 1))
    )
    np.testing.assert_allclose(stress, 0.0, atol=1e-10)
    np.testing.assert_array_equal(tangent, 0.0)
    assert flags[0] == PlasticFlag.APEX

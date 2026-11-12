from __future__ import annotations

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.errors import ModelError
from slipsurface.fe2d.fem.bond_slip import bond_slip_return


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": "", "stiffness": 1.0, "strength": 1.0},
        {"name": "bond", "stiffness": 0.0, "strength": 1.0},
        {"name": "bond", "stiffness": float("nan"), "strength": 1.0},
        {"name": "bond", "stiffness": 1.0, "strength": 0.0},
        {"name": "bond", "stiffness": 1.0, "strength": float("inf")},
    ],
)
def test_bond_slip_spec_rejects_nonphysical_values(kwargs):
    with pytest.raises(ModelError):
        api.BondSlipSpec(**kwargs)


def test_rs2_tutorial_properties_remain_elastic_at_small_slip():
    spec = api.BondSlipSpec("tieback", stiffness=10_000.0, strength=5_000.0)
    q, kt, yielded = bond_slip_return(0.0, np.array([0.001, 0.010, -0.010]), spec)
    np.testing.assert_allclose(q, [10.0, 100.0, -100.0])
    np.testing.assert_allclose(kt, 10_000.0)
    assert not yielded.any()
    assert spec.strength / spec.stiffness == pytest.approx(0.5)


@pytest.mark.parametrize("sign", [-1.0, 1.0])
def test_symmetric_bond_strength_cap_and_zero_plastic_tangent(sign):
    spec = api.BondSlipSpec("bond", stiffness=2_000.0, strength=10.0)
    q, kt, yielded = bond_slip_return(0.0, sign * 0.010, spec)
    assert float(q) == pytest.approx(sign * 10.0)
    assert float(kt) == 0.0
    assert bool(yielded)


def test_unloading_from_yield_is_elastic_again():
    spec = api.BondSlipSpec("bond", stiffness=2_000.0, strength=10.0)
    q, kt, yielded = bond_slip_return(10.0, -0.003, spec)
    assert float(q) == pytest.approx(4.0)
    assert float(kt) == pytest.approx(2_000.0)
    assert not bool(yielded)


def test_algorithmic_tangent_matches_finite_difference_in_smooth_branch():
    spec = api.BondSlipSpec("bond", stiffness=3_500.0, strength=100.0)
    q0, ds, eps = 12.0, 0.004, 1e-8
    q, kt, yielded = bond_slip_return(q0, ds, spec)
    qp = bond_slip_return(q0, ds + eps, spec)[0]
    qm = bond_slip_return(q0, ds - eps, spec)[0]
    numerical = float((qp - qm) / (2 * eps))
    assert not bool(yielded)
    assert numerical == pytest.approx(float(kt), rel=1e-9)
    assert float(q) == pytest.approx(q0 + spec.stiffness * ds)


def test_nonfinite_or_inadmissible_committed_state_is_rejected():
    spec = api.BondSlipSpec("bond", stiffness=2_000.0, strength=10.0)
    with pytest.raises(ValueError, match="finite"):
        bond_slip_return(np.nan, 0.0, spec)
    with pytest.raises(ValueError, match="exceeds"):
        bond_slip_return(10.1, 0.0, spec)

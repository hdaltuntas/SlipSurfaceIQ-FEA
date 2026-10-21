"""Explicit Rankine flow at the MC apex: analytic stress and exact tangent.

For psi=0, MC corrections are isochoric. Trial mean stress above the common
apex needs Rankine flow. At sigma1=sig_t=c*cot(phi), MC admissibility also
requires sigma2=sigma3=sig_t, so the returned stress is fixed analytically.
"""

import json
from pathlib import Path

import numpy as np
import pytest
from scipy.optimize import nnls

from slipsurface.fe2d.core.enums import PlasticFlag
from slipsurface.fe2d.core.errors import MaterialIntegrationError, ModelError
from slipsurface.fe2d.fem.materials import build
from slipsurface.fe2d.fem.materials.mohr_coulomb import MohrCoulomb
from slipsurface.fe2d.model.materials import MaterialSpec

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


@pytest.mark.parametrize("psi", [5.0, 30.0])
def test_trial_mean_above_apex_does_not_clip_a_dilatant_shear_return(psi):
    mc = MohrCoulomb(3e4, 0.3, 10, 30, psi, rankine_at_apex=True)
    trial = np.array([[300.0, -100.0, -110.0, 0.0]])
    assert trial[0, :3].mean() > mc.apex
    stress, _, tangent, flags = mc.integrate(trial, np.zeros((1, 4)), np.zeros((1, 1)))
    assert flags[0] == PlasticFlag.SHEAR
    assert np.ptp(stress[0, :3]) > 1.0
    assert np.max(mc.yield_function(stress)) < 1e-9
    assert np.linalg.norm(tangent) > 0


@pytest.mark.parametrize("F", [0.8, 1.0, 1.25, 1.5625, 2.0, 10.0])
def test_rankine_apex_is_exactly_retained_under_strength_reduction(F):
    spec = MaterialSpec.mohr_coulomb("soil", 1e5, 0.3, 10, 20, 0, rankine_at_apex=True)
    mc = build(spec.with_strength_factor(F))
    assert mc.has_t and mc.st == mc.apex
    assert mc.apex == pytest.approx(10 / np.tan(np.radians(20)), rel=1e-14)
    assert mc.psi == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"phi": 0},
        {"sig_t": 0},
        {"rankine_at_apex": 2},
    ],
)
def test_invalid_apex_flow_options_are_rejected(kwargs):
    params = {"E": 3e4, "nu": 0.3, "c": 10, "phi": 30, "rankine_at_apex": True}
    params.update(kwargs)
    with pytest.raises(ValueError):
        MohrCoulomb(**params)
    with pytest.raises(ModelError):
        MaterialSpec.mohr_coulomb("soil", **params)


@pytest.mark.parametrize(
    "case",
    json.loads(
        (Path(__file__).parents[1] / "verification/data/material_return_failures.json").read_text(
            encoding="utf-8"
        )
    ),
    ids=lambda case: case["case"],
)
def test_recorded_failures_return_with_explicit_rankine_flow_and_positive_multipliers(case):
    data = case["details"]
    mc = MohrCoulomb(**data["params"], rankine_at_apex=True)
    point = data["points"][0]
    sn, deps, qn = (np.array([point[k]]) for k in ("sig_n", "deps", "q_n"))
    stress, q, tangent, flags = mc.integrate(sn, deps, qn)
    np.testing.assert_allclose(stress, [[mc.apex, mc.apex, mc.apex, 0]], atol=1e-11)
    np.testing.assert_array_equal(tangent, 0)
    assert flags[0] == PlasticFlag.TENSION and q[0, 0] >= qn[0, 0]
    assert mc.yield_function(stress)[0] < 1e-9
    for j in range(4):
        step = np.zeros((1, 4))
        step[0, j] = 1e-9
        sp = mc.integrate(sn, deps + step, qn)[0]
        sm = mc.integrate(sn, deps - step, qn)[0]
        np.testing.assert_allclose((sp - sm) / 2e-9, tangent[0, :, j][None], atol=1e-6)
    # Independently decompose the correction into six MC and three associated
    # Rankine potentials. Non-negative multipliers and exact reconstruction
    # certify Koiter admissibility for these recorded cases.
    sx, sy, sz, t = (sn + deps @ mc.elastic_D().T)[0]
    trial = np.linalg.eigvalsh([[sx, t, 0], [t, sy, 0], [0, 0, sz]])
    dep = np.linalg.solve(mc.elastic_D()[:3, :3], trial - mc.apex)
    normals = np.array(
        [
            [1, -1, 0],
            [-1, 1, 0],
            [1, 0, -1],
            [-1, 0, 1],
            [0, 1, -1],
            [0, -1, 1],
            [1, 0, 0],
            [0, 1, 0],
            [0, 0, 1],
        ],
        dtype=float,
    )
    multipliers, residual = nnls(normals.T, dep)
    assert residual < 1e-12
    assert np.all(multipliers >= 0)
    assert multipliers[6:].sum() == pytest.approx(dep.sum(), rel=1e-9)
    assert multipliers[6:].sum() > 0

"""Fast analytical/diagnostic checks for the optional F7 Salencon audit.

Full three-mesh nonlinear solves are opt-in and not part of CI.
"""

from __future__ import annotations

import runpy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

AUDIT = runpy.run_path(
    str(
        Path(__file__).resolve().parents[2]
        / "examples"
        / "f7_salencon_mesh_audit.py"
    )
)


def test_reference_has_elastic_branch_and_zero_unloading():
    solve = AUDIT["analytical_cavity"]
    a = AUDIT["A"]
    p0 = AUDIT["P0"]
    assert solve(p0, 0.0) == pytest.approx((a, 0.0), abs=1e-12)
    # Support pressure close to the in-situ pressure stays purely elastic.
    radius, displacement = solve(0.9 * p0, 0.0)
    g = AUDIT["E"] / (2 * (1 + AUDIT["NU"]))
    assert radius == pytest.approx(a)
    assert displacement == pytest.approx(-0.1 * p0 * a / (2 * g))


@pytest.mark.parametrize("psi", [0.0, 15.0, 30.0])
def test_reference_plastic_radius_is_independent_of_dilation(psi):
    solve = AUDIT["analytical_cavity"]
    r, u = solve(AUDIT["PI"], psi)
    r0, _ = solve(AUDIT["PI"], 0.0)
    assert r > AUDIT["A"]
    assert r == pytest.approx(r0, rel=1e-12)
    assert u < 0.0
    assert np.isfinite(u)


@pytest.mark.parametrize("bad_pi,bad_psi", [
    (-0.01, 0.0),
    (101.0, 0.0),
    (10.0, -0.1),
    (10.0, 31.0),
])
def test_reference_rejects_invalid_pressure_and_dilation(bad_pi, bad_psi):
    with pytest.raises(ValueError):
        AUDIT["analytical_cavity"](bad_pi, bad_psi)


def test_plastic_front_brackets_inside_and_outside_points():
    points = np.array([
        [[1.05, 0.0], [1.30, 0.0]],
        [[2.1, 0.0], [2.3, 0.0]],
    ])
    flags = np.array([[1, 1], [0, 0]], dtype=np.uint8)
    result = AUDIT["plastic_radius_from_gauss"](points, flags)
    assert result == pytest.approx(0.5 * (1.3 + 2.1))


def test_front_returns_none_if_all_or_none_plastic():
    points = np.array([[[1.0, 0.0], [2.0, 0.0]]])
    find = AUDIT["plastic_radius_from_gauss"]
    assert find(points, np.zeros((1, 2), dtype=np.uint8)) is None
    assert find(points, np.ones((1, 2), dtype=np.uint8)) is None
    with pytest.raises(ValueError, match="align"):
        find(points, np.ones((1, 3), dtype=np.uint8))


def test_stage_diagnostics_tracks_accepted_and_rejected_iterations():
    steps = [
        SimpleNamespace(converged=True, residuals=[0.3, 1e-6], iterations=3),
        SimpleNamespace(converged=False, residuals=[0.2], iterations=5),
        SimpleNamespace(converged=True, residuals=[0.1, 2e-7], iterations=2),
    ]
    stage = SimpleNamespace(
        history=SimpleNamespace(steps=steps), lam=1.0,
    )
    result = AUDIT["stage_diagnostics"](stage)
    assert result["accepted_steps"] == 2
    assert result["rejected_steps"] == 1
    assert result["newton_iterations"] == 10
    assert result["last_accepted_residual"] == pytest.approx(2e-7)
    assert result["load_factor"] == pytest.approx(1.0)

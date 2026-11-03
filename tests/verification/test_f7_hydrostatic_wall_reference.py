"""F7 exact hydrostatic vertical-wall pressure benchmark for FEM edge forces."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from slipsurface.fe2d.model.boundary import WaterCondition
from slipsurface.fe2d.post.hydrostatic_reference import (
    compare_vertical_water_edge,
    vertical_wall_water_resultant,
)

GAMMA = 9.81


@pytest.mark.parametrize("head,resultant", [
    (0.0, 0.0),
    (2.0, 0.5 * GAMMA * 2.0**2),
    (4.0, 0.5 * GAMMA * 4.0**2),
    (8.0, GAMMA * (8.0 * 4.0 - 0.5 * 4.0**2)),
])
def test_closed_form_vertical_wall_resultant(head, resultant):
    out = vertical_wall_water_resultant(0., 4., head, -1.)
    assert out["hydrostatic_resultant_kn_per_m"] == pytest.approx(resultant)
    assert out["force_fx_kn_per_m"] == pytest.approx(resultant)
    assert out["force_fy_kn_per_m"] == 0.0
    reversed_wall = vertical_wall_water_resultant(4., 0., head, +1.)
    assert reversed_wall["force_fx_kn_per_m"] == pytest.approx(-resultant)


@pytest.mark.parametrize("quadratic", [False, True])
def test_fem_boundary_quadrature_matches_exact_fully_submerged_wall(quadratic):
    # Wall from y=0 to y=-4. Material is to the right, water pressure acts +X.
    coords = np.array([
        [0., 0.], [0., -4.], [0., -2.],
    ]) if quadratic else np.array([[0., 0.], [0., -4.]])
    edge = [0, 1, 2] if quadratic else [0, 1]
    mesh = SimpleNamespace(coords=coords)
    water = WaterCondition.piezo([(0., 0.)])
    out = compare_vertical_water_edge(
        mesh, edge, inner=(2., -2.), water=water
    )
    assert out["force_fx_kn_per_m"] == pytest.approx(0.5 * GAMMA * 4.**2)
    assert out["fem_fx_kn_per_m"] == pytest.approx(out["force_fx_kn_per_m"], rel=1e-12)
    assert out["fem_fy_kn_per_m"] == pytest.approx(0., abs=1e-12)
    assert out["relative_resultant_error"] < 1e-12


def test_water_table_at_segment_boundary_keeps_exact_total():
    mesh = SimpleNamespace(coords=np.array([
        [0., 0.], [0., -2.], [0., -4.],
    ]))
    water = WaterCondition.piezo([(0., -2.)])
    upper = compare_vertical_water_edge(mesh, [0, 1], (2., -1.), water)
    lower = compare_vertical_water_edge(mesh, [1, 2], (2., -3.), water)
    assert upper["force_fx_kn_per_m"] == 0.
    assert lower["force_fx_kn_per_m"] == pytest.approx(GAMMA * 2.**2 / 2)
    assert upper["relative_resultant_error"] < 1e-12
    assert lower["relative_resultant_error"] < 1e-12


def test_crossing_unmeshed_water_table_reports_integration_error():
    mesh = SimpleNamespace(coords=np.array([
        [0., 0.], [0., -4.],
    ]))
    water = WaterCondition.piezo([(0., -1.5)])
    out = compare_vertical_water_edge(mesh, [0, 1], (2., -2.), water)
    assert out["hydrostatic_resultant_kn_per_m"] == pytest.approx(
        GAMMA * (2.5**2) / 2,
    )
    assert out["relative_resultant_error"] >= 0
    assert np.isfinite(out["relative_resultant_error"])


def test_invalid_hydrostatic_reference_geometry_is_rejected():
    with pytest.raises(ValueError, match="positive"):
        vertical_wall_water_resultant(0., 0., 2., +1.)
    with pytest.raises(ValueError, match="outward_nx"):
        vertical_wall_water_resultant(0., 2., 2., 0.5)
    mesh = SimpleNamespace(coords=np.array([
        [0., 0.], [1., -2.],
    ]))
    with pytest.raises(ValueError, match="vertical"):
        compare_vertical_water_edge(
            mesh, [0, 1], (2., -1.), WaterCondition.piezo([(0., 0.)])
        )
    vertical = SimpleNamespace(coords=np.array([
        [0., 0.], [0., -2.],
    ]))
    with pytest.raises(ValueError, match="horizontal"):
        compare_vertical_water_edge(
            vertical, [0, 1], (2., -1.),
            WaterCondition.piezo([(0., 0.), (1., -1.)]),
        )

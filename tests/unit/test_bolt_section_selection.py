"""Regression tests for diameter-derived bolt sections and legacy CAD projects."""

import math

import pytest

from slipsurface.fe2d.cad.supports import SupportAssignment, bolt_section


def test_bolt_nominal_section_25mm_b500b():
    ea, yield_force = bolt_section(25, 0)
    area = math.pi * 0.025**2 / 4
    assert ea == pytest.approx(200e6 * area)
    assert yield_force == pytest.approx(500e3 * area)


def test_larger_diameter_scales_by_area():
    ea25, fy25 = bolt_section(25, 1)
    ea50, fy50 = bolt_section(50, 1)
    assert ea50 / ea25 == pytest.approx(4)
    assert fy50 / fy25 == pytest.approx(4)


@pytest.mark.parametrize("diameter,grade", [(0, 0), (-1, 1), (25, 88)])
def test_invalid_bolt_section_rejected(diameter, grade):
    with pytest.raises(ValueError):
        bolt_section(diameter, grade)


def test_legacy_bolt_properties_preserved():
    assignment = SupportAssignment(
        "AnchorLine", "bolt",
        {"EA": 123456.0, "T_yield": 175.0,
         "pretension": 0.0, "spacing_out_of_plane": 1.0},
    )
    assert assignment.spec().EA == pytest.approx(123456)
    assert assignment.spec().T_yield == pytest.approx(175)
    assert "diameter_mm" not in assignment.properties


def test_new_bolt_diameter_overrides_initial_display_stiffness():
    assignment = SupportAssignment(
        "AnchorLine", "bolt", {"diameter_mm": 32.0, "grade_code": 2}
    )
    ea, fy = bolt_section(32, 2)
    assert assignment.spec().EA == pytest.approx(ea)
    assert assignment.spec().T_yield == pytest.approx(fy)

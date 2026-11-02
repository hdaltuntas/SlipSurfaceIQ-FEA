"""Shotcrete 28-day reference vs first-stage maturity regression checks."""

import pytest

from slipsurface.fe2d.cad.lining import LiningSystem
from slipsurface.fe2d.model.materials import LinerSpec


def test_first_stage_reduces_concrete_only():
    lining = LiningSystem(mesh="Q257", mesh_layers=2, rib="HEB 140",
                          initial_capacity_percent=35.0)
    ea28, ei28 = lining.stiffness()
    early_ea, early_ei = lining.stiffness_at_capacity(35.0)
    concrete_ea = lining.E_shotcrete * lining.thickness
    concrete_ei = lining.E_shotcrete * lining.thickness**3 / 12
    assert early_ea == pytest.approx(ea28 - 0.65 * concrete_ea)
    assert early_ei == pytest.approx(ei28 - 0.65 * concrete_ei)
    assert lining.stiffness_at_capacity(100) == pytest.approx((ea28, ei28))


def test_stage_equivalent_beam_keeps_steel_stiffness():
    lining = LiningSystem(mesh="Q335", mesh_layers=2, rib="HEB 120",
                          initial_capacity_percent=20.0)
    full = LinerSpec("lining", **lining.liner_properties())
    early = full.at_shotcrete_capacity(20.0)
    later = full.at_shotcrete_capacity(100.0)
    assert early.E * early.A == pytest.approx(lining.stiffness_at_capacity(20.0)[0])
    assert early.E * early.I == pytest.approx(lining.stiffness_at_capacity(20.0)[1])
    assert later.E * later.A == pytest.approx(lining.stiffness()[0])
    assert later.E * later.I == pytest.approx(lining.stiffness()[1])


def test_strength_reference_scales_for_display():
    lining = LiningSystem(fc28=32000, ft28=2500, initial_capacity_percent=40)
    assert lining.strengths_at_capacity(40) == pytest.approx((12800, 1000))
    assert lining.strengths_at_capacity(100) == pytest.approx((32000, 2500))


@pytest.mark.parametrize("percent", [-1, 0, 101, float("nan")])
def test_invalid_percentage(percent):
    with pytest.raises(ValueError):
        LiningSystem(initial_capacity_percent=percent)

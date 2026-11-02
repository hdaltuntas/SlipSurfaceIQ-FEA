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


def test_steel_contribution_is_not_reduced_at_early_capacity():
    """Capacity scales only the concrete delta, regardless of installed steel."""
    plain = LiningSystem(mesh="None", rib="None", mesh_layers=1,
                         initial_capacity_percent=30)
    reinforced = LiningSystem(mesh="Q335", mesh_layers=2, rib="HEB 160",
                              initial_capacity_percent=30)
    plain_early = plain.stiffness_at_capacity(30)
    reinforced_early = reinforced.stiffness_at_capacity(30)
    plain_full = plain.stiffness_at_capacity(100)
    reinforced_full = reinforced.stiffness_at_capacity(100)
    for i in (0, 1):
        steel_full = reinforced_full[i] - plain_full[i]
        steel_early = reinforced_early[i] - plain_early[i]
        assert steel_early == pytest.approx(steel_full)


def test_zero_shotcrete_metadata_does_not_modify_legacy_liner():
    """Legacy beam specifications retain their original mechanical stiffness."""
    liner = LinerSpec("legacy", E=2e7, nu=0.2, A=0.15, I=0.0003,
                      As=0.125, unit_weight=24)
    reduced = liner.at_shotcrete_capacity(30)
    assert reduced.E * reduced.A == pytest.approx(liner.E * liner.A)
    assert reduced.E * reduced.I == pytest.approx(liner.E * liner.I)


def test_early_strength_scaling_does_not_mutate_28_day_reference():
    liner = LiningSystem(fc28=35000, ft28=3000, initial_capacity_percent=25)
    assert liner.strengths_at_capacity(25) == pytest.approx((8750, 750))
    assert liner.fc28 == 35000
    assert liner.ft28 == 3000

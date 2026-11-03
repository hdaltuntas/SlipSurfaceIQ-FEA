"""F7 independently derived hydrostatic and saturated gravity reaction budgets."""

from __future__ import annotations

import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.units import GAMMA_W
from slipsurface.fe2d.mesh import layered_box
from slipsurface.fe2d.post.saturated_column_balance import (
    saturated_column_budget,
    saturated_column_budget_by_stage,
)

WIDTH = 2.0
HEIGHT = 10.0
G_UNSAT = 17.0
G_SAT = 20.0


def column(water, stages=()):
    mesh = layered_box(
        WIDTH, [0.0, -4.0], -HEIGHT, nx=2, ny_per_layer=[4, 6]
    )
    material = api.MaterialSpec.elastic(
        "soil", 20000.0, 0.3, gamma=G_UNSAT, gamma_sat=G_SAT
    )
    model = api.Model(
        api.Analysis.PLANE_STRAIN, mesh, {"soil": material},
        {1: "soil", 2: "soil"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        initial=api.InitialStress("gravity", water=water),
        stages=list(stages),
    )
    return model


@pytest.mark.parametrize("head,expected", [
    (0.0, WIDTH * HEIGHT * G_SAT),
    (-4.0, WIDTH * (4.0 * G_UNSAT + 6.0 * G_SAT)),
    (-10.0, WIDTH * HEIGHT * G_UNSAT),
    (3.0, WIDTH * (HEIGHT * G_SAT + 3.0 * GAMMA_W)),
])
def test_initial_hydrostatic_reaction_matches_independent_weight(head, expected):
    model = column(api.WaterCondition.piezo([(0.0, head)]))
    result = api.run(model)
    balance = saturated_column_budget(model, result)
    assert balance["expected_ry_kn_per_m"] == pytest.approx(expected, rel=1e-10)
    assert balance["reaction_ry_kn_per_m"] == pytest.approx(expected, rel=1e-8)
    assert balance["reaction_rx_kn_per_m"] == pytest.approx(0.0, abs=1e-7)
    assert balance["relative_residual"] < 1e-7
    assert saturated_column_budget_by_stage(model, result)[0]["status"] == "passed"


def test_water_table_lowering_preserves_reaction_equilibrium_across_stages():
    initial_water = api.WaterCondition.piezo([(0., 0.)])
    lowered = api.WaterCondition.piezo([(0., -4.)])
    model = column(initial_water, stages=[
        api.Stage("lower head", water=lowered),
    ])
    result = api.run(model)
    budget = saturated_column_budget(model, result, 0)
    assert budget["expected_ry_kn_per_m"] == pytest.approx(
        WIDTH * (4.0 * G_UNSAT + 6.0 * G_SAT)
    )
    assert budget["reaction_ry_kn_per_m"] == pytest.approx(
        budget["expected_ry_kn_per_m"], rel=1e-8
    )
    assert [row["status"] for row in saturated_column_budget_by_stage(
        model, result
    )] == ["passed", "passed"]


def test_unaligned_water_table_is_explicitly_unsupported():
    model = column(api.WaterCondition.piezo([(0., -2.)]))
    result = api.run(model)
    with pytest.raises(ValueError, match="element edges"):
        saturated_column_budget(model, result)
    assert saturated_column_budget_by_stage(model, result)[0]["status"] == "unsupported"


def test_nonhorizontal_water_head_and_staged_external_loads_rejected():
    model = column(api.WaterCondition.piezo([(0., 0.), (2., -1.)]))
    result = api.run(model)
    with pytest.raises(ValueError, match="horizontal"):
        saturated_column_budget(model, result)

    initial = api.WaterCondition.piezo([(0., 0.)])
    loaded = column(initial, stages=[
        api.Stage("loaded", water=initial, loads=(api.EdgeLoad("top", qn=10.),))
    ])
    simulated = api.run(loaded)
    with pytest.raises(ValueError, match="Stage loads"):
        saturated_column_budget(loaded, simulated, 0)
    assert saturated_column_budget_by_stage(loaded, simulated)[1]["status"] == (
        "unsupported"
    )

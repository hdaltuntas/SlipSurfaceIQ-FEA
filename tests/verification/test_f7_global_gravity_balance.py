"""F7 dry staged excavation: independently integrated weight vs support reactions."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.mesh import layered_box
from slipsurface.fe2d.post.global_balance import (
    gravity_equilibrium_budget,
    gravity_equilibrium_by_stage,
)

WIDTH = 4.0
GAMMA = 18.0


@pytest.mark.parametrize("etype", [ElemType.T3, ElemType.T6])
def test_global_equilibrium_survives_staged_top_layer_excavation(etype):
    mesh = layered_box(
        WIDTH, [0.0, -3.0], -6.0,
        nx=4, ny_per_layer=[4, 4], etype=etype,
    )
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"soil": api.MaterialSpec.elastic(
            "soil", 20000.0, 0.3, gamma=GAMMA,
        )},
        region_material={1: "soil", 2: "soil"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        initial=api.InitialStress("gravity"),
        stages=[
            api.Stage("before excavation", active_regions={1, 2}),
            api.Stage("remove upper layer", active_regions={2}),
        ],
    )
    solved = api.run(model)
    for index, thickness in enumerate((6.0, 3.0)):
        budget = gravity_equilibrium_budget(model, solved, index)
        expected = WIDTH * thickness * GAMMA
        assert budget["soil_weight_kn_per_m"] == pytest.approx(expected, rel=1e-10)
        assert budget["beam_weight_kn_per_m"] == 0.0
        assert budget["reaction_fy_kn_per_m"] == pytest.approx(
            expected, rel=1e-7, abs=1e-6,
        )
        assert budget["reaction_fx_kn_per_m"] == pytest.approx(0.0, abs=1e-6)
        assert budget["relative_resultant_imbalance"] < 1e-7
    rows = gravity_equilibrium_by_stage(model, solved)
    assert [entry["status"] for entry in rows] == ["checked", "checked"]


def test_budget_declines_unsupported_external_load_instead_of_faking_balance():
    mesh = layered_box(4.0, [0.0, -3.0], -6.0, 2, [2, 2])
    stage = api.Stage(
        "loaded", loads=(api.EdgeLoad("top", qn=100.0),),
    )
    model = api.Model(
        api.Analysis.PLANE_STRAIN, mesh,
        {"soil": api.MaterialSpec.elastic("soil", 20000.0, 0.3, gamma=GAMMA)},
        {1: "soil", 2: "soil"},
        fixities=(api.Fixity("bottom", True, True),
                  api.Fixity("left", True, False),
                  api.Fixity("right", True, False)),
        initial=api.InitialStress("gravity"),
        stages=[stage],
    )
    mock = SimpleNamespace(stages=[SimpleNamespace(name=stage.name)])
    with pytest.raises(ValueError, match="External or seismic"):
        gravity_equilibrium_budget(model, mock, 0)
    summary = gravity_equilibrium_by_stage(model, mock)
    assert summary[0]["status"] == "unsupported"
    assert "External or seismic" in summary[0]["reason"]


def test_budget_rejects_out_of_range_stage():
    mesh = layered_box(4.0, [0.0, -3.0], -6.0, 2, [2, 2])
    model = api.Model(
        api.Analysis.PLANE_STRAIN, mesh,
        {"soil": api.MaterialSpec.elastic("soil", 20000.0, 0.3, gamma=GAMMA)},
        {1: "soil", 2: "soil"},
        fixities=(api.Fixity("bottom", True, True),),
        initial=api.InitialStress("gravity"),
        stages=[api.Stage("stage")],
    )
    mock = SimpleNamespace(stages=[])
    with pytest.raises(IndexError, match="outside"):
        gravity_equilibrium_budget(model, mock, 0)

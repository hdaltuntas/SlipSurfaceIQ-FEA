"""F7 local Gauss-point groundwater and effective-stress verification."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.core.units import GAMMA_W
from slipsurface.fe2d.mesh import layered_box
from slipsurface.fe2d.post.local_water_stress import (
    column_reference,
    local_column_errors,
    local_column_errors_by_stage,
)

WIDTH = 2.0
HEIGHT = 10.0
G_UNSAT = 17.0
G_SAT = 20.0


def column(etype, rows):
    mesh = layered_box(
        WIDTH, [0.0, -4.0], -HEIGHT, nx=2,
        ny_per_layer=[rows, int(1.5 * rows)], etype=etype,
    )
    mat = api.MaterialSpec.elastic(
        "soil", 20000.0, 0.3, gamma=G_UNSAT, gamma_sat=G_SAT,
    )
    return api.Model(
        api.Analysis.PLANE_STRAIN, mesh,
        {"soil": mat}, {1: "soil", 2: "soil"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        initial=api.InitialStress(
            "gravity", water=api.WaterCondition.piezo([(0.0, 0.0)])
        ),
        stages=[
            api.Stage(
                "lower water table",
                water=api.WaterCondition.piezo([(0.0, -4.0)]),
            )
        ],
    )


def test_reference_is_piecewise_and_tension_positive():
    elevations = np.array([0., -2., -4., -7., -10.])
    pore, sig = column_reference(
        elevations, -4.0, G_UNSAT, G_SAT,
    )
    assert pore == pytest.approx(
        GAMMA_W * np.array([0., 0., 0., 3., 6.])
    )
    assert sig == pytest.approx(-np.array([
        0., 2 * G_UNSAT, 4 * G_UNSAT,
        4 * G_UNSAT + 3 * (G_SAT - GAMMA_W),
        4 * G_UNSAT + 6 * (G_SAT - GAMMA_W),
    ]))


@pytest.mark.parametrize("etype", [ElemType.T3, ElemType.T6])
@pytest.mark.parametrize("rows", [2, 4])
def test_initial_and_lowered_head_gauss_points_match_analytic_profile(etype, rows):
    model = column(etype, rows)
    result = api.run(model)
    initial = local_column_errors(model, result)
    lowered = local_column_errors(model, result, 0)
    assert initial["gauss_points"] > 0
    assert lowered["gauss_points"] > 0
    assert initial["max_abs_pore_error_kpa"] < 1e-7
    assert initial["max_abs_effective_stress_error_kpa"] < 1e-6
    assert lowered["max_abs_pore_error_kpa"] < 1e-7
    assert lowered["max_abs_effective_stress_error_kpa"] < 1e-6
    assert [row["status"] for row in local_column_errors_by_stage(
        model, result
    )] == ["passed", "passed"]


def test_corrupted_local_pore_field_cannot_be_misreported_as_pass():
    model = column(ElemType.T3, 2)
    result = api.run(model)
    corrupted_pore = {
        tag: field.copy() for tag, field in result.initial.pore.items()
    }
    corrupted_pore["soil"][0, 0] += 25.0
    tampered_initial = replace(result.initial, pore=corrupted_pore)
    tampered = SimpleNamespace(
        initial=tampered_initial, stages=result.stages, geom=result.geom,
    )
    sample = local_column_errors(model, tampered)
    assert sample["max_abs_pore_error_kpa"] >= 25.0 - 1e-7
    assert local_column_errors_by_stage(model, tampered)[0]["status"] == "failed"


def test_nonhorizontal_groundwater_explicitly_unsupported():
    model = column(ElemType.T3, 2)
    model.initial = api.InitialStress(
        "gravity", water=api.WaterCondition.piezo([(0., 0.), (2., -2.)])
    )
    result = api.run(model)
    with pytest.raises(ValueError, match="Sloping"):
        local_column_errors(model, result)
    assert local_column_errors_by_stage(model, result)[0]["status"] == "unsupported"

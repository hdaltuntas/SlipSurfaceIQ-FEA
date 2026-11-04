"""Target pore pressure and history-blended applied water loads are distinct."""

from __future__ import annotations

import copy
import json
import runpy
from pathlib import Path

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.core.units import GAMMA_W
from slipsurface.fe2d.mesh import rectangle
from slipsurface.fe2d.post.incremental_hydrostatic_budget import (
    incremental_hydrostatic_budget_by_stage,
)


def column(etype):
    mesh = rectangle(2., 10., 2, 5, etype=etype, origin=(0., -10.))
    initial = api.WaterCondition.piezo([[0., 3.]])
    lowered = api.WaterCondition.piezo([[0., 1.]])
    return api.Model(
        api.Analysis.PLANE_STRAIN, mesh,
        {"soil": api.MaterialSpec.elastic("soil", 25000., 0.3, gamma=17., gamma_sat=20.)},
        {1: "soil"},
        fixities=(api.Fixity("bottom", True, True), api.Fixity("left", True, False),
                  api.Fixity("right", True, False)),
        initial=api.InitialStress("gravity", water=initial), stages=[
            api.Stage("lower 40 percent", water=lowered, load_split=0.4),
            api.Stage("lower 70 percent", water=lowered, load_split=0.5),
            api.Stage("complete lowering", water=lowered),
            api.Stage("dry"),
        ],
    )


@pytest.mark.parametrize("etype", [ElemType.T3, ElemType.T6, ElemType.Q4, ElemType.Q8])
def test_partial_drawdown_has_exact_recursive_surcharge_reactions_and_dries_cleanly(etype):
    model = column(etype)
    solved = api.run(model)
    rows = incremental_hydrostatic_budget_by_stage(model, solved)
    for row, head in zip(rows[:3], (2.2, 1.6, 1.)):
        assert row["status"] == "passed", row.get("reason")
        np.testing.assert_allclose(row["actual_applied_water_resultant"],
                                   [0., -2*head*GAMMA_W, -2*head*GAMMA_W], atol=1e-7)
        assert row["reaction_resultant"][1] == pytest.approx(400 + 2*head*GAMMA_W, abs=1e-7)
        np.testing.assert_allclose(row["retained_release_resultant"], 0., atol=1e-7)
        np.testing.assert_allclose(row["target_water_resultant"],
                                   [0., -2*GAMMA_W, -2*GAMMA_W], atol=1e-7)
        assert row["water_head_m"] == 1.
    assert rows[3]["status"] == "passed"
    assert rows[3]["water_head_m"] is None
    np.testing.assert_allclose(rows[3]["actual_applied_water_resultant"], 0., atol=1e-7)
    assert rows[3]["reaction_resultant"][1] == pytest.approx(340., abs=1e-7)
    json.dumps(rows, allow_nan=False)


def test_missing_initial_pressure_evidence_is_not_assumed_zero():
    model = column(ElemType.T6)
    solved = api.run(model)
    solved.initial.pore.clear()
    rows = incremental_hydrostatic_budget_by_stage(model, solved)
    assert all(row["status"] == "unsupported" for row in rows)
    assert "pore-pressure blocks" in rows[0]["reason"]


def test_pressure_snapshot_must_match_target_head_not_interpolated_actual_loading():
    model = column(ElemType.T6)
    solved = api.run(model)
    changed = copy.deepcopy(solved)
    changed.stages[0].pore["soil"] += (2.2 - 1.) * GAMMA_W
    rows = incremental_hydrostatic_budget_by_stage(model, changed)
    assert rows[0]["status"] == "failed"
    assert rows[0]["max_pressure_reference_error_kpa"] > 1.


@pytest.fixture(scope="module")
def wet_history():
    pytest.importorskip("shapely")
    root = Path(__file__).resolve().parents[2]
    helper = runpy.run_path(str(root / "examples/f7_excavation_mesh_audit.py"))
    loaded = runpy.run_path(str(root / "scripts/f7_loaded_excavation_audit.py"))["loaded_case"]
    schedule = runpy.run_path(str(root / "scripts/f7_partial_hydrostatic_audit.py"))[
        "wet_partial_schedule"
    ]
    model = schedule(loaded(helper["build_case"](helper["excavation_model"](), 2.5)))
    return model, api.run(model)


def test_actual_wet_excavation_drawdown_and_rewetting_preserve_load_history(wet_history):
    model, solved = wet_history
    rows = incremental_hydrostatic_budget_by_stage(model, solved)
    assert [row["status"] for row in rows] == ["passed"] * 10
    assert rows[1]["max_retained_release_force"] > 1.
    np.testing.assert_allclose(rows[2]["retained_release_resultant"],
                               0.5 * np.array(rows[1]["retained_release_resultant"]), atol=1e-7)
    # No topology changes during drawdown/rewetting: water terms interpolate exactly.
    for index, fraction in ((4, 0.4), (8, 0.5)):
        expected = fraction * np.array(rows[index]["target_water_resultant"]) + (
            1 - fraction
        ) * np.array(rows[index - 1]["actual_applied_water_resultant"])
        np.testing.assert_allclose(rows[index]["actual_applied_water_resultant"],
                                   expected, atol=1e-7)
        assert rows[index]["max_retained_release_force"] < 1e-7
    assert max(row["max_nodal_force_residual"] for row in rows) < 1e-7
    json.dumps(rows, allow_nan=False)


def test_corrupt_previous_wet_stress_breaks_retained_force_evidence(wet_history):
    model, solved = wet_history
    changed = copy.deepcopy(solved)
    block = model.mesh.continuum_blocks()[0]
    kept = np.flatnonzero(solved.stages[1].active[block.tag])[0]
    changed.stages[0].sig[block.tag][kept, :, 0] += 100.
    rows = incremental_hydrostatic_budget_by_stage(model, changed)
    assert rows[1]["status"] == "failed"

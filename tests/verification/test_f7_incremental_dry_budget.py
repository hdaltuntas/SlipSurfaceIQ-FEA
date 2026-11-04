"""Partial-load histories and retained excavation force must be accounted separately."""

from __future__ import annotations

import copy
import runpy
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.mesh import rectangle
from slipsurface.fe2d.post.incremental_dry_budget import incremental_dry_budget_by_stage


@pytest.mark.parametrize("etype", [ElemType.T3, ElemType.T6, ElemType.Q4, ElemType.Q8])
def test_partial_loads_recur_as_fractions_of_remaining_change(etype):
    mesh = rectangle(4., 6., 2, 3, etype=etype, origin=(0., -6.))
    model = api.Model(
        api.Analysis.PLANE_STRAIN, mesh,
        {"soil": api.MaterialSpec.elastic("soil", 25000., 0.3, gamma=18.)}, {1: "soil"},
        fixities=(api.Fixity("bottom", True, True), api.Fixity("left", True, False),
                  api.Fixity("right", True, False)),
        initial=api.InitialStress("gravity"), stages=[
            api.Stage("40 percent", loads=(api.EdgeLoad("top", qn=20.),), load_split=0.4),
            api.Stage("70 percent", loads=(api.EdgeLoad("top", qn=20.),), load_split=0.5),
            api.Stage("full", loads=(api.EdgeLoad("top", qn=20.),)),
        ],
    )
    solved = api.run(model)
    rows = incremental_dry_budget_by_stage(model, solved)
    for row, fraction in zip(rows, (0.4, 0.7, 1.)):
        assert row["status"] == "passed", row.get("reason")
        expected = [0., -432. - 80 * fraction, -864. - 160 * fraction]
        np.testing.assert_allclose(row["actual_applied_resultant"], expected, atol=1e-7)
        np.testing.assert_allclose(row["retained_release_resultant"], 0., atol=1e-7)
        assert row["max_nodal_force_residual"] < 1e-7


def partial_case():
    pytest.importorskip("shapely")
    helpers = runpy.run_path(str(
        Path(__file__).resolve().parents[2] / "examples/f7_excavation_mesh_audit.py"
    ))
    base = helpers["build_case"](helpers["excavation_model"](), 2.5)
    schedule = runpy.run_path(str(
        Path(__file__).resolve().parents[2] / "scripts/f7_partial_excavation_audit.py"
    ))["partial_schedule"]
    return schedule(base)


def test_partial_excavation_has_nonzero_held_forces_and_closes_all_six_stages():
    model = partial_case()
    solved = api.run(model)
    rows = incremental_dry_budget_by_stage(model, solved)
    assert [row["status"] for row in rows] == ["passed"] * 6, [
        row.get("reason") for row in rows
    ]
    for index in (1, 2, 4):
        assert rows[index]["max_retained_release_force"] > 1.
        assert rows[index]["max_nodal_force_residual"] < 1e-7
    np.testing.assert_allclose(rows[2]["retained_release_resultant"],
                               0.5 * np.array(rows[1]["retained_release_resultant"]), atol=1e-7)
    assert rows[5]["max_retained_release_force"] == 0.
    # Changing a committed stress from the previous state must break the held-force reference.
    corrupted = copy.deepcopy(solved)
    block = model.mesh.continuum_blocks()[0]
    kept = np.flatnonzero(solved.stages[1].active[block.tag])[0]
    corrupted.stages[0].sig[block.tag][kept, :, 0] += 100.
    changed = incremental_dry_budget_by_stage(model, corrupted)
    assert changed[1]["status"] == "failed"


def test_new_activation_in_partial_stage_is_explicitly_unsupported():
    model = partial_case()
    model = replace(model, stages=[replace(model.stages[0], load_split=0.4)])
    solved = api.run(model)
    rows = incremental_dry_budget_by_stage(model, solved)
    assert rows[0]["status"] == "unsupported"
    assert "New activation" in rows[0]["reason"]


def test_missing_previous_stage_cannot_be_treated_as_zero_release_history():
    model = partial_case()
    solved = api.run(model)
    solved.stages.pop(0)
    rows = incremental_dry_budget_by_stage(model, solved)
    assert all(row["status"] == "unsupported" for row in rows)
    assert "Stage order" in rows[0]["reason"]

"""Actual excavation, analytical weights/moments and corrupted transfer evidence."""

from __future__ import annotations

import copy
import runpy
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.post.coupled_dry_budget import (
    coupled_dry_budget_by_stage,
    coupled_dry_stage_budget,
)


@pytest.fixture(scope="module")
def excavation():
    pytest.importorskip("shapely")
    helpers = runpy.run_path(str(
        Path(__file__).resolve().parents[2] / "examples/f7_excavation_mesh_audit.py"
    ))
    model = helpers["build_case"](helpers["excavation_model"](), 2.5)
    return model, api.run(model)


def test_actual_three_stages_close_against_analytical_weight_and_first_moment(excavation):
    model, result = excavation
    # Original 30x14 rectangle; remove 15x2 m from its left side on each lift.
    pile_weight = np.pi * 0.8**2 / 4 / 2 * 9 * 24
    for i in range(3):
        row = coupled_dry_stage_budget(model, result, i)
        weight = (420 - 30 * i) * 18 + pile_weight
        np.testing.assert_allclose(row["external_weight_resultant"],
                                   [0., -weight, -4050. * i], atol=1e-7)
        np.testing.assert_allclose(row["reaction_resultant"],
                                   [0., weight, 4050. * i], atol=1e-7)
        assert row["status"] == "passed"
        assert row["max_nodal_force_residual"] < 1e-7
        assert row["max_nodal_moment_residual"] < 1e-7


def test_corrupt_anchor_force_fails_even_though_global_weight_balance_is_unchanged(excavation):
    model, solved = excavation
    result = copy.deepcopy(solved)
    result.last.bars["cad_Anchor1"][0] += 1.
    row = coupled_dry_stage_budget(model, result, 2)
    assert row["status"] == "failed"
    assert row["max_nodal_force_residual"] > 0.5
    assert max(abs(v) for v in row["global_residual"]) < 1e-7


def test_reaction_couple_is_detected_independently_of_net_force(excavation):
    model, solved = excavation
    result = copy.deepcopy(solved)
    x = model.mesh.coords[:, 0]
    left, right = np.argmin(x), np.argmax(x)
    result.last.reactions[left, 1] += 1.
    result.last.reactions[right, 1] -= 1.
    row = coupled_dry_stage_budget(model, result, 2)
    assert np.linalg.norm(row["global_residual"][:2]) < 1e-7
    assert abs(row["global_residual"][2]) == pytest.approx(30., abs=1e-7)
    assert row["status"] == "failed"


def test_anchor_pretension_and_spacing_are_not_double_counted_as_external_loads(excavation):
    model, _ = excavation
    changed = replace(model, bolts={
        tag: replace(spec, pretension=10., spacing_out_of_plane=2.)
        for tag, spec in model.bolts.items()
    })
    solved = api.run(changed)
    row = coupled_dry_stage_budget(changed, solved, 2)
    assert row["status"] == "passed"
    assert row["max_nodal_force_residual"] < 1e-7
    assert any(np.linalg.norm(n["bar"][:2]) > 1. for n in row["structural_nodes"])


@pytest.mark.parametrize("change", [
    "water", "partial", "missing_bar", "nonfinite_bar", "hidden_anchor",
])
def test_unsupported_or_incomplete_evidence_never_passes(excavation, change):
    model, solved = excavation
    result = copy.deepcopy(solved)
    if change == "water":
        model = replace(model, stages=[
            *model.stages[:2], replace(model.stages[2], water=api.WaterCondition.piezo(
                [[-15., -2.], [15., -2.]],
            )),
        ])
    elif change == "partial":
        result.last.lam = 0.5
    elif change == "missing_bar":
        result.last.bars.clear()
    elif change == "hidden_anchor":
        result.last.active["cad_Anchor1"][:] = False
        result.last.bars["cad_Anchor1"][:] = np.nan
    else:
        result.last.bars["cad_Anchor1"][0] = np.nan
    rows = coupled_dry_budget_by_stage(model, result)
    assert rows[2]["status"] == "unsupported"
    assert rows[2]["reason"]

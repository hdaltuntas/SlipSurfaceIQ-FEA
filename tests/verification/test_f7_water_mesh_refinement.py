"""F7 mesh-refinement reaction audits must not fabricate convergence."""

from __future__ import annotations

import math
import runpy
from pathlib import Path

import pytest

from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.post.water_mesh_convergence import water_table_mesh_comparison


def example_study():
    path = Path(__file__).resolve().parents[2] / "examples"
    return runpy.run_path(str(path / "f7_water_table_mesh_refinement.py"))


def row(h, error, *, reference=385.78):
    return {
        "h_m": h,
        "water_table_cut_elements": 2,
        "expected_ry_kn_per_m": reference,
        "reaction_ry_kn_per_m": reference * (1 + error),
        "relative_residual": error,
    }


def test_refinement_records_nonmonotonic_error_without_claiming_convergence():
    report = water_table_mesh_comparison([
        row(2.0, 0.02), row(1.0, 0.04), row(0.5, 0.01),
    ])
    assert report["reference_ry_kn_per_m"] == pytest.approx(385.78)
    assert report["refinement_monotone_nonincreasing"] is False
    assert report["finest_mesh_passed"] is False
    assert report["all_meshes_passed"] is False
    assert [sample["status"] for sample in report["meshes"]] == [
        "failed", "failed", "failed",
    ]
    assert report["meshes"][1]["error_ratio"] == pytest.approx(2.0)
    assert report["meshes"][2]["error_change"] == pytest.approx(-0.03)


def test_acceptance_uses_finest_not_only_coarsest_or_aggregate_result():
    report = water_table_mesh_comparison([
        row(2.0, 0), row(1.0, 0.002), row(0.5, 1e-8),
    ])
    assert report["finest_mesh_passed"] is True
    assert report["all_meshes_passed"] is False
    assert report["meshes"][-1]["status"] == "passed"
    assert report["meshes"][1]["status"] == "failed"


@pytest.mark.parametrize("rows,match", [
    ([row(2.0, 0.01)], "At least two"),
    ([row(1.0, 0.01), row(2.0, 0.01)], "coarse-to-fine"),
    ([row(2.0, 0.01), row(2.0, 0.01)], "coarse-to-fine"),
    ([row(2.0, 0.01), row(1.0, 0.01, reference=390)], "identical"),
    ([row(2.0, 0.01), {**row(1.0, 0.01),
                       "water_table_cut_elements": 0}], "cut elements"),
])
def test_mesh_comparison_rejects_invalid_or_different_references(rows, match):
    with pytest.raises(ValueError, match=match):
        water_table_mesh_comparison(rows)


def test_three_mesh_t3_groundwater_study_has_consistent_closed_form_reference():
    report = example_study()["run_study"](
        (2, 3, 4), head=-2.37, etype=ElemType.T3,
    )
    expected = 2.0 * (2.37 * 17.0 + 7.63 * 20.0)
    assert expected == pytest.approx(385.78)
    assert report["reference_ry_kn_per_m"] == pytest.approx(expected, rel=1e-10)
    assert len(report["meshes"]) == 3
    assert [entry["h_m"] for entry in report["meshes"]] == [
        2.0, 4.0 / 3.0, 1.0,
    ]
    assert all(entry["water_table_cut_elements"] > 0 for entry in report["meshes"])
    assert all(math.isfinite(entry["relative_residual"]) for entry in report["meshes"])
    assert all(entry["status"] in {"passed", "failed"} for entry in report["meshes"])

"""F7: local effective stress refinement must preserve measured T3 error."""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.post.local_stress_refinement import compare_local_stress_meshes


def synthetic(h, stage, err, *, head=0.):
    return {
        "h_m": h,
        "stage": stage,
        "head_m": head,
        "max_abs_pore_error_kpa": 0.,
        "max_abs_effective_stress_error_kpa": err,
        "rms_pore_error_kpa": 0.,
        "rms_effective_stress_error_kpa": err / 2,
        "relative_residual": err / 200.,
    }


def test_nonmonotone_errors_remain_failed_not_accepted():
    values = [
        synthetic(2., "initial", 3.),
        synthetic(2., "lower", 3., head=-4.),
        synthetic(1., "initial", 4.),
        synthetic(1., "lower", 1., head=-4.),
    ]
    result = compare_local_stress_meshes(values)
    assert result["trends"]["initial"]["stress_error_nonincreasing"] is False
    assert result["trends"]["lower"]["stress_error_nonincreasing"] is True
    assert result["all_rows_passed"] is False
    assert all(r["status"] == "failed" for r in result["rows"])


def test_changed_reference_or_missing_stage_rejected():
    values = [
        synthetic(2., "initial", 1.),
        synthetic(2., "lower", 1., head=-4.),
        synthetic(1., "initial", 1., head=-2.),
        synthetic(1., "lower", 1., head=-4.),
    ]
    with pytest.raises(ValueError, match="identical"):
        compare_local_stress_meshes(values)
    values[2]["head_m"] = 0.
    values[3]["stage"] = "initial"
    with pytest.raises(ValueError, match="every mesh"):
        compare_local_stress_meshes(values)


def test_actual_t3_two_mesh_local_stress_errors_decrease():
    script = Path(__file__).resolve().parents[2] / "examples"
    example = runpy.run_path(str(script / "f7_local_stress_refinement.py"))
    report = example["run_study"]((2, 4), etype=ElemType.T3)
    assert len(report["rows"]) == 4
    assert report["mesh_sizes_m"] == [2., 1.]
    assert report["trends"]["initial"]["stress_error_nonincreasing"]
    assert report["trends"]["initial"]["coarsest_stress_error_kpa"] > (
        report["trends"]["initial"]["finest_stress_error_kpa"]
    )
    assert report["trends"]["initial"]["finest_status"] == "failed"
    assert all(r["max_abs_pore_error_kpa"] < 1e-7 for r in report["rows"])

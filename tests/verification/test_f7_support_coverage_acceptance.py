"""F7 global report must not pass with missing support outputs."""

from __future__ import annotations

from copy import deepcopy

from slipsurface.fe2d.post.support_coverage_acceptance import support_coverage_acceptance

SIZES = (2.5, 1.8, 1.2)
STAGES = ("pile", "lift1", "lift2")


def row(h, stage):
    return {
        "h_m": h,
        "stage": stage,
        "support_result_coverage": {
            "status": "passed",
            "declared_structures": 3,
            "checked_structures": 3,
            "failed_structures": 0,
            "details": [
                {"tag": "pile", "status": "passed",
                 "active_elements": 2, "total_elements": 2},
                {"tag": "anchor", "status": "passed",
                 "active_elements": 0, "total_elements": 1},
                {"tag": "skin", "status": "passed",
                 "active_elements": 2, "total_elements": 2},
            ],
        },
    }


def rows():
    return [row(h, stage) for h in SIZES for stage in STAGES]


def test_complete_structural_coverage_passes_all_nine_mesh_stage_rows():
    report = support_coverage_acceptance(rows(), SIZES, STAGES)
    assert report["status"] == "passed"
    assert report["expected_stage_mesh_rows"] == 9
    assert report["passed"] == 9
    assert report["failed"] == report["missing"] == 0


def test_missing_mesh_stage_or_structural_report_fails_closed():
    partial = rows()[:-1]
    report = support_coverage_acceptance(partial, SIZES, STAGES)
    assert report["status"] == "failed"
    assert report["missing"] == 1
    partial = rows()
    partial[0].pop("support_result_coverage")
    report = support_coverage_acceptance(partial, SIZES, STAGES)
    assert report["status"] == "failed"
    assert report["missing"] == 1


def test_active_support_output_failure_blocks_cli_acceptance():
    partial = rows()
    coverage = partial[0]["support_result_coverage"]
    coverage["status"] = "failed"
    coverage["failed_structures"] = 1
    coverage["details"][0]["status"] = "failed"
    report = support_coverage_acceptance(partial, SIZES, STAGES)
    assert report["status"] == "failed"
    assert report["failed"] == 1
    assert report["passed"] == 8


def test_disguised_missing_or_duplicate_support_report_is_detected():
    partial = rows()
    coverage = partial[0]["support_result_coverage"]
    coverage["details"][0]["tag"] = "anchor"
    report = support_coverage_acceptance(partial, SIZES, STAGES)
    assert report["status"] == "failed"
    assert report["failed"] == 1

    partial = rows()
    coverage = partial[0]["support_result_coverage"]
    coverage["checked_structures"] = 2
    report = support_coverage_acceptance(partial, SIZES, STAGES)
    assert report["status"] == "failed"


def test_extra_unknown_stage_row_fails_acceptance():
    partial = rows()
    partial.append(deepcopy(row(1.2, "unknown")))
    report = support_coverage_acceptance(partial, SIZES, STAGES)
    assert report["status"] == "failed"
    assert len(report["unexpected"]) == 1


def test_duplicate_mesh_stage_row_fails_acceptance():
    partial = rows()
    partial.append(deepcopy(partial[0]))
    report = support_coverage_acceptance(partial, SIZES, STAGES)
    assert report["status"] == "failed"
    assert report["missing"] == 1

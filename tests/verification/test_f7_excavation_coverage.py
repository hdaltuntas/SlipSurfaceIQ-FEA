"""F7 fail-closed coverage checks for optional staged pile/anchor excavation."""

from __future__ import annotations

from slipsurface.fe2d.post.excavation_coverage import excavation_audit_coverage

SIZES = (2.5, 1.8, 1.2)
STAGES = ("pile", "lift1", "lift2")


def row(h, stage, *, status="passed"):
    return {
        "h_m": h,
        "stage": stage,
        "gravity_balance": {"status": status},
        "dry_load_balance": {"status": status},
        "excavation_balance": {"status": status},
    }


def full_rows():
    return [row(h, stage) for h in SIZES for stage in STAGES]


def test_all_mesh_stages_and_force_checks_are_explicitly_accounted_for():
    result = excavation_audit_coverage(full_rows(), [], SIZES, STAGES)
    assert result["complete"]
    assert result["status"] == "complete"
    assert result["expected_rows"] == result["observed_rows"] == 9
    assert result["balance_checks"]["passed"] == 27
    assert result["all_force_checks_passed"]


def test_missing_stage_or_failed_mesh_cannot_report_complete():
    entries = full_rows()
    entries.pop()
    result = excavation_audit_coverage(
        entries, [{"h_m": 1.2, "type": "SolverError"}], SIZES, STAGES,
    )
    assert not result["complete"]
    assert not result["all_force_checks_passed"]
    assert result["missing"] == [{"h_m": 1.2, "stage": "lift2"}]
    assert result["failed_solves"]


def test_duplicated_and_out_of_order_stage_rows_are_rejected():
    entries = full_rows()
    entries.insert(1, row(2.5, "pile"))
    result = excavation_audit_coverage(entries, [], SIZES, STAGES)
    assert not result["complete"]
    assert result["duplicates"][0]["stage"] == "pile"
    reordered = full_rows()
    reordered[0], reordered[1] = reordered[1], reordered[0]
    result = excavation_audit_coverage(reordered, [], SIZES, STAGES)
    assert not result["complete"]
    assert result["reordered_meshes"] == [2.5]


def test_unsupported_balance_is_not_counted_as_independent_validation():
    entries = full_rows()
    entries[0]["gravity_balance"] = {"status": "unsupported"}
    report = excavation_audit_coverage(entries, [], SIZES, STAGES)
    assert report["complete"]
    assert report["balance_checks"]["unsupported"] == 1
    assert not report["all_force_checks_passed"]


def test_missing_balance_status_is_a_failure_not_a_pass():
    entries = full_rows()
    entries[2].pop("dry_load_balance")
    report = excavation_audit_coverage(entries, [], SIZES, STAGES)
    assert report["complete"]
    assert report["balance_checks"]["failed"] == 1
    assert report["balance_checks"]["details"][0]["status"] == "missing"
    assert not report["all_force_checks_passed"]

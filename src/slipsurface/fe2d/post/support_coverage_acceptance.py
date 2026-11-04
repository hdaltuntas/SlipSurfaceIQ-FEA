"""F7 fail-closed aggregation for staged structural-result coverage.

Every requested mesh and excavation stage must contain a complete,
passed structural activation/output report. This is a data integrity
acceptance gate only; it cannot validate physical N/V/M magnitudes.
"""

from __future__ import annotations


def support_coverage_acceptance(rows, sizes, stages):
    """Aggregate stage-wise pile, anchor and interface coverage without skips."""
    sizes = tuple(float(h) for h in sizes)
    stages = tuple(stages)
    if len(sizes) < 1 or len(set(sizes)) != len(sizes):
        raise ValueError("Mesh sizes must be unique and nonempty")
    if len(stages) < 1 or len(set(stages)) != len(stages):
        raise ValueError("Stage names must be unique and nonempty")
    results = []
    for h in sizes:
        for stage in stages:
            matched = [
                row for row in rows
                if row.get("h_m") == h and row.get("stage") == stage
            ]
            if len(matched) != 1:
                results.append({
                    "h_m": h, "stage": stage, "status": "missing",
                    "reason": f"Expected exactly one row; found {len(matched)}",
                })
                continue
            coverage = matched[0].get("support_result_coverage")
            if not isinstance(coverage, dict):
                results.append({
                    "h_m": h, "stage": stage, "status": "missing",
                    "reason": "Structural coverage report missing",
                })
                continue
            details = coverage.get("details")
            declared = coverage.get("declared_structures")
            checked = coverage.get("checked_structures")
            failed = coverage.get("failed_structures")
            if (
                not isinstance(details, list)
                or not isinstance(declared, int) or declared <= 0
                or not isinstance(checked, int) or checked != declared
                or len(details) != checked
                or not isinstance(failed, int)
                or failed != sum(item.get("status") != "passed"
                                 for item in details if isinstance(item, dict))
                or any(not isinstance(item, dict) for item in details)
                or coverage.get("status") != "passed"
                or failed != 0
            ):
                results.append({
                    "h_m": h, "stage": stage, "status": "failed",
                    "reason": "Structural report incomplete or contains failures",
                })
                continue
            tags = [item.get("tag") for item in details]
            if (
                any(not isinstance(tag, str) or not tag for tag in tags)
                or len(set(tags)) != len(tags)
                or any(
                    item.get("active_elements", -1) < 0
                    or item.get("total_elements", 0) <= 0
                    or item["active_elements"] > item["total_elements"]
                    for item in details
                )
            ):
                results.append({
                    "h_m": h, "stage": stage, "status": "failed",
                    "reason": "Invalid support identities or activity counts",
                })
                continue
            results.append({
                "h_m": h, "stage": stage, "status": "passed",
                "support_count": checked,
            })
    expected = len(sizes) * len(stages)
    passed = sum(item["status"] == "passed" for item in results)
    failed = sum(item["status"] == "failed" for item in results)
    missing = sum(item["status"] == "missing" for item in results)
    extra = [
        {"h_m": row.get("h_m"), "stage": row.get("stage")}
        for row in rows
        if row.get("h_m") not in sizes or row.get("stage") not in stages
    ]
    return {
        "status": (
            "passed" if passed == expected and not extra else "failed"
        ),
        "expected_stage_mesh_rows": expected,
        "passed": passed,
        "failed": failed,
        "missing": missing,
        "unexpected": extra,
        "rows": results,
        "warning": (
            "Support activation and finite-output integrity is not independent "
            "physical validation of pile, anchor or interface forces."
        ),
    }

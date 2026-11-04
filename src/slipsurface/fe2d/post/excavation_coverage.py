"""F7 fail-closed completeness gate for staged supported-excavation mesh audits.

A report containing fewer stages or meshes than requested must never be
mistaken for a successful sensitivity study. This gate checks coverage
and interprets existing balance classifications, without claiming that
a numerical convergence check is an independent physical benchmark.
"""

from __future__ import annotations

import math


def excavation_audit_coverage(rows, failures, sizes, expected_stages):
    """Check requested (mesh, stage) coverage and expose force-balance gaps.

    The mesh-size and stage names must be unique. For each requested mesh
    there must be one row for *every* expected stage, in stage order.
    This is a report-integrity gate, not an independent solver benchmark.
    """
    sizes = tuple(float(h) for h in sizes)
    expected_stages = tuple(str(name) for name in expected_stages)
    if (
        len(sizes) < 3 or len(set(sizes)) != len(sizes)
        or any(not math.isfinite(h) or h <= 0 for h in sizes)
    ):
        raise ValueError("At least three distinct positive finite mesh sizes required")
    if len(expected_stages) < 1 or len(set(expected_stages)) != len(expected_stages):
        raise ValueError("Expected stage names must be nonempty and unique")

    duplicates, missing, unexpected, reordered = [], [], [], []
    accepted, failed, unsupported = 0, 0, 0
    balance_names = (
        "gravity_balance", "dry_load_balance", "excavation_balance"
    )
    status_details = []
    for h in sizes:
        selected = [row for row in rows if row.get("h_m") == h]
        names = [row.get("stage") for row in selected]
        for name in expected_stages:
            count = names.count(name)
            if count == 0:
                missing.append({"h_m": h, "stage": name})
            if count > 1:
                duplicates.append({"h_m": h, "stage": name, "count": count})
        for name in names:
            if name not in expected_stages:
                unexpected.append({"h_m": h, "stage": name})
        if names != [name for name in expected_stages if name in names]:
            reordered.append(h)
        for row in selected:
            for kind in balance_names:
                balance = row.get(kind)
                status = balance.get("status") if isinstance(balance, dict) else None
                if status == "passed":
                    accepted += 1
                elif status == "failed":
                    failed += 1
                    status_details.append({
                        "h_m": h, "stage": row.get("stage"),
                        "check": kind, "status": status,
                    })
                elif status == "unsupported":
                    unsupported += 1
                    status_details.append({
                        "h_m": h, "stage": row.get("stage"),
                        "check": kind, "status": status,
                    })
                else:
                    failed += 1
                    status_details.append({
                        "h_m": h, "stage": row.get("stage"),
                        "check": kind, "status": "missing",
                    })

    for row in rows:
        if row.get("h_m") not in sizes:
            unexpected.append({
                "h_m": row.get("h_m"), "stage": row.get("stage"),
            })
    complete = not (
        failures or missing or duplicates or unexpected or reordered
    )
    return {
        "status": "complete" if complete else "incomplete",
        "complete": complete,
        "requested_meshes": list(sizes),
        "expected_stages": list(expected_stages),
        "expected_rows": len(sizes) * len(expected_stages),
        "observed_rows": len(rows),
        "missing": missing,
        "duplicates": duplicates,
        "unexpected": unexpected,
        "reordered_meshes": reordered,
        "failed_solves": list(failures),
        "balance_checks": {
            "passed": accepted, "failed": failed,
            "unsupported": unsupported,
            "details": status_details,
        },
        "all_force_checks_passed": (
            complete and failed == 0 and unsupported == 0 and accepted > 0
        ),
        "warning": (
            "Completeness and supported force checks are diagnostics; "
            "they do not establish physical validation of soil–pile–anchor response."
        ),
    }

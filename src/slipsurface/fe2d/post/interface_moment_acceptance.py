"""F7 fail-closed stage interface moment acceptance for supported excavation.

The numerical interface first-moment diagnostic is meaningful for active
interfaces only. An inactive interface is correctly `unsupported`; an
expected-active interface that is unsupported, missing, or failed must
never be counted as accepted. This is an assembly-integrity gate, not an
independent physical soil-structure validation.
"""

from __future__ import annotations

import math


def interface_moment_acceptance(rows, sizes, stages, interface_tags):
    """Require every expected-active interface to pass at every mesh/stage.

    `stages` is an ordered sequence of native Stage objects, allowing
    expected activation to be derived independently from the result rows.
    `interface_tags` lists declared interface block names. Inactive
    interfaces may be reported `unsupported`, but may not pass as active.
    """
    meshes = tuple(float(h) for h in sizes)
    steps = tuple(stages)
    declared = frozenset(interface_tags)
    if (
        not meshes or len(set(meshes)) != len(meshes)
        or any(not math.isfinite(h) or h <= 0 for h in meshes)
    ):
        raise ValueError("Mesh resolutions must be positive, finite and distinct")
    names = tuple(stage.name for stage in steps)
    if not names or len(set(names)) != len(names):
        raise ValueError("Stage names must be nonempty and distinct")
    if not declared or any(not isinstance(tag, str) or not tag for tag in declared):
        raise ValueError("At least one declared interface tag is required")
    findings = []
    for h in meshes:
        for step in steps:
            matching = [
                row for row in rows
                if row.get("h_m") == h and row.get("stage") == step.name
            ]
            if len(matching) != 1:
                findings.append({
                    "h_m": h, "stage": step.name, "interface": None,
                    "status": "missing", "reason": "Expected exactly one mesh-stage row",
                })
                continue
            report = matching[0].get("interface_moment_transfer")
            if not isinstance(report, dict):
                findings.append({
                    "h_m": h, "stage": step.name, "interface": None,
                    "status": "missing", "reason": "Interface moment report missing",
                })
                continue
            unexpected_tags = set(report) - declared
            for tag in sorted(unexpected_tags):
                findings.append({
                    "h_m": h, "stage": step.name, "interface": tag,
                    "status": "failed", "reason": "Undeclared interface result",
                })
            for tag in sorted(declared):
                value = report.get(tag)
                expected = tag in step.active_structures
                status = value.get("status") if isinstance(value, dict) else None
                active = value.get("active_elements") if isinstance(value, dict) else None
                if not isinstance(active, int) or active < 0:
                    outcome, reason = "missing", "Missing valid interface activity count"
                elif expected and status == "passed" and active > 0:
                    residual = value.get("relative_residual")
                    tolerance = value.get("acceptance_tolerance")
                    if (
                        isinstance(residual, (int, float))
                        and isinstance(tolerance, (int, float))
                        and math.isfinite(residual) and math.isfinite(tolerance)
                        and 0 <= residual <= tolerance and tolerance > 0
                    ):
                        outcome, reason = "passed", None
                    else:
                        outcome, reason = "failed", "Missing or invalid moment residual"
                elif not expected and status == "unsupported" and active == 0:
                    outcome, reason = "not_applicable", None
                else:
                    outcome, reason = "failed", (
                        "Interface moment status or activation disagrees with stage"
                    )
                finding = {
                    "h_m": h, "stage": step.name, "interface": tag,
                    "expected_active": expected, "status": outcome,
                }
                if reason:
                    finding["reason"] = reason
                findings.append(finding)
    extra_rows = [
        {"h_m": row.get("h_m"), "stage": row.get("stage")}
        for row in rows
        if row.get("h_m") not in meshes or row.get("stage") not in names
    ]
    passed = sum(row["status"] == "passed" for row in findings)
    excluded = sum(row["status"] == "not_applicable" for row in findings)
    failed = sum(row["status"] == "failed" for row in findings)
    missing = sum(row["status"] == "missing" for row in findings)
    expected_active_checks = len(meshes) * sum(
        len(stage.active_structures & declared) for stage in steps
    )
    complete = (
        passed == expected_active_checks and failed == 0 and missing == 0
        and not extra_rows
    )
    return {
        "status": "passed" if complete else "failed",
        "expected_active_checks": expected_active_checks,
        "passed": passed,
        "failed": failed,
        "missing": missing,
        "not_applicable": excluded,
        "unexpected_rows": extra_rows,
        "checks": findings,
        "warning": (
            "Passing interface moment assembly does not independently verify "
            "soil, pile, anchor or hydrostatic equilibrium."
        ),
    }

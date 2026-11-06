"""Fail-closed F7 acceptance for interface transfer ledger and stage activation.

Checks a bounded internal action/reaction integrity property, not external
soil-structure force equilibrium or independent physical validation.
"""

from __future__ import annotations

import math


def interface_ledger_acceptance(ledger, sizes, stages, interface_tags):
    """Require transfer checks for active interfaces, N/A only when none expected."""
    sizes = tuple(float(h) for h in sizes)
    steps = tuple(stages)
    names = tuple(step.name for step in steps)
    tags = frozenset(interface_tags)
    if (not sizes or len(set(sizes)) != len(sizes)
            or any(not math.isfinite(h) or h <= 0 for h in sizes)):
        raise ValueError("Invalid mesh resolutions")
    if not names or len(set(names)) != len(names):
        raise ValueError("Invalid stage names")
    if not tags or any(not isinstance(tag, str) or not tag for tag in tags):
        raise ValueError("Invalid interface tag set")
    checks = ledger.get("checks") if isinstance(ledger, dict) else None
    if not isinstance(checks, list):
        checks = []
    findings = []
    for h in sizes:
        for step in steps:
            matched = [item for item in checks
                       if isinstance(item, dict)
                       and item.get("h_m") == h
                       and item.get("stage") == step.name]
            expected = bool(step.active_structures & tags)
            if len(matched) != 1:
                findings.append({
                    "h_m": h, "stage": step.name, "status": "failed",
                    "reason": "Missing or duplicated transfer ledger row",
                })
                continue
            item = matched[0]
            active_count = item.get("active_interface_elements")
            if expected:
                ratio = item.get("relative_transfer_residual")
                tol = ledger.get("tolerance")
                valid = (
                    item.get("status") == "passed"
                    and isinstance(active_count, int)
                    and not isinstance(active_count, bool)
                    and active_count > 0
                    and isinstance(ratio, (int, float))
                    and not isinstance(ratio, bool)
                    and isinstance(tol, (int, float))
                    and not isinstance(tol, bool)
                    and math.isfinite(ratio)
                    and math.isfinite(tol)
                    and tol > 0 and 0 <= ratio <= tol
                )
            else:
                valid = item.get("status") == "not_applicable"
            findings.append({
                "h_m": h, "stage": step.name,
                "expected_active": expected,
                "status": "passed" if valid else "failed",
                **({"reason": "Transfer status inconsistent with stage activation"}
                   if not valid else {}),
            })
    extras = [item for item in checks
              if not isinstance(item, dict)
              or item.get("h_m") not in sizes or item.get("stage") not in names]
    success = (
        all(item["status"] == "passed" for item in findings)
        and not extras
        and ledger.get("status") == "passed"
    )
    return {
        "status": "passed" if success else "failed",
        "checked_mesh_stages": len(findings),
        "failed_mesh_stages": sum(item["status"] == "failed" for item in findings),
        "unexpected_checks": len(extras),
        "checks": findings,
        "warning": (
            "Internal interface transfer integrity only; global external "
            "force equilibrium and physical validation remain unverified."
        ),
    }

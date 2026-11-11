"""Presentation envelope for the existing read-only elastic contact audit.

This module never solves a model or changes a numerical tolerance. A passed
transition is deliberately NOT promoted to a physical-only equilibrium pass.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .contact_resultants import moment_origin
from .contact_topology_equilibrium import contact_topology_equilibrium_by_stage

SCHEMA = "slipsurface.contact_topology_audit/1"
_STATUSES = {"passed", "failed", "invalid", "unsupported", "blocked"}


@dataclass(frozen=True)
class AuditRow:
    snapshot_index: int
    name: str
    fraction: float | None
    transition: str
    physical: str
    nodal_residual: float | None = None
    global_residual: tuple | None = None
    retained_max: float | None = None
    reason: str = ""


def validate_document(document):
    """Reject malformed/nonfinite presentation data before display or replacement.

    Return a detached JSON-only copy so exporters cannot alter a dialog's data.
    Failed/unsupported audit outcomes are valid reports and remain exportable.
    """
    data = json.loads(json.dumps(document, allow_nan=False))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise ValueError("Unknown contact audit document schema")
    moment_origin(data.get("origin_m"))
    names = data.get("snapshot_names")
    audit = data.get("audit")
    if not isinstance(names, list) or not names or any(not isinstance(n, str) for n in names):
        raise ValueError("Invalid audit snapshot identities")
    if not isinstance(audit, dict) or audit.get("status") not in ("passed", "failed"):
        raise ValueError("Missing aggregate audit status")
    if audit.get("initial_status") not in {"passed", "invalid", "unsupported"}:
        raise ValueError("Invalid initial audit status")
    stages = audit.get("stages")
    if (not isinstance(stages, list) or len(stages) != len(names) - 1
            or type(audit.get("stage_count")) is not int or audit["stage_count"] != len(stages)):
        raise ValueError("Incomplete audit stage history")
    for i, row in enumerate(stages):
        if (not isinstance(row, dict) or type(row.get("stage_index")) is not int
                or row["stage_index"] != i or row.get("stage") != names[i + 1]
                or row.get("status") not in _STATUSES):
            raise ValueError("Invalid audit stage identity/status")
        if row["status"] in ("passed", "failed"):
            for key in ("transition_equilibrium", "physical_equilibrium"):
                balance = row.get(key)
                if (not isinstance(balance, dict)
                        or balance.get("status") not in ("passed", "failed")):
                    raise ValueError("Missing measured equilibrium evidence")
            if row["status"] == "passed" and row["transition_equilibrium"]["status"] != "passed":
                raise ValueError("Contradictory transition status")
    success = audit["initial_status"] == "passed" and all(r["status"] == "passed" for r in stages)
    if (audit["status"] == "passed") != success:
        raise ValueError("Contradictory aggregate audit status")
    return data


def prepare_contact_audit(result, *, origin=(0.0, 0.0)):
    """Audit the COMPLETE supplied snapshot history, including its initial record."""
    if result is None or result.initial is None:
        raise ValueError("Stored accepted results, including the initial snapshot, are required")
    origin = moment_origin(origin)
    audit = contact_topology_equilibrium_by_stage(result, origin=origin)
    return validate_document({
        "schema": SCHEMA,
        "origin_m": list(origin),
        "snapshot_names": [result.initial.name, *(s.name for s in result.stages)],
        "units": {"force": "kN/m", "moment": "kN*m/m", "gap": "m", "traction": "kPa"},
        "audit": audit,
    })


def audit_rows(document):
    """Snapshot index zero is initial; audit stage index zero is the FIRST stage."""
    data = validate_document(document)
    audit = data["audit"]
    rows = [AuditRow(0, data["snapshot_names"][0], None, audit["initial_status"],
                     "not assessed", reason=audit.get("reason", "Initial reference check only"))]
    for item in audit["stages"]:
        balance = item.get("transition_equilibrium", {})
        nodal = balance.get("checks", {}).get("nodal_force", {})
        retained = item.get("history", {}).get("retained_release_nodal")
        physical = (item["physical_equilibrium"]["status"]
                    if item["status"] == "passed" else "not assessed")
        reason = item.get("reason", "")
        if "blocked_by_stage_index" in item:
            reason = f"Blocked by snapshot {item['blocked_by_stage_index'] + 1}"
        rows.append(AuditRow(
            item["stage_index"] + 1, item["stage"], item.get("accepted_fraction"),
            item["status"], physical, nodal.get("maximum_absolute_residual"),
            tuple(balance["global_residual"]) if "global_residual" in balance else None,
            max((abs(v) for pair in retained for v in pair), default=0.0)
            if retained is not None else None,
            reason,
        ))
    return tuple(rows)


def audit_summary(document):
    rows = audit_rows(document)[1:]
    return {
        "stage_count": len(rows),
        "transition_passed": sum(r.transition == "passed" for r in rows),
        "physical_passed": sum(r.physical == "passed" for r in rows),
        "physical_not_balanced": sum(r.physical == "failed" for r in rows),
        "physical_not_assessed": sum(r.physical == "not assessed" for r in rows),
    }

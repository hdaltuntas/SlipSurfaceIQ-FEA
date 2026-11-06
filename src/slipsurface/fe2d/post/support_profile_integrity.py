"""F7 mesh/stage structural profile completeness diagnostics.

Validate profiles sampled on CAD support length coordinates. This check is
data integrity only; matching N/V/M magnitudes is not physical validation.
"""

from __future__ import annotations

import math


def _valid_profile(profile, kind, stations):
    if not isinstance(profile, dict):
        return False, "Missing profile dictionary"
    if profile.get("kind") != kind or profile.get("mode") != "magnitude":
        return False, "Unexpected profile type or mode"
    axis = profile.get("s")
    values = profile.get("components")
    if not isinstance(axis, list) or not isinstance(values, list):
        return False, "Profile stations or components missing"
    if len(axis) < 2 or len(axis) != len(values):
        return False, "Invalid profile station count"
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool)
               and math.isfinite(x) for x in axis):
        return False, "Nonfinite profile station"
    if abs(axis[0]) > 1e-10 or abs(axis[-1] - 1.0) > 1e-10:
        return False, "Profile must cover normalized CAD length 0..1"
    if any(right <= left for left, right in zip(axis, axis[1:])):
        return False, "Profile stations must increase"
    if stations is not None and axis != stations:
        return False, "Profile station axes differ between meshes"
    columns = 3 if kind == "beam" else 1
    for section in values:
        if (not isinstance(section, list) or len(section) != columns
                or any(not isinstance(x, (int, float)) or isinstance(x, bool)
                       or not math.isfinite(x) or x < 0 for x in section)):
            return False, "Invalid or nonfinite N/V/M or bar axial component"
    return True, None


def support_profile_integrity(rows, sizes, stages, beams, bars):
    """Check all declared support tags at each requested mesh and stage.

    A support declared active in the stage must have a sampled profile; one
    not yet installed must have no sampled profile. Duplicates or extra
    output tags are not silently ignored.
    """
    meshes = tuple(float(h) for h in sizes)
    steps = tuple(stages)
    tags = {**{tag: "beam" for tag in beams},
            **{tag: "bar" for tag in bars}}
    if (not meshes or len(meshes) != len(set(meshes))
            or any(not math.isfinite(h) or h <= 0 for h in meshes)):
        raise ValueError("Mesh sizes must be distinct, finite and positive")
    names = [step.name for step in steps]
    if not names or len(set(names)) != len(names) or not tags:
        raise ValueError("Stages and structural tags must be nonempty and unique")
    if len(tags) != len(set(beams)) + len(set(bars)):
        raise ValueError("Duplicate beam/bar support identity")
    axes = {}
    findings = []
    for h in meshes:
        for step in steps:
            matched = [row for row in rows
                       if row.get("h_m") == h and row.get("stage") == step.name]
            if len(matched) != 1:
                findings.append({"h_m": h, "stage": step.name, "tag": None,
                                 "status": "failed",
                                 "reason": "Missing or duplicate mesh-stage results"})
                continue
            profiles = matched[0].get("profiles")
            if not isinstance(profiles, dict):
                findings.append({"h_m": h, "stage": step.name, "tag": None,
                                 "status": "failed", "reason": "Missing profile map"})
                continue
            for extra in sorted(set(profiles) - set(tags)):
                findings.append({"h_m": h, "stage": step.name, "tag": extra,
                                 "status": "failed", "reason": "Undeclared support"})
            for tag, kind in sorted(tags.items()):
                expected = tag in step.active_structures
                profile = profiles.get(tag)
                if not expected:
                    status = "failed" if tag in profiles else "not_applicable"
                    reason = "Inactive support has an output profile" if tag in profiles else None
                elif tag not in profiles:
                    status, reason = "failed", "Active support profile missing"
                elif not isinstance(profile, dict) or profile.get("tag") != tag:
                    status, reason = "failed", "Profile identity mismatch"
                else:
                    valid, reason = _valid_profile(profile, kind, axes.get((step.name, tag)))
                    status = "passed" if valid else "failed"
                    if valid:
                        axes.setdefault((step.name, tag), profile["s"])
                findings.append({
                    "h_m": h, "stage": step.name, "tag": tag,
                    "kind": kind, "expected_active": expected, "status": status,
                    **({"reason": reason} if reason else {}),
                })
    extra_rows = [
        {"h_m": row.get("h_m"), "stage": row.get("stage")}
        for row in rows
        if row.get("h_m") not in meshes or row.get("stage") not in names
    ]
    passed = sum(x["status"] == "passed" for x in findings)
    failed = sum(x["status"] == "failed" for x in findings)
    return {
        "status": "diagnostic_complete" if not failed and not extra_rows else "incomplete",
        "passed_profiles": passed,
        "failed_profiles": failed,
        "unexpected_rows": extra_rows,
        "checks": findings,
        "warning": (
            "CAD-aligned profile completeness is not N/V/M physical "
            "validation, numerical convergence certification, or a design check."
        ),
    }

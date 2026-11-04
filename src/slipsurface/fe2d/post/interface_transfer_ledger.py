"""Global interface action-reaction transfer ledger for the F7 excavation.

Sums reported per-interface nodal force contributions across the model.
The check verifies internal cancellation and independently computed face
resultants; it does NOT establish continuum/beam/bar external equilibrium.
"""

from __future__ import annotations

import math


def _finite(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def interface_transfer_ledger(rows, sizes, stages, interface_tags, *, tolerance=1e-9):
    """Fail closed on missing/extra interface tags and nonfinite force data."""
    if not _finite(tolerance) or tolerance <= 0:
        raise ValueError("Tolerance must be positive and finite")
    sizes = tuple(float(x) for x in sizes)
    stages = tuple(stages)
    tags = tuple(interface_tags)
    if (not sizes or len(set(sizes)) != len(sizes)
            or any(not math.isfinite(h) or h <= 0 for h in sizes)):
        raise ValueError("Mesh sizes must be unique, finite and positive")
    if not stages or len(set(stages)) != len(stages):
        raise ValueError("Stage names must be unique and nonempty")
    if not tags or len(set(tags)) != len(tags):
        raise ValueError("Interface tags must be unique and nonempty")

    items = []
    for h in sizes:
        for name in stages:
            matched = [row for row in rows
                       if row.get("h_m") == h and row.get("stage") == name]
            if len(matched) != 1:
                items.append({"h_m": h, "stage": name, "status": "missing",
                              "reason": "Expected exactly one stage-mesh record"})
                continue
            results = matched[0].get("interface_nodal_transfer")
            if not isinstance(results, dict) or set(results) != set(tags):
                items.append({"h_m": h, "stage": name, "status": "missing",
                              "reason": "Missing or unexpected interface tags"})
                continue
            net = [0.0, 0.0]
            face = [0.0, 0.0]
            scale = 1.0
            max_reference_error = 0.0
            count_active = 0
            valid = True
            for tag in tags:
                item = results[tag]
                if not isinstance(item, dict):
                    valid = False
                    break
                n = item.get("active_elements")
                if not isinstance(n, int) or isinstance(n, bool) or n < 0:
                    valid = False
                    break
                keys = (
                    "face1_fx", "face1_fy", "face2_fx", "face2_fy",
                    "global_residual_fx", "global_residual_fy",
                    "reference_error_fx", "reference_error_fy",
                )
                if any(not _finite(item.get(key)) for key in keys):
                    valid = False
                    break
                count_active += n
                for axis, suffix in enumerate(("fx", "fy")):
                    f1 = float(item[f"face1_{suffix}"])
                    f2 = float(item[f"face2_{suffix}"])
                    net[axis] += float(item[f"global_residual_{suffix}"])
                    face[axis] += f1 + f2
                    scale = max(scale, abs(f1), abs(f2))
                    max_reference_error = max(
                        max_reference_error, abs(item[f"reference_error_{suffix}"])
                    )
            if not valid or count_active == 0:
                items.append({
                    "h_m": h, "stage": name,
                    "status": "failed" if not valid else "not_applicable",
                    "reason": "Invalid interface forces" if not valid
                              else "No active interface elements",
                })
                continue
            residual = max(abs(net[0]), abs(net[1]), abs(face[0]), abs(face[1]),
                           max_reference_error)
            ratio = residual / scale
            items.append({
                "h_m": h, "stage": name, "status": "passed" if ratio <= tolerance
                else "failed",
                "active_interface_elements": count_active,
                "global_internal_fx": net[0],
                "global_internal_fy": net[1],
                "paired_face_fx": face[0],
                "paired_face_fy": face[1],
                "max_reference_error": max_reference_error,
                "relative_transfer_residual": ratio,
            })
    known = set(sizes), set(stages)
    extra = [{"h_m": row.get("h_m"), "stage": row.get("stage")}
             for row in rows
             if row.get("h_m") not in known[0] or row.get("stage") not in known[1]]
    success = all(item["status"] in ("passed", "not_applicable") for item in items)
    return {
        "status": "passed" if success and not extra
                  and any(item["status"] == "passed" for item in items)
                  else "failed",
        "tolerance": tolerance,
        "checks": items,
        "unexpected_rows": extra,
        "warning": (
            "Interface action/reaction cancellation is an internal transfer "
            "integrity check; it does not validate total soil-structure "
            "equilibrium, water, pretension, or external force budgets."
        ),
    }

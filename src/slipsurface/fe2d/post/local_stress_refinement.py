"""Mesh-refinement audit of independent local pore and effective-stress errors.

An acceptable *global* force resultant is not enough to certify local
Gauss-point fields. Report maximum and RMS discrepancies stage by stage,
without silently upgrading a T3 discretization error to a pass.
"""

from __future__ import annotations

import math

from slipsurface.fe2d.post.balance_acceptance import classify_balance


def compare_local_stress_meshes(rows, *, tolerance=1e-6):
    """Classify matched stage results on strictly decreasing mesh sizes.

    Each row is a flat mapping with h_m, stage, head_m,
    max_abs_pore_error_kpa, max_abs_effective_stress_error_kpa,
    rms_pore_error_kpa, rms_effective_stress_error_kpa, and
    relative_residual. Each mesh must report the same stages and head.
    """
    if len(rows) < 4:
        raise ValueError("At least two meshes and two stages are required")
    stages = list(dict.fromkeys(row["stage"] for row in rows))
    if len(stages) < 2:
        raise ValueError("At least two distinct stages are required")
    groups = {}
    for row in rows:
        h = float(row["h_m"])
        if not math.isfinite(h) or h <= 0:
            raise ValueError("Mesh size must be positive and finite")
        groups.setdefault(h, []).append(row)
    mesh_sizes = sorted(groups, reverse=True)
    if len(mesh_sizes) < 2:
        raise ValueError("At least two distinct mesh sizes are required")
    reference_heads = {}
    for stage in stages:
        head_values = [float(r["head_m"]) for r in rows if r["stage"] == stage]
        if not all(math.isfinite(x) for x in head_values):
            raise ValueError("Water head must be finite")
        if max(head_values) - min(head_values) > 1e-10:
            raise ValueError("Groundwater head must be identical across meshes")
        reference_heads[stage] = head_values[0]
    results = []
    for h in mesh_sizes:
        these = groups[h]
        if len(these) != len(stages) or {r["stage"] for r in these} != set(stages):
            raise ValueError("Every mesh must report each stage exactly once")
        for stage in stages:
            row = next(r for r in these if r["stage"] == stage)
            for name in (
                "max_abs_pore_error_kpa", "max_abs_effective_stress_error_kpa",
                "rms_pore_error_kpa", "rms_effective_stress_error_kpa",
            ):
                value = float(row[name])
                if not math.isfinite(value) or value < 0:
                    raise ValueError(f"Invalid local error metric: {name}")
            results.append(classify_balance(row, "relative_residual",
                                            tolerance=tolerance))
    trends = {}
    for stage in stages:
        subset = [r for r in results if r["stage"] == stage]
        field = "max_abs_effective_stress_error_kpa"
        errors = [float(row[field]) for row in subset]
        trends[stage] = {
            "head_m": reference_heads[stage],
            "stress_error_nonincreasing": all(
                next_error <= old + 1e-12
                for old, next_error in zip(errors, errors[1:])
            ),
            "coarsest_stress_error_kpa": errors[0],
            "finest_stress_error_kpa": errors[-1],
            "finest_status": subset[-1]["status"],
        }
    return {
        "mesh_sizes_m": mesh_sizes,
        "stages": stages,
        "rows": results,
        "trends": trends,
        "all_rows_passed": all(r["status"] == "passed" for r in results),
        "warning": (
            "Refined local stress errors do not validate coupled "
            "excavation, seepage gradients or constitutive plasticity."
        ),
    }

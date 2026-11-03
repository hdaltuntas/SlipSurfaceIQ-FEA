"""Joint reporting of independent local and global groundwater accuracy.

This is a reporting gate, not an additional constitutive model.
Local Gauss-point stress and pore errors and the global reaction error
must be accepted separately; cancellation in the global resultant must
never conceal a local stress failure.
"""

from __future__ import annotations

import math

from slipsurface.fe2d.post.balance_acceptance import classify_balance


def compare_water_cut_fields(rows, *, tolerance=1e-6):
    """Summarize meshes ordered coarse to fine for the same physical column.

    Each row contains `h_m`, `head_m`, `global` and `local` dicts.
    The force reference and sampling target must agree across meshes.
    """
    if len(rows) < 2:
        raise ValueError("At least two mesh levels are required")
    output = []
    previous_h = math.inf
    reference = None
    head = None
    for sample in rows:
        h = float(sample["h_m"])
        if not math.isfinite(h) or h <= 0 or h >= previous_h:
            raise ValueError("Meshes must be strictly ordered coarse to fine")
        previous_h = h
        g, local = sample["global"], sample["local"]
        this_head = float(sample["head_m"])
        this_reference = float(g["expected_ry_kn_per_m"])
        if not all(math.isfinite(x) for x in (this_head, this_reference)):
            raise ValueError("Nonfinite physical reference")
        if this_reference <= 0:
            raise ValueError("Reaction reference must be positive")
        if reference is None:
            reference, head = this_reference, this_head
        elif not (
            math.isclose(this_reference, reference, rel_tol=1e-9, abs_tol=1e-8)
            and math.isclose(this_head, head, rel_tol=0, abs_tol=1e-10)
        ):
            raise ValueError("All meshes must share the same physical reference")
        if g["reference_method"] != "exact_polygon_clip":
            raise ValueError("Global reference must use exact polygon clipping")
        if int(g["water_table_cut_elements"]) <= 0:
            raise ValueError("No water-table cut elements in mesh")
        if not math.isclose(float(local["head_m"]), head, abs_tol=1e-10):
            raise ValueError("Local and global groundwater levels disagree")
        if int(local["gauss_points"]) <= 0:
            raise ValueError("Local field must contain Gauss-point samples")
        for field in (
            "max_abs_pore_error_kpa", "max_abs_effective_stress_error_kpa",
            "rms_pore_error_kpa", "rms_effective_stress_error_kpa",
        ):
            val = float(local[field])
            if not math.isfinite(val) or val < 0:
                raise ValueError(f"Invalid local error: {field}")
        global_check = classify_balance(g, "relative_residual", tolerance=tolerance)
        local_check = classify_balance(local, "relative_residual", tolerance=tolerance)
        output.append({
            "h_m": h, "head_m": this_head,
            "global": global_check, "local": local_check,
            "both_passed": (
                global_check["status"] == "passed"
                and local_check["status"] == "passed"
            ),
        })
    return {
        "meshes": output,
        "reference_ry_kn_per_m": reference,
        "all_meshes_passed": all(x["both_passed"] for x in output),
        "finest_mesh_passed": output[-1]["both_passed"],
        "finest_global_passed": output[-1]["global"]["status"] == "passed",
        "finest_local_passed": output[-1]["local"]["status"] == "passed",
        "warning": (
            "Global reaction agreement cannot mask local pore/stress errors; "
            "this column benchmark does not establish supported excavation validation."
        ),
    }

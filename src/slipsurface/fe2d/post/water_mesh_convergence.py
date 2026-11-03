"""F7 groundwater reaction mesh-refinement diagnostics, against exact clipping.

A finer mesh may improve or worsen the total force error when a water table
cuts finite elements. Do not infer monotonic convergence, or mark a model
verified merely because mesh sizes decrease.
"""

from __future__ import annotations

import math

from slipsurface.fe2d.post.balance_acceptance import classify_balance


def water_table_mesh_comparison(rows, *, tolerance=1e-6):
    """Return independently classified stages and successive error changes.

    Rows are in coarse-to-fine order, share the same physical analytical
    reference, and contain mesh length h, computed reactions, expected reaction,
    and the exact-cut relative error. Missing and nonfinite results are errors.
    """
    if len(rows) < 2:
        raise ValueError("At least two mesh resolutions are required")
    if any(
        not math.isfinite(float(row["h_m"])) or float(row["h_m"]) <= 0
        for row in rows
    ):
        raise ValueError("Mesh sizes must be positive and finite")
    sizes = [float(row["h_m"]) for row in rows]
    if any(fine >= coarse for coarse, fine in zip(sizes, sizes[1:])):
        raise ValueError("Mesh sizes must be strictly coarse-to-fine")
    reference = float(rows[0]["expected_ry_kn_per_m"])
    if not math.isfinite(reference) or reference <= 0:
        raise ValueError("Analytical reference must be finite and positive")
    output = []
    previous = None
    for row in rows:
        expected = float(row["expected_ry_kn_per_m"])
        actual = float(row["reaction_ry_kn_per_m"])
        relative_error = float(row["relative_residual"])
        if not math.isfinite(expected) or not math.isclose(
            expected, reference, rel_tol=1e-9, abs_tol=1e-8
        ):
            raise ValueError("All meshes must share an identical analytical reference")
        if not math.isfinite(actual):
            raise ValueError("Nonfinite FEM support reaction")
        if int(row["water_table_cut_elements"]) <= 0:
            raise ValueError("Each mesh must actually contain water-table-cut elements")
        result = classify_balance(row, "relative_residual", tolerance=tolerance)
        result["previous_error"] = previous
        result["error_change"] = (
            relative_error - previous if previous is not None else None
        )
        result["error_ratio"] = (
            relative_error / previous
            if previous is not None and previous > 0 else None
        )
        output.append(result)
        previous = relative_error
    return {
        "meshes": output,
        "reference_ry_kn_per_m": reference,
        "all_meshes_passed": all(row["status"] == "passed" for row in output),
        "finest_mesh_passed": output[-1]["status"] == "passed",
        "refinement_monotone_nonincreasing": all(
            output[i]["relative_residual"] <= output[i - 1]["relative_residual"]
            for i in range(1, len(output))
        ),
        "warning": (
            "A decreasing global force residual is not proof of local effective-stress "
            "convergence or coupled excavation safety."
        ),
    }

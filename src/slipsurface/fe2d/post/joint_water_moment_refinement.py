"""F7 independent hydrostatic pressure-centre mesh refinement diagnostic.

Multiple straight interface segments represent the same vertical wall.
Actual IFACE4 or IFACE6 water-load vectors are compared against the
unchanged analytical force and first-moment reference on every mesh.
"""

from __future__ import annotations

import math

import numpy as np

from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.model.mesh import ElementBlock, Mesh
from slipsurface.fe2d.post.joint_water_moment import vertical_joint_water_moment


def segmented_vertical_joint(segments, *, etype=ElemType.IFACE4,
                             bottom=-4.0, top=0.0, reverse=False):
    """Build a connected, two-faced vertical joint using shared endpoint IDs."""
    if not isinstance(segments, int) or segments < 1:
        raise ValueError("Number of segments must be a positive integer")
    if etype not in (ElemType.IFACE4, ElemType.IFACE6):
        raise ValueError("Only IFACE4 and IFACE6 are supported")
    if not all(math.isfinite(float(v)) for v in (bottom, top)) or top <= bottom:
        raise ValueError("Wall endpoints must be finite and ordered")
    levels = np.linspace(bottom, top, segments + 1)
    n = segments + 1
    coords = [[0.0, y] for y in levels]
    coords += [[0.0, y] for y in levels]
    if etype is ElemType.IFACE6:
        mids = 0.5 * (levels[:-1] + levels[1:])
        coords += [[0.0, y] for y in mids]
        coords += [[0.0, y] for y in mids]
    conns = []
    for i in range(segments):
        a, b = (i, i + 1) if not reverse else (i + 1, i)
        if etype is ElemType.IFACE4:
            conns.append([a, b, n + a, n + b])
        else:
            conns.append([
                a, b, 2 * n + i,
                n + a, n + b, 2 * n + segments + i,
            ])
    return Mesh(
        np.asarray(coords, dtype=float),
        (ElementBlock(
            etype, np.asarray(conns, dtype=int),
            np.ones(segments, dtype=int), "joint",
        ),),
    )


def joint_water_moment_refinement(
    spec, resolutions=(1, 2, 4, 8), *,
    etype=ElemType.IFACE4, head=0.0,
    bottom=-4.0, top=0.0, reverse=False, tolerance=1e-6,
):
    """Return genuine force/moment convergence, not inferred convergence order.

    The same physical wall and head are kept across meshes. Every result
    independently compares the actual FEM nodal water loads with the
    exact continuous-force and moment integral.
    """
    if len(resolutions) < 2 or any(
        not isinstance(n, int) or n < 1 for n in resolutions
    ) or any(b <= a for a, b in zip(resolutions, resolutions[1:])):
        raise ValueError("At least two strictly increasing segment counts required")
    if not math.isfinite(float(head)):
        raise ValueError("Water head must be finite")
    results = []
    expected_force = None
    expected_moment = None
    for n in resolutions:
        mesh = segmented_vertical_joint(
            n, etype=etype, bottom=bottom, top=top, reverse=reverse
        )
        audit = vertical_joint_water_moment(
            mesh, "joint", spec, head, tolerance=tolerance,
        )
        force = audit["reference_force_kn_per_m"]
        moment = audit["reference_moment_knm_per_m"]
        if expected_force is None:
            expected_force, expected_moment = force, moment
        elif not (
            math.isclose(force, expected_force, rel_tol=1e-10, abs_tol=1e-9)
            and math.isclose(moment, expected_moment, rel_tol=1e-10, abs_tol=1e-9)
        ):
            raise ValueError("Analytical reference changed across meshes")
        results.append({
            "segments": n,
            "h_m": (top - bottom) / n,
            "nodes": mesh.nn,
            **audit,
        })
    moment_errors = [abs(row["moment_error_knm_per_m"]) for row in results]
    return {
        "element_type": etype.name,
        "head_m": float(head),
        "wall_bottom_m": float(bottom),
        "wall_top_m": float(top),
        "reference_force_kn_per_m": float(expected_force),
        "reference_moment_knm_per_m": float(expected_moment),
        "rows": results,
        "moment_error_nonincreasing": all(
            right <= left + 1e-10
            for left, right in zip(moment_errors, moment_errors[1:])
        ),
        "finest_force_passed": results[-1]["force_status"] == "passed",
        "finest_moment_passed": results[-1]["status"] == "passed",
        "finest_both_passed": results[-1]["both_passed"],
        "warning": (
            "This is a water-load integration benchmark, not a solved "
            "retaining-wall bending or soil-structure convergence audit."
        ),
    }

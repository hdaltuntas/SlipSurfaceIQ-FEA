"""Independent hydrostatic force reference for vertical plane-strain boundaries.

These formulas use a closed-form integral of p(y)=gamma_w max(h-y, 0)
rather than the FEM boundary quadrature. They are deliberately restricted
to vertical straight edges and a horizontal piezometric level. The
resultant is positive *into* the material (opposite to outward normal).
"""

from __future__ import annotations

import math

import numpy as np

from slipsurface.fe2d.core.units import GAMMA_W


def vertical_wall_water_resultant(
    y0: float, y1: float, head: float, outward_nx: float, *, gamma_w=GAMMA_W
) -> dict:
    """Exact integrated water force per out-of-plane metre for vertical wall.

    The outward normal must be either +X or -X. A partially submerged
    interval is handled exactly, without assuming the pressure is uniform.
    """
    numbers = (y0, y1, head, outward_nx, gamma_w)
    if not all(math.isfinite(v) for v in numbers):
        raise ValueError("Wall geometry, water head and unit weight must be finite")
    if y0 == y1 or gamma_w <= 0:
        raise ValueError("Wall height and water unit weight must be positive")
    if abs(abs(outward_nx) - 1.0) > 1e-12:
        raise ValueError("A vertical wall requires outward_nx of +1 or -1")
    low, high = sorted((float(y0), float(y1)))
    # Integral_low^high max(head-y, 0) dy
    area = 0.5 * gamma_w * (
        max(head - low, 0.0) ** 2 - max(head - high, 0.0) ** 2
    )
    pressure_base = gamma_w * max(head - low, 0.0)
    return {
        "low_y_m": low,
        "high_y_m": high,
        "head_m": float(head),
        "hydrostatic_resultant_kn_per_m": float(area),
        "force_fx_kn_per_m": float(-outward_nx * area),
        "force_fy_kn_per_m": 0.0,
        "base_pressure_kpa": float(pressure_base),
        "submerged_height_m": float(max(min(head, high) - low, 0.0)),
    }


def compare_vertical_water_edge(mesh, edge, inner, water, *, gamma_w=GAMMA_W):
    """Compare analytical resultant with integrated FEM pressure-edge forces.

    Only horizontal piezometric lines, straight vertical element edges,
    and plane strain are accepted. The FEM integration may approximate
    the kink at the water table; its error is deliberately reported.
    """
    from slipsurface.fe2d.core.enums import Analysis
    from slipsurface.fe2d.fem.loads import pressure_edge_forces

    if water.mode != "piezo_line":
        raise ValueError("Only prescribed piezometric water lines supported")
    line = np.asarray(water.piezo_polyline, dtype=float)
    if not np.allclose(line[:, 1], line[0, 1], atol=1e-12, rtol=0):
        raise ValueError("Piezometric level must be horizontal")
    e = np.asarray(edge, dtype=int).ravel()
    coords = mesh.coords[e]
    if e.size not in (2, 3):
        raise ValueError("Only linear or quadratic vertical edges supported")
    if np.ptp(coords[:, 0]) > 1e-10:
        raise ValueError("Edge must be vertical and straight")
    if e.size == 3 and not np.isclose(
        coords[2, 1], (coords[0, 1] + coords[1, 1]) / 2,
        atol=1e-10, rtol=0,
    ):
        raise ValueError("Quadratic edge must be straight with centered mid-node")
    center = coords[:2].mean(axis=0)
    inward = np.asarray(inner, dtype=float) - center
    if abs(inward[0]) < 1e-12:
        raise ValueError("Interior point must define outward face normal")
    outward_nx = -float(np.sign(inward[0]))
    analytic = vertical_wall_water_resultant(
        coords[0, 1], coords[1, 1], float(line[0, 1]), outward_nx,
        gamma_w=gamma_w,
    )
    nodal = pressure_edge_forces(
        mesh.coords, e[None, :], np.asarray(inner, dtype=float)[None, :],
        lambda points: gamma_w * np.maximum(water.head(points[:, 0]) - points[:, 1], 0.0),
        Analysis.PLANE_STRAIN,
    )
    computed = nodal.sum(axis=(0, 1))
    target = np.array([
        analytic["force_fx_kn_per_m"], analytic["force_fy_kn_per_m"]
    ])
    difference = computed - target
    scale = max(float(np.linalg.norm(target)), 1.0)
    return {
        **analytic,
        "fem_fx_kn_per_m": float(computed[0]),
        "fem_fy_kn_per_m": float(computed[1]),
        "residual_fx_kn_per_m": float(difference[0]),
        "residual_fy_kn_per_m": float(difference[1]),
        "relative_resultant_error": float(np.linalg.norm(difference) / scale),
    }

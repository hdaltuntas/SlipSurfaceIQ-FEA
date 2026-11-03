"""Independent local pore-pressure and effective-stress reference for a soil column.

This is a one-dimensional, homogeneous, gravity-loaded, plane-strain
reference, not a general groundwater or supported excavation audit.
The exact total vertical stress is accumulated from bulk soil weight and
any free water standing above the soil. Effective stress is total minus
the hydrostatic pore pressure, with tension-positive FEM signs.
"""

from __future__ import annotations

import math

import numpy as np

from slipsurface.fe2d.core.enums import Analysis
from slipsurface.fe2d.core.units import GAMMA_W
from slipsurface.fe2d.post.balance_acceptance import classify_balance


def column_reference(y, head, gamma_unsat, gamma_sat, *, surface=0.0):
    """Exact (pore kPa, vertical effective sigma kPa) at elevations y."""
    values = (head, gamma_unsat, gamma_sat, surface)
    if not all(math.isfinite(float(x)) for x in values):
        raise ValueError("Reference parameters must be finite")
    if gamma_unsat < 0 or gamma_sat < 0:
        raise ValueError("Bulk unit weights must be nonnegative")
    elev = np.asarray(y, dtype=float)
    if not np.isfinite(elev).all() or np.any(elev > surface + 1e-9):
        raise ValueError("Sampling points must lie inside the ground")
    depth = np.maximum(surface - elev, 0.0)
    dry_depth = np.minimum(depth, max(surface - head, 0.0))
    sat_depth = depth - dry_depth
    total = gamma_unsat * dry_depth + gamma_sat * sat_depth
    total += GAMMA_W * max(head - surface, 0.0)
    pore = GAMMA_W * np.maximum(head - elev, 0.0)
    return pore, -(total - pore)


def local_column_errors(model, result, stage_index=None):
    """Compare Gauss-point FEM pore/sigma_yy with independent 1D fields.

    Only single-material, fully active, horizontal uniform hydrostatic
    gravity columns are supported. Stage indices are zero-based; None
    denotes the initial stress state.
    """
    if model.analysis is not Analysis.PLANE_STRAIN:
        raise ValueError("Only plane strain is supported")
    if model.initial.mode != "gravity":
        raise ValueError("Gravity initialization required")
    if model.liners or model.bolts or model.interfaces or model.displacements:
        raise ValueError("Structures and imposed displacements are unsupported")
    if len(set(model.region_material.values())) != 1:
        raise ValueError("Only one homogeneous material is supported")
    if stage_index is None:
        stage = result.initial
        water = model.initial.water
    else:
        if not 0 <= stage_index < len(result.stages):
            raise IndexError("Stage index outside result")
        if any(
            item.loads or item.active_regions is not None or item.active_structures
            or item.material_override or item.displacements
            or item.seismic_kh or item.seismic_kv or item.load_split != 1.0
            for item in model.stages[:stage_index + 1]
        ):
            raise ValueError("Changed load, geometry or material is unsupported")
        stage = result.stages[stage_index]
        water = model.stages[stage_index].water
    if water.mode != "piezo_line":
        raise ValueError("Horizontal piezometric line required")
    line = np.asarray(water.piezo_polyline, dtype=float)
    if not np.allclose(line[:, 1], line[0, 1], atol=1e-10, rtol=0):
        raise ValueError("Sloping piezometric line unsupported")
    material = model.materials[next(iter(model.region_material.values()))]
    if material.drainage.value != "drained":
        raise ValueError("Undrained reference unsupported")
    coords = model.mesh.coords
    surface = float(coords[:, 1].max())
    xmin, xmax = coords[:, 0].min(), coords[:, 0].max()
    ymin = coords[:, 1].min()
    # Restrict to a full rectangular domain, not a free-form excavation.
    measured_area = 0.0
    highest_pore = 0.0
    highest_stress = 0.0
    sumsq_pore = 0.0
    sumsq_stress = 0.0
    count = 0
    scale = max(
        1.0,
        material.gamma_sat * (surface - ymin),
        material.gamma_unsat * (surface - ymin),
        GAMMA_W * max(float(line[0, 1]) - ymin, 0.0),
    )
    for block in model.mesh.continuum_blocks():
        active = np.asarray(stage.active[block.tag], dtype=bool)
        if active.shape != (block.ne,) or not active.all():
            raise ValueError("Excavation is unsupported")
        geom = result.geom[block.tag]
        measured_area += float(np.sum(geom.wdet))
        points = geom.xg[..., 1]
        expected_p, expected_s = column_reference(
            points, float(line[0, 1]), material.gamma_unsat,
            material.gamma_sat, surface=surface,
        )
        actual_p = np.asarray(stage.pore[block.tag])
        actual_s = np.asarray(stage.sig[block.tag])[..., 1]
        if (
            actual_p.shape != expected_p.shape or actual_s.shape != expected_s.shape
            or not np.isfinite(actual_p).all() or not np.isfinite(actual_s).all()
        ):
            raise ValueError("Invalid local FEM pore pressure or stress")
        dp = actual_p - expected_p
        ds = actual_s - expected_s
        highest_pore = max(highest_pore, float(np.max(np.abs(dp))))
        highest_stress = max(highest_stress, float(np.max(np.abs(ds))))
        sumsq_pore += float(np.sum(dp**2))
        sumsq_stress += float(np.sum(ds**2))
        count += dp.size
    if count == 0 or not math.isclose(
        measured_area, float((xmax - xmin) * (surface - ymin)),
        rel_tol=1e-8, abs_tol=1e-8,
    ):
        raise ValueError("Requires a fully filled rectangular soil column")
    worst = max(highest_pore, highest_stress)
    return {
        "stage": stage.name,
        "head_m": float(line[0, 1]),
        "gauss_points": count,
        "max_abs_pore_error_kpa": highest_pore,
        "max_abs_effective_stress_error_kpa": highest_stress,
        "rms_pore_error_kpa": math.sqrt(sumsq_pore / count),
        "rms_effective_stress_error_kpa": math.sqrt(sumsq_stress / count),
        "relative_residual": worst / scale,
    }


def local_column_errors_by_stage(model, result, *, tolerance=1e-6):
    """Never certify invalid/out-of-scope local stresses as passing."""
    output = []
    for index in (None, *range(len(result.stages))):
        name = "initial" if index is None else result.stages[index].name
        try:
            output.append(classify_balance(
                local_column_errors(model, result, index),
                "relative_residual", tolerance=tolerance,
            ))
        except (ValueError, KeyError, IndexError) as exc:
            output.append({"stage": name, "status": "unsupported", "reason": str(exc)})
    return output

"""F7 independent dry excavation-weight and newly exposed face load budget.

For completed stages with load_split=1, full exterior pressure target and
the weight of the *currently active* continuum should balance reactions.
The unit budget is kN per metre out of plane (plane strain). Newly exposed
edges are detected against active-element connectivity, not against the
original unearthed mesh boundary.

This diagnostic intentionally refuses partial stages, water, seismic
inertia, point-load singularities (supported only as external point forces),
interfaces/structures and prestressing: those require additional force
budgets and cannot be declared verified from the simplified equation.
"""

from __future__ import annotations

import numpy as np

from slipsurface.fe2d.core.enums import Analysis
from slipsurface.fe2d.post.balance_acceptance import classify_balance
from slipsurface.fe2d.post.dry_load_balance import independent_stage_loads


def excavation_stage_balance(model, result, index):
    """Reactions vs weight plus loads after excavating inactive continuum."""
    if model.analysis is not Analysis.PLANE_STRAIN:
        raise ValueError("Only plane strain is supported")
    if not 0 <= index < len(result.stages):
        raise IndexError("Stage outside computed results")
    if model.initial.mode not in ("gravity", "k0_field"):
        raise ValueError("Gravity/K0 initial state required")
    if model.initial.water.mode != "none" or model.displacements:
        raise ValueError("Water or prescribed displacement unsupported")
    if model.liners or model.bolts or model.interfaces:
        raise ValueError("Coupled structures/interfaces need a separate force budget")
    if getattr(model, "extra_tractions", None):
        raise ValueError("Additional unmodeled tractions unsupported")
    for earlier in model.stages[:index + 1]:
        if earlier.load_split != 1.0:
            raise ValueError("Partial load splits need an incremental force budget")
        if earlier.water.mode != "none" or earlier.seismic_kh or earlier.seismic_kv:
            raise ValueError("Water or seismic inertia unsupported")
        if earlier.displacements or earlier.material_override or earlier.active_structures:
            raise ValueError("Changed properties/supports/displacements unsupported")
    stage = result.stages[index]
    if not np.isclose(stage.lam, 1.0):
        raise ValueError("Stage did not reach full load")
    weight = 0.0
    for block in model.mesh.continuum_blocks():
        active = np.asarray(stage.active[block.tag], dtype=bool)
        if active.shape != (block.ne,):
            raise ValueError("Active element mask shape mismatch")
        area = np.sum(result.geom[block.tag].wdet, axis=1)
        if not np.isfinite(area).all():
            raise ValueError("Nonfinite element area")
        gamma = np.array([
            model.materials[model.region_material[int(region)]].gamma_unsat
            for region in block.region
        ])
        weight += float(np.dot(area[active], gamma[active]))

    external = independent_stage_loads(
        model, model.stages[index], active_masks=stage.active
    )
    predicted = -external + np.array([0.0, weight])
    reactions = np.asarray(stage.reactions, dtype=float)[:, :2].sum(axis=0)
    error = reactions - predicted
    norm = max(1.0, weight, np.linalg.norm(external), np.linalg.norm(predicted))
    return {
        "stage": stage.name,
        "active_soil_weight_kn_per_m": weight,
        "external_fx_kn_per_m": float(external[0]),
        "external_fy_kn_per_m": float(external[1]),
        "reaction_fx_kn_per_m": float(reactions[0]),
        "reaction_fy_kn_per_m": float(reactions[1]),
        "residual_fx_kn_per_m": float(error[0]),
        "residual_fy_kn_per_m": float(error[1]),
        "relative_residual": float(np.linalg.norm(error) / norm),
    }


def excavation_balance_by_stage(model, result):
    """Return checked or explicitly unsupported for each completed stage."""
    rows = []
    for index, stage in enumerate(result.stages):
        try:
            row = classify_balance(
                excavation_stage_balance(model, result, index), "relative_residual"
            )
        except (ValueError, KeyError, IndexError) as exc:
            row = {"stage": stage.name, "status": "unsupported", "reason": str(exc)}
        rows.append(row)
    return rows

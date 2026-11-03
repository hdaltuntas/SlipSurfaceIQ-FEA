"""F7 independent gravity-only global force budget for staged excavations.

The analytical exterior vertical force is the weight of all *active*
continuum and beam elements, integrated independently of the nonlinear
solver's assembled internal-force vector. The sum of all prescribed-node
reactions should oppose the weight, per out-of-plane metre.

Restricted deliberately to plane strain, gravity/K0 initial states, dry
stages without surface/point loads or pseudo-static accelerations. The
restriction prevents a false equilibrium claim when water, staged external
loads, pretension, or additional tractions require distinct load accounting.
"""

from __future__ import annotations

import numpy as np

from slipsurface.fe2d.core.enums import Analysis, ElemType


def gravity_equilibrium_budget(model, result, stage_index: int) -> dict:
    """Compare active material/beam weight to the actual stage support reactions.

    stage_index is zero-based in the list of computed user stages.
    A returned signed vertical residual is R_y - W, with W positive.
    """
    if model.analysis is not Analysis.PLANE_STRAIN:
        raise ValueError("Gravity balance currently supports plane strain only")
    if model.initial.mode not in ("gravity", "k0_field"):
        raise ValueError("Gravity balance needs gravity or k0_field initialization")
    if model.initial.water.mode != "none":
        raise ValueError("Initial groundwater requires a separate water-force budget")
    if not 0 <= stage_index < len(result.stages):
        raise IndexError("Stage index is outside computed results")
    stage_def = model.stages[stage_index]
    if stage_def.water.mode != "none":
        raise ValueError("Stage groundwater requires a separate water-force budget")
    if stage_def.loads or stage_def.seismic_kh or stage_def.seismic_kv:
        raise ValueError("External or seismic stage loads require a separate force budget")
    if stage_def.displacements or model.displacements:
        raise ValueError("Imposed displacements require a separate force budget")
    if any(prior.material_override for prior in model.stages[:stage_index + 1]):
        raise ValueError("Stage material overrides require a cumulative material budget")
    if model.bolts and any(
        tag in stage_def.active_structures and spec.pretension
        for tag, spec in model.bolts.items()
    ):
        raise ValueError("Pretension requires a separate force budget")
    if model.liners and any(
        tag in stage_def.active_structures and spec.shotcrete_EA
        for tag, spec in model.liners.items()
    ):
        raise ValueError("Variable shotcrete maturity requires stage-specific body weights")

    stage = result.stages[stage_index]
    soil_weight = 0.0
    region_names = {**model.region_material, **stage_def.material_override}
    for block in model.mesh.continuum_blocks():
        active = np.asarray(stage.active[block.tag], dtype=bool)
        if active.shape != (block.ne,):
            raise ValueError(f"{block.tag}: active mask shape mismatch")
        geom = result.geom[block.tag]
        areas = np.sum(geom.wdet, axis=1)
        if areas.shape != (block.ne,) or not np.isfinite(areas).all():
            raise ValueError(f"{block.tag}: invalid integration weights")
        gamma = np.array([
            model.materials[region_names[int(region)]].gamma_unsat
            for region in block.region
        ])
        soil_weight += float(np.dot(areas[active], gamma[active]))

    beam_weight = 0.0
    for block in model.mesh.blocks:
        if block.etype is not ElemType.BEAM2:
            continue
        active = np.asarray(stage.active[block.tag], dtype=bool)
        if active.shape != (block.ne,):
            raise ValueError(f"{block.tag}: active mask shape mismatch")
        spec = model.liners[block.tag]
        endpoints = model.mesh.coords[block.conn]
        lengths = np.linalg.norm(endpoints[:, 1] - endpoints[:, 0], axis=1)
        beam_weight += float(np.sum(lengths[active]) * spec.A * spec.unit_weight)

    reactions = np.asarray(stage.reactions, dtype=float)
    if reactions.shape[1] < 2 or not np.isfinite(reactions).all():
        raise ValueError("Invalid stage reactions")
    rx, ry = (float(x) for x in reactions[:, :2].sum(axis=0))
    total = soil_weight + beam_weight
    norm = max(total, 1.0)
    return {
        "stage": stage.name,
        "soil_weight_kn_per_m": soil_weight,
        "beam_weight_kn_per_m": beam_weight,
        "expected_vertical_reaction_kn_per_m": total,
        "reaction_fx_kn_per_m": rx,
        "reaction_fy_kn_per_m": ry,
        "imbalance_fx_kn_per_m": rx,
        "imbalance_fy_kn_per_m": ry - total,
        "relative_resultant_imbalance": float(np.hypot(rx, ry - total) / norm),
    }


def gravity_equilibrium_by_stage(model, result) -> list[dict]:
    """Return results, or explicit reasons that a stage is outside current scope."""
    output = []
    for index, stage in enumerate(result.stages):
        try:
            entry = gravity_equilibrium_budget(model, result, index)
            entry["status"] = "checked"
        except (ValueError, KeyError, IndexError) as exc:
            entry = {"stage": stage.name, "status": "unsupported", "reason": str(exc)}
        output.append(entry)
    return output

"""F7 independent vertical resultant for a horizontal, saturated soil column.

The analytical external-force budget is the soil's bulk weight above and
below the phreatic level, plus hydrostatic water surcharge when the head
stands above the ground surface. It never uses the solver's pore pressure
forces or its assembled right-hand-side vector.

The scope is deliberately restricted to an unexcavated, fully supported
plane-strain rectangular column with an element-aligned horizontal water
table. This is not a general water-force budget for excavations.
"""

from __future__ import annotations

import math

import numpy as np

from slipsurface.fe2d.core.enums import Analysis
from slipsurface.fe2d.core.units import GAMMA_W
from slipsurface.fe2d.post.balance_acceptance import classify_balance


def saturated_column_budget(model, result, stage_index=None):
    """Independent hydrostatic and gravity Ry benchmark, in kN/m.

    stage_index=None evaluates the initial state. Otherwise it evaluates
    the requested completed stage, which must prescribe the corresponding
    groundwater condition explicitly.
    """
    if model.analysis is not Analysis.PLANE_STRAIN:
        raise ValueError("Only plane-strain rectangular columns supported")
    if model.initial.mode != "gravity":
        raise ValueError("Gravity initial stress mode required")
    if model.liners or model.bolts or model.interfaces:
        raise ValueError("Structures or interfaces require a coupled force budget")
    if model.displacements:
        raise ValueError("Prescribed displacement is not covered")

    if stage_index is None:
        stage = result.initial
        water = model.initial.water
    else:
        if not 0 <= stage_index < len(result.stages):
            raise IndexError("Stage index outside computed results")
        if any(
            st.loads or st.active_regions is not None or st.active_structures
            or st.displacements or st.seismic_kh or st.seismic_kv
            or st.material_override or st.load_split != 1
            for st in model.stages[:stage_index + 1]
        ):
            raise ValueError("Stage loads, excavation or partial steps are unsupported")
        stage = result.stages[stage_index]
        water = model.stages[stage_index].water
    if water.mode != "piezo_line":
        raise ValueError("Horizontal piezometric line required")
    line = np.asarray(water.piezo_polyline, dtype=float)
    if not np.allclose(line[:, 1], line[0, 1], rtol=0, atol=1e-10):
        raise ValueError("Water head must be horizontal")
    head = float(line[0, 1])

    coords = model.mesh.coords
    x0, x1 = float(coords[:, 0].min()), float(coords[:, 0].max())
    y0, y1 = float(coords[:, 1].min()), float(coords[:, 1].max())
    width = x1 - x0
    if width <= 0 or y1 <= y0:
        raise ValueError("Rectangular domain must have positive dimensions")
    if not np.isfinite(stage.reactions).all():
        raise ValueError("Nonfinite support reactions")

    dry_weight = 0.0
    saturated_weight = 0.0
    areas_sum = 0.0
    for block in model.mesh.continuum_blocks():
        mask = np.asarray(stage.active[block.tag], dtype=bool)
        if mask.shape != (block.ne,) or not mask.all():
            raise ValueError("Continuum excavation is unsupported")
        corners = block.conn[:, :3] if block.etype.name.startswith("T") else block.conn[:, :4]
        vertices = coords[corners]
        ymin = vertices[:, :, 1].min(axis=1)
        ymax = vertices[:, :, 1].max(axis=1)
        if np.any((ymin < head - 1e-9) & (ymax > head + 1e-9)):
            raise ValueError("Water table must follow element edges")
        # Use element geometry's Gauss quadrature for exact straight-sided area.
        areas = np.asarray(result.geom[block.tag].wdet).sum(axis=1)
        if not np.isfinite(areas).all() or np.any(areas <= 0):
            raise ValueError("Nonpositive element area")
        areas_sum += float(areas.sum())
        for idx, region in enumerate(block.region):
            spec = model.materials[model.region_material[int(region)]]
            if ymin[idx] >= head - 1e-9:
                dry_weight += float(areas[idx] * spec.gamma_unsat)
            else:
                saturated_weight += float(areas[idx] * spec.gamma_sat)
    if not math.isclose(areas_sum, width * (y1 - y0), rel_tol=1e-8, abs_tol=1e-8):
        raise ValueError("Column requires a fully filled rectangular continuum")
    water_surface_force = GAMMA_W * max(head - y1, 0.0) * width
    expected_ry = dry_weight + saturated_weight + water_surface_force
    rx, ry = (float(v) for v in stage.reactions[:, :2].sum(axis=0))
    residual = math.hypot(rx, ry - expected_ry)
    return {
        "stage": stage.name,
        "water_head_m": head,
        "dry_soil_weight_kn_per_m": dry_weight,
        "saturated_soil_weight_kn_per_m": saturated_weight,
        "water_surface_force_kn_per_m": water_surface_force,
        "expected_ry_kn_per_m": expected_ry,
        "reaction_rx_kn_per_m": rx,
        "reaction_ry_kn_per_m": ry,
        "relative_residual": residual / max(expected_ry, 1.0),
    }


def saturated_column_budget_by_stage(model, result):
    """Explicit pass/fail/unsupported rows for initial + completed stages."""
    rows = []
    for index in (None, *range(len(result.stages))):
        name = "initial" if index is None else result.stages[index].name
        try:
            row = classify_balance(
                saturated_column_budget(model, result, index), "relative_residual"
            )
        except (ValueError, KeyError, IndexError) as exc:
            row = {"stage": name, "status": "unsupported", "reason": str(exc)}
        rows.append(row)
    return rows

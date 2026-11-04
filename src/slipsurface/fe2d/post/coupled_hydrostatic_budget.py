"""Bounded full-stage horizontal-head water/soil/structure equilibrium audit."""

from __future__ import annotations

from .coupled_dry_budget import _coupled_dry_components, _summarize_dry_components


def coupled_hydrostatic_stage_budget(model, result, index):
    if model.stages[index].water.mode != "piezo_line":
        raise ValueError("An explicit horizontal piezometric stage is required")
    components = _coupled_dry_components(model, result, index, hydrostatic=True)
    return _summarize_dry_components(model, result.stages[index], components)


def coupled_hydrostatic_budget_by_stage(model, result):
    rows = []
    for index, stage in enumerate(result.stages):
        try:
            row = coupled_hydrostatic_stage_budget(model, result, index)
        except (ValueError, KeyError, IndexError) as exc:
            row = {"stage": stage.name, "status": "unsupported", "reason": str(exc)}
        rows.append(row)
    return rows

"""Full-stage seepage-derived pressure transfer and coupled mechanical equilibrium."""

from __future__ import annotations

from .coupled_dry_budget import _coupled_dry_components, _summarize_dry_components


def coupled_seepage_stage_budget(model, result, index):
    components = _coupled_dry_components(model, result, index, seepage=True)
    return _summarize_dry_components(model, result.stages[index], components)


def coupled_seepage_budget_by_stage(model, result):
    rows = []
    for index, stage in enumerate(result.stages):
        try:
            row = coupled_seepage_stage_budget(model, result, index)
        except (ValueError, KeyError, IndexError) as exc:
            row = {"stage": stage.name, "status": "unsupported", "reason": str(exc)}
        rows.append(row)
    return rows

"""Changing horizontal heads and partial wet elastic stages; no seepage history."""

from __future__ import annotations

from .incremental_dry_budget import _incremental_budget_by_stage


def incremental_hydrostatic_budget_by_stage(model, result):
    """Reconstruct target water fields, actual applied loads and retained release."""
    return _incremental_budget_by_stage(model, result, hydrostatic=True)

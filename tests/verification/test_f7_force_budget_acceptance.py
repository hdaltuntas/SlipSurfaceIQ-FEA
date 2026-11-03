"""F7 force-budget acceptance: never mistake computed residual for a pass."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from slipsurface.fe2d.post import dry_load_balance, excavation_balance, global_balance
from slipsurface.fe2d.post.balance_acceptance import (
    classify_balance,
    summarize_balances,
)


@pytest.mark.parametrize("value,status", [
    (0.0, "passed"),
    (1e-6, "passed"),
    (1.0001e-6, "failed"),
    (1e-2, "failed"),
    (float("nan"), "failed"),
    (float("inf"), "failed"),
    (-0.01, "failed"),
])
def test_relative_force_balance_has_explicit_acceptance_state(value, status):
    original = {"stage": "excavated", "relative_residual": value}
    result = classify_balance(original, "relative_residual")
    assert original == {"stage": "excavated", "relative_residual": value} or np.isnan(value)
    assert result["status"] == status
    assert result["acceptance_tolerance"] == pytest.approx(1e-6)
    if status == "failed":
        assert result["reason"]


@pytest.mark.parametrize("invalid", [0, -1, float("nan"), float("inf")])
def test_invalid_acceptance_tolerance_refused(invalid):
    with pytest.raises(ValueError, match="tolerance"):
        classify_balance({"relative_residual": 0.0}, "relative_residual",
                         tolerance=invalid)


def test_summary_never_converts_unsupported_or_failed_to_verified():
    partial = summarize_balances([
        {"status": "passed"}, {"status": "unsupported"},
    ])
    assert partial == {
        "passed": 1, "failed": 0, "unsupported": 1, "total": 2,
        "all_supported_passed": True, "fully_verified": False,
    }
    failed = summarize_balances([{"status": "passed"}, {"status": "failed"}])
    assert failed["fully_verified"] is False
    assert failed["all_supported_passed"] is False
    assert summarize_balances([{"status": "passed"}])["fully_verified"] is True
    assert summarize_balances([])["fully_verified"] is False
    with pytest.raises(ValueError, match="Unknown"):
        summarize_balances([{"status": "checked"}])


@pytest.mark.parametrize("module,calc,wrapper,metric", [
    (global_balance, "gravity_equilibrium_budget",
     "gravity_equilibrium_by_stage", "relative_resultant_imbalance"),
    (dry_load_balance, "dry_stage_load_balance",
     "dry_stage_load_balance_by_stage", "relative_imbalance"),
    (excavation_balance, "excavation_stage_balance",
     "excavation_balance_by_stage", "relative_residual"),
])
def test_stage_wrappers_fail_on_unbalanced_solution(
    monkeypatch, module, calc, wrapper, metric,
):
    mock = SimpleNamespace(stages=[SimpleNamespace(name="lift")])
    monkeypatch.setattr(
        module, calc,
        lambda _model, _result, _index: {"stage": "lift", metric: 0.125},
    )
    output = getattr(module, wrapper)(None, mock)
    assert len(output) == 1
    assert output[0]["status"] == "failed"
    assert "exceeds" in output[0]["reason"]
    assert output[0][metric] == pytest.approx(0.125)


@pytest.mark.parametrize("module,calc,wrapper,metric", [
    (global_balance, "gravity_equilibrium_budget",
     "gravity_equilibrium_by_stage", "relative_resultant_imbalance"),
    (dry_load_balance, "dry_stage_load_balance",
     "dry_stage_load_balance_by_stage", "relative_imbalance"),
    (excavation_balance, "excavation_stage_balance",
     "excavation_balance_by_stage", "relative_residual"),
])
def test_stage_wrappers_preserve_unsupported_state(
    monkeypatch, module, calc, wrapper, metric,
):
    mock = SimpleNamespace(stages=[SimpleNamespace(name="lift")])

    def unsupported(_model, _result, _index):
        raise ValueError("not in bounded reference scope")

    monkeypatch.setattr(module, calc, unsupported)
    output = getattr(module, wrapper)(None, mock)
    assert output[0]["status"] == "unsupported"
    assert "bounded reference scope" in output[0]["reason"]

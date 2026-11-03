"""Unit checks for the optional staged excavation mesh-audit report."""

from __future__ import annotations

import runpy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("shapely")

AUDIT = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "examples" /
        "f7_excavation_mesh_audit.py")
)


def test_stage_metrics_excludes_inactive_nan_displacements():
    from slipsurface.fe2d.fem.nonlinear import StageHistory, StepRecord

    history = StageHistory([
        StepRecord(0.5, 3, [1.0, 0.01], True),
        StepRecord(0.7, 7, [0.9, 0.1], False),
        StepRecord(1.0, 4, [0.2, 0.0001], True),
    ])
    stage = SimpleNamespace(
        name="Excavation",
        u=np.array([[0., -0.01], [np.nan, np.nan], [0.02, 0.]]),
        reactions=np.array([[0., 10., 0.], [1., 20., 0.], [-1., 30., 0.]]),
        plastic={"soil": np.array([[0, 1], [1, 0]], dtype=np.uint8)},
        history=history,
        lam=1.0,
    )
    result = AUDIT["stage_metrics"](stage, h=1.2, nodes=3, elements=2)
    assert result["max_displacement_m"] == pytest.approx(0.02)
    assert result["reaction_fy_kn_per_m"] == pytest.approx(60.0)
    assert result["active_plastic_gauss_points"] == 2
    assert result["accepted_steps"] == 2
    assert result["rejected_steps"] == 1
    assert result["newton_iterations"] == 14
    assert result["last_accepted_residual"] == pytest.approx(1e-4)


def test_mesh_difference_report_preserves_stages_and_coarse_baseline():
    rows = [
        {"stage": "Head", "max_displacement_m": 0.010},
        {"stage": "Bench", "max_displacement_m": 0.020},
        {"stage": "Head", "max_displacement_m": 0.011},
        {"stage": "Bench", "max_displacement_m": 0.022},
        {"stage": "Head", "max_displacement_m": 0.0111},
    ]
    AUDIT["attach_mesh_differences"](rows)
    assert rows[0]["relative_displacement_change"] is None
    assert rows[1]["relative_displacement_change"] is None
    assert rows[2]["relative_displacement_change"] == pytest.approx(0.001 / 0.011)
    assert rows[3]["relative_displacement_change"] == pytest.approx(0.002 / 0.022)
    assert rows[4]["relative_displacement_change"] == pytest.approx(0.0001 / 0.0111)

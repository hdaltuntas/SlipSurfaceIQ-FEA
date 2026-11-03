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
        beams={"liner": np.array([[[0.0, 0.0, -7.0], [0.0, 0.0, 12.0]]])},
        bars={"anchor": np.array([5.0, -9.0])},
        history=history,
        lam=1.0,
    )
    result = AUDIT["stage_metrics"](stage, h=1.2, nodes=3, elements=2)
    assert result["max_displacement_m"] == pytest.approx(0.02)
    assert result["reaction_fy_kn_per_m"] == pytest.approx(60.0)
    assert result["active_plastic_gauss_points"] == 2
    assert result["max_abs_beam_moment"] == pytest.approx(12.0)
    assert result["max_abs_bar_axial_force"] == pytest.approx(9.0)
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


def test_magnitude_metric_ignores_inactive_structural_nan():
    metric = AUDIT["maximum_finite_magnitude"]
    assert metric([np.array([np.nan, -3.0]), np.array([np.nan, 5.0])]) == 5.0
    assert metric([np.array([np.nan])]) == 0.0
    assert metric([]) == 0.0


def test_structural_peak_metrics_are_tagged_and_ignore_nan():
    stage = SimpleNamespace(
        beams={
            "pile": np.array([[[0.0, 0.0, -4.0], [0.0, 0.0, 8.0]]]),
            "liner": np.array([[[0.0, 0.0, np.nan], [0.0, 0.0, -3.0]]]),
        },
        bars={"bolt": np.array([np.nan, -12.0, 5.0])},
    )
    result = AUDIT["support_force_metrics"](stage)
    assert result == {
        "beam_moments": {"liner": 3.0, "pile": 8.0},
        "bar_axial_forces": {"bolt": 12.0},
    }


def test_support_comparison_preserves_activation_and_missing_tags():
    data = [
        {"stage": "Head", "h_m": 2.0, "supports": {
            "beam_moments": {"liner": 10.0}, "bar_axial_forces": {},
        }},
        {"stage": "Head", "h_m": 1.0, "supports": {
            "beam_moments": {"liner": 11.0}, "bar_axial_forces": {"bolt": 5.0},
        }},
        {"stage": "Head", "h_m": 0.5, "supports": {
            "beam_moments": {"liner": 11.5}, "bar_axial_forces": {"bolt": 4.5},
        }},
    ]
    result = AUDIT["compare_supports_by_stage"](data)
    liner = [row for row in result if row["tag"] == "liner"]
    bolt = [row for row in result if row["tag"] == "bolt"]
    assert [x["relative_change"] for x in liner] == pytest.approx(
        [1.0 / 11.0, 0.5 / 11.5]
    )
    assert bolt[0]["status"] == "missing"
    assert bolt[0]["relative_change"] is None
    assert bolt[1]["relative_change"] == pytest.approx(0.5 / 5.0)


def test_stage_support_profiles_compare_componentwise_and_detect_missing():
    profile = {
        "tag": "pile", "kind": "beam", "s": [0., 1.],
        "components": [[1., 2., 3.], [2., 3., 4.]],
    }
    data = [
        {"stage": "Lift 1", "h_m": 2.0, "profiles": {"pile": profile}},
        {"stage": "Lift 1", "h_m": 1.0, "profiles": {"pile": profile}},
        {"stage": "Lift 1", "h_m": 0.5, "profiles": {}},
    ]
    compared = AUDIT["compare_stage_profiles"](data)
    assert compared[0]["status"] == "compared"
    assert compared[0]["relative_rms_components"] == pytest.approx([0., 0., 0.])
    assert compared[1]["status"] == "missing"
    assert compared[1]["relative_rms_components"] is None


def test_signed_stage_mesh_comparisons_use_separate_profile_field():
    signed = {
        "tag": "pile", "kind": "beam", "mode": "signed_local",
        "s": [0., 1.], "components": [[-2., 0., -4.], [-2., 0., -1.]],
    }
    entries = [
        {"stage": "Lift", "h_m": 2., "signed_profiles": {"pile": signed}},
        {"stage": "Lift", "h_m": 1., "signed_profiles": {"pile": signed}},
    ]
    result = AUDIT["compare_stage_profiles"](entries, field="signed_profiles")
    assert len(result) == 1
    assert result[0]["relative_rms_components"] == pytest.approx([0., 0., 0.])

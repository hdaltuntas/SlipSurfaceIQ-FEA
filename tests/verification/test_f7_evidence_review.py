"""Test F7 evidence reporting without requiring native FEM or desktop dependencies."""

from __future__ import annotations

import runpy
from pathlib import Path

_MODULE = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "scripts" / "f7_evidence_review.py")
)
summarize = _MODULE["summarize"]
markdown = _MODULE["markdown"]


def sample():
    return {
        "mesh_sizes_m": [2.5, 1.8, 1.2],
        "mesh_stage_coverage": {"complete": True, "expected_rows": 3},
        "results": [{"stage": "pile", "h_m": h} for h in (2.5, 1.8, 1.2)],
        "failures": [],
        "force_balance_acceptance": {
            "gravity_balance": {"passed": 3, "failed": 0, "unsupported": 0},
            "excavation_balance": {"passed": 0, "failed": 0, "unsupported": 3},
        },
        "excavation_balance": [
            {"status": "unsupported", "reason": "coupled force budget"}
            for _ in range(3)
        ],
        "mesh_sensitivity_diagnostics": {
            "metrics": [
                {
                    "status": "compared", "stage": "pile", "kind": "beam_moments",
                    "tag": "cad_Pile", "finest_pair_relative_change": 0.47,
                    "values": [
                        {"h_m": 2.5, "value": 0.09},
                        {"h_m": 1.8, "value": 0.05},
                        {"h_m": 1.2, "value": 0.10},
                    ],
                }
            ]
        },
        "profile_comparisons": [
            {"status": "compared", "stage": "pile", "h_m": 1.2,
             "tag": "cad_Pile", "relative_rms_components": [0.1, 0.9, 0.8]}
        ],
    }


def test_unsupported_force_checks_are_not_reported_as_validation():
    result = summarize(sample())
    assert result["physical_validation"] == "not_established"
    assert result["balance_status"]["excavation_balance"]["unsupported"] == 3
    assert result["unsupported_reasons"] == [
        {"check": "excavation_balance", "reason": "coupled force budget", "count": 3}
    ]
    assert "not established" in markdown(result)


def test_large_initial_peak_change_is_review_only():
    result = summarize(sample())
    assert result["review_priorities"][0]["type"] == "review_peak_mesh_change"
    assert result["review_priorities"][0]["maximum_reported_peak"] == 0.10
    assert "not pass/fail" in markdown(result)


def test_incomplete_metric_is_visible_without_fabricated_values():
    data = sample()
    data["mesh_sensitivity_diagnostics"]["metrics"][0] = {
        "status": "incomplete", "stage": "pile",
        "kind": "beam_moments", "tag": "cad_Pile",
    }
    result = summarize(data)
    assert result["review_priorities"][0]["type"] == "incomplete_metric"
    assert "47.00%" not in markdown(result)


def test_no_metric_does_not_imply_physical_validation():
    data = sample()
    data["mesh_sensitivity_diagnostics"] = {"metrics": []}
    result = summarize(data)
    assert result["physical_validation"] == "not_established"
    assert result["review_priorities"] == []

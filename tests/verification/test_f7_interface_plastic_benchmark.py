"""Independent zero-friction Goodman shear and opening reference."""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

_MOD = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "scripts"
        / "f7_interface_plastic_benchmark.py")
)
reference = _MOD["reference"]
run_benchmark = _MOD["run_benchmark"]


def test_closed_form_shear_positive_negative_and_tension():
    assert reference(1000, 2000, 5, 1, 0.012, -0.002)["traction"] == (5, -4)
    assert reference(1000, 2000, 5, 1, -0.012, -0.002)["traction"] == (-5, -4)
    assert reference(1000, 2000, 5, 1, 0, 0.002)["traction"] == (0, 1)


def test_simultaneous_shear_and_tensile_cap():
    result = reference(1000, 2000, 5, 1, 0.012, 0.002)
    assert result["traction"] == (5, 1)
    assert result["tangent"] == (0, 0)
    assert result["flag"] == 2


@pytest.mark.parametrize("length", [2.0, 4.0, 8.0])
def test_native_interface_matches_analytical_yield_and_nodal_forces(length):
    report = run_benchmark(length=length)
    assert report["all_flags_match"]
    assert report["maximum_relative_error"] <= 1e-9
    assert len(report["results"]) == 6
    assert all(row["relative_error"] <= 1e-9 for row in report["results"])


def test_yield_cases_show_zero_local_tangent():
    report = run_benchmark()
    found = {r["case"]: r for r in report["results"]}
    assert found["positive_shear_yield"]["analytical_flag"] == 1
    assert found["opening_tensile_cap"]["analytical_flag"] == 2
    assert found["simultaneous_shear_opening"]["analytical_flag"] == 2


def test_zero_strength_and_tensile_cutoff_reference():
    out = reference(1000, 2000, 0, 0, 0.01, 0.01)
    assert out["traction"] == (0, 0)
    assert out["tangent"] == (0, 0)


def test_invalid_reference_inputs_fail_closed():
    with pytest.raises(ValueError, match="finite"):
        reference(1000, 2000, 5, 1, float("nan"), 0)
    with pytest.raises(ValueError, match="negative"):
        reference(1000, 2000, -1, 1, 0, 0)
    with pytest.raises(ValueError, match="positive"):
        reference(0, 2000, 5, 1, 0, 0)

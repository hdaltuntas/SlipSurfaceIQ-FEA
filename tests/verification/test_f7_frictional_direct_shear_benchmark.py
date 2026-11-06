"""Analytical direct-shear tests independent of active-set constitutive solver."""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

_MODULE = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "scripts"
        / "f7_frictional_direct_shear_benchmark.py")
)
analytical_direct_shear = _MODULE["analytical_direct_shear"]
run_benchmark = _MODULE["run_benchmark"]


def test_frictional_strength_depends_on_compression():
    weak = analytical_direct_shear(1000, 2000, 5, 30, 0.04, -0.002)
    strong = analytical_direct_shear(1000, 2000, 5, 30, 0.04, -0.01)
    assert strong["shear_strength"] > weak["shear_strength"]
    assert strong["traction"][0] > weak["traction"][0]


def test_negative_shear_and_consistent_tangent_coupling():
    result = analytical_direct_shear(1000, 2000, 5, 30, -0.04, -0.01)
    assert result["yielded"]
    assert result["traction"][0] < 0
    assert result["tangent"][0][1] > 0


@pytest.mark.parametrize("length", [1.0, 4.0, 8.0])
@pytest.mark.parametrize("friction", [0.0, 20.0, 35.0])
def test_native_interface_matches_closed_form(length, friction):
    report = run_benchmark(length=length, friction_deg=friction)
    assert report["all_flags_match"]
    assert report["maximum_normalized_error"] <= 1e-9
    assert len(report["results"]) == 3


def test_elastic_and_both_shear_directions():
    report = run_benchmark()
    assert [item["analytical"]["flag"] for item in report["results"]] == [0, 1, 1]
    assert all(item["flag_matches"] for item in report["results"])


@pytest.mark.parametrize("bad", [
    {"compressive_jump": 0.0},
    {"compressive_jump": 0.002},
    {"length": 0.0},
])
def test_unsupported_or_invalid_geometry_rejected(bad):
    with pytest.raises(ValueError):
        run_benchmark(**bad)


def test_invalid_reference_inputs_rejected():
    with pytest.raises(ValueError, match="compression"):
        analytical_direct_shear(1000, 2000, 5, 30, 0.04, 0.0)
    with pytest.raises(ValueError, match="compression"):
        analytical_direct_shear(1000, 2000, -1, 30, 0.04, -0.01)

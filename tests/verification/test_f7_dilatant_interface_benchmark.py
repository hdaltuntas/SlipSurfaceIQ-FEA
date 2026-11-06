"""Closed-form dilatant/multisurface interface reference, independent of the return solver."""

from __future__ import annotations

import json
import math
import runpy
import sys
from pathlib import Path

import numpy as np
import pytest

from slipsurface.fe2d.fem.structural import InterfaceGroup

_MODULE = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "scripts" / "f7_dilatant_interface_benchmark.py")
)
closed_form = _MODULE["closed_form"]
run_benchmark = _MODULE["run_benchmark"]
run_case = _MODULE["run_case"]
benchmark_cases = _MODULE["benchmark_cases"]
main = _MODULE["main"]
PARAMETERS = dict(ks=100.0, kn=200.0, cohesion=2.0,
                  phi=math.degrees(math.atan(0.5)), psi=math.degrees(math.atan(0.25)),
                  tensile_cap=1.0)


def test_scalar_consistency_reference_has_hand_calculated_values():
    result = closed_form((10.0, -2.0), branch="shear", **PARAMETERS)
    assert result["multipliers"]["shear"] == pytest.approx(0.056)
    np.testing.assert_allclose(result["traction"], [4.4, -4.8], atol=1e-13)
    np.testing.assert_allclose(result["tangent"], [[20.0, -80.0], [-40.0, 160.0]])
    assert result["flag"] == 1


def test_negative_shear_flips_cross_terms_not_normal_correction():
    result = closed_form((-10.0, -2.0), branch="shear", sign=-1, **PARAMETERS)
    np.testing.assert_allclose(result["traction"], [-4.4, -4.8], atol=1e-13)
    np.testing.assert_allclose(result["tangent"], [[20.0, 80.0], [40.0, 160.0]])


def test_shear_tension_corner_has_two_positive_multipliers():
    result = closed_form((10.0, 10.0), branch="corner", **PARAMETERS)
    np.testing.assert_allclose(result["traction"], [1.5, 1.0])
    assert result["multipliers"] == pytest.approx({"shear": 0.085, "tension": 0.02375})
    np.testing.assert_array_equal(result["tangent"], np.zeros((2, 2)))
    assert result["flag"] == 2


def test_apex_has_closed_form_value_and_zero_tangent():
    args = {**PARAMETERS, "tensile_cap": 10.0}
    result = closed_form((1.0, 10.0), branch="apex", **args)
    np.testing.assert_allclose(result["traction"], [0.0, 4.0], atol=1e-13)
    assert result["multipliers"] == pytest.approx(
        {"positive_shear": 0.065, "negative_shear": 0.055}
    )
    np.testing.assert_array_equal(result["tangent"], np.zeros((2, 2)))
    assert result["flag"] == 3


def test_tensile_trial_can_return_to_compressive_shear():
    case = next(x for x in benchmark_cases()
                if x["name"] == "tensile_trial_returns_to_compression")
    args = {k: v for k, v in case.items() if k not in ("name", "trial")}
    reference = closed_form(case["trial"], **args)
    assert case["trial"][1] > case["tensile_cap"]
    assert reference["traction"][1] < 0
    assert reference["flag"] == 1


def test_associated_tangent_is_symmetric_but_nonassociated_is_not():
    nonassociated = closed_form((10.0, -2.0), branch="shear", **PARAMETERS)
    args = {**PARAMETERS, "psi": PARAMETERS["phi"]}
    associated = closed_form((10.0, -2.0), branch="shear", **args)
    a, b = np.array(associated["tangent"]), np.array(nonassociated["tangent"])
    np.testing.assert_allclose(a, a.T)
    assert not np.allclose(b, b.T)


@pytest.mark.parametrize("element_type", ["IFACE4", "IFACE6"])
@pytest.mark.parametrize("length", [1.0, 4.0, 8.0])
@pytest.mark.parametrize("angle_deg", [0.0, 37.0, -63.0])
def test_native_interface_matches_reference_and_full_finite_difference(
    element_type, length, angle_deg
):
    report = run_benchmark(element_type=element_type, length=length, angle_deg=angle_deg)
    assert report["status"] == "passed", report
    assert report["case_count"] == 11
    assert all(row["committed_state_unchanged"] for row in report["results"])
    assert all(row["flags_match"] for row in report["results"])
    assert all(check["status"] == "passed" for row in report["results"]
               for check in row["checks"].values())


@pytest.mark.parametrize("fault", ["traction", "force", "tangent", "flag", "state", "nan"])
def test_corrupted_native_results_cannot_produce_pass(monkeypatch, fault):
    original_integrate = InterfaceGroup.integrate

    def corrupted(self, state, ids, du, p):
        result, force, tangent, flags = original_integrate(self, state, ids, du, p)
        if fault == "traction":
            result["t"][0, 0, 0] += 1.0
        elif fault == "force":
            force[0, 0] += 1.0
        elif fault == "tangent":
            tangent[0, 0, 0] += 1.0
        elif fault == "flag":
            flags[:] = 0
        elif fault == "state":
            state["t"][0, 0, 0] += 1.0
        else:
            tangent[0, 0, 0] = np.nan
        return result, force, tangent, flags

    monkeypatch.setattr(InterfaceGroup, "integrate", corrupted)
    result = run_case(benchmark_cases()[1])
    assert result["status"] == "failed"


@pytest.mark.parametrize("changes", [
    {"ks": 0.0}, {"kn": -1.0}, {"cohesion": -1.0}, {"phi": 90.0},
    {"psi": 40.0}, {"tensile_cap": -1.0}, {"ks": float("nan")}, {"kn": True},
])
def test_invalid_reference_properties_rejected(changes):
    with pytest.raises(ValueError):
        closed_form((10.0, -2.0), branch="shear", **{**PARAMETERS, **changes})


@pytest.mark.parametrize("branch,trial", [
    ("unknown", (1.0, -2.0)), ("elastic", (10.0, -2.0)),
    ("shear", (1.0, -2.0)), ("shear", (3.0, -2.0)),
    ("corner", (10.0, -2.0)), ("apex", (1.0, 10.0)),
])
def test_wrong_branch_and_switching_points_rejected(branch, trial):
    with pytest.raises(ValueError):
        closed_form(trial, branch=branch, **PARAMETERS)


@pytest.mark.parametrize("kwargs", [
    {"length": 0.0}, {"length": float("inf")}, {"angle_deg": float("nan")},
    {"element_type": "BAR2"},
])
def test_invalid_geometry_rejected(kwargs):
    with pytest.raises(ValueError):
        run_case(benchmark_cases()[0], **kwargs)


def test_cli_writes_strict_json_and_propagates_failed_case(monkeypatch, tmp_path):
    output = tmp_path / "failure.json"
    monkeypatch.setattr(sys, "argv", ["benchmark", "--output", str(output)])
    monkeypatch.setitem(main.__globals__, "run_benchmark",
                        lambda **kwargs: {"status": "failed", "case_count": 1, "results": []})
    assert main() == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert report["case_count"] == 6

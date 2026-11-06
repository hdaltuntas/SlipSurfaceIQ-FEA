"""Independent elastic interface benchmark: uniform relative displacements."""

from __future__ import annotations

import runpy
from pathlib import Path

import numpy as np
import pytest

_MODULE = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "scripts"
        / "f7_interface_elastic_benchmark.py")
)
run_benchmark = _MODULE["run_benchmark"]
analytical_uniform_jump = _MODULE["analytical_uniform_jump"]


@pytest.mark.parametrize("length", [1.0, 4.0, 8.0])
@pytest.mark.parametrize("jump", [(0.002, -0.001), (-0.001, -0.002), (0.0, -0.003)])
def test_independent_traction_and_force_transfer(length, jump):
    result = run_benchmark(
        length=length, tangential_jump=jump[0], normal_jump=jump[1]
    )
    assert result["maximum_normalized_error"] <= 1e-9
    assert result["plastic_flags"] == [0, 0]
    assert result["face_reciprocity_error"] == pytest.approx(0.0)
    assert np.asarray(result["observed_nodal_forces"]).sum(axis=0) == pytest.approx(
        [0.0, 0.0]
    )


def test_pure_shear_has_no_normal_traction():
    result = run_benchmark(tangential_jump=0.003, normal_jump=0.0)
    assert np.asarray(result["observed_local_traction"])[:, 1] == pytest.approx(
        [0.0, 0.0]
    )
    assert result["maximum_normalized_error"] <= 1e-9


def test_pure_compression_has_no_shear_traction():
    result = run_benchmark(tangential_jump=0.0, normal_jump=-0.004)
    assert np.asarray(result["observed_local_traction"])[:, 0] == pytest.approx(
        [0.0, 0.0]
    )
    assert result["maximum_normalized_error"] <= 1e-9


def test_stiffness_scaling_changes_analytical_resultant():
    a, f = analytical_uniform_jump(4.0, 1000.0, 2000.0, 0.001, -0.001)
    b, g = analytical_uniform_jump(4.0, 2000.0, 4000.0, 0.001, -0.001)
    assert b == pytest.approx(2 * a)
    assert g == pytest.approx(2 * f)


def test_invalid_geometry_or_stiffness_rejected():
    with pytest.raises(ValueError, match="Invalid"):
        analytical_uniform_jump(0.0, 1000.0, 2000.0, 0.001, 0.0)
    with pytest.raises(ValueError, match="Invalid"):
        analytical_uniform_jump(2.0, -1.0, 2000.0, 0.001, 0.0)


def test_nonfinite_jump_rejected():
    with pytest.raises(ValueError, match="Invalid"):
        analytical_uniform_jump(2.0, 1000.0, 2000.0, float("nan"), 0.0)

"""Analytical cantilever checks with no staged soil/structure coupling."""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

_MOD = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "scripts"
        / "f7_cantilever_beam_benchmark.py")
)
run_benchmark = _MOD["run_benchmark"]
cantilever_reference = _MOD["cantilever_reference"]


@pytest.mark.parametrize("length", [2.0, 6.0, 12.0])
@pytest.mark.parametrize("shear_area", [0.0, 0.15, 0.5])
def test_closed_form_timoshenko_tip_and_reactions(length, shear_area):
    result = run_benchmark(length=length, shear_area=shear_area)
    assert result["maximum_relative_error"] < 1e-9
    assert result["checks"]["root_moment_knm_per_m"]["analytical"] == (
        pytest.approx(35.0 * length)
    )


def test_zero_transverse_load_is_pure_axial():
    result = run_benchmark(axial=40.0, transverse=0.0)
    assert result["maximum_relative_error"] < 1e-9
    assert result["checks"]["tip_uy_m"]["observed"] == pytest.approx(0.0)
    assert result["checks"]["root_rx_kn_per_m"]["observed"] == pytest.approx(-40.0)


def test_zero_axial_load_is_pure_bending_and_shear():
    result = run_benchmark(axial=0.0, transverse=15.0)
    assert result["maximum_relative_error"] < 1e-9
    assert result["checks"]["tip_ux_m"]["observed"] == pytest.approx(0.0)


def test_shear_deformation_increases_tip_deflection():
    flexible = run_benchmark(shear_area=0.08, transverse=20.0)
    shear_rigid = run_benchmark(shear_area=0.0, transverse=20.0)
    assert (flexible["checks"]["tip_uy_m"]["observed"]
            > shear_rigid["checks"]["tip_uy_m"]["observed"])


def test_invalid_length_or_force_rejected():
    from slipsurface.fe2d.model.materials import LinerSpec

    spec = LinerSpec(
        "cantilever", E=30_000_000.0, nu=0.2,
        A=0.3, I=0.00225, As=0.2,
    )
    with pytest.raises(ValueError, match="Length"):
        cantilever_reference(-1.0, spec, 1.0, 2.0)
    with pytest.raises(ValueError, match="Forces"):
        cantilever_reference(3.0, spec, float("nan"), 2.0)

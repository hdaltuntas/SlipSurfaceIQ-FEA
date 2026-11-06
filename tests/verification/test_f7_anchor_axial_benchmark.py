"""Independent BAR2 axial law and reaction benchmark regressions."""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

_MODULE = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "scripts"
        / "f7_anchor_axial_benchmark.py")
)
run_benchmark = _MODULE["run_benchmark"]
analytical_force = _MODULE["analytical_force"]


@pytest.mark.parametrize("length", [2.0, 5.0, 10.0])
@pytest.mark.parametrize("spacing", [1.0, 2.0])
def test_axial_force_and_yield_across_lengths_and_spacing(length, spacing):
    report = run_benchmark(length=length, spacing=spacing)
    assert report["yield_flags_match"]
    assert report["maximum_relative_error"] < 1e-9


def test_prestress_present_at_zero_displacement():
    report = run_benchmark(displacements=(0.0,))
    point = report["observations"][0]
    assert point["observed_force_kn_per_m"] == pytest.approx(20.0)
    assert point["root_reaction_kn_per_m"] == pytest.approx(-20.0)


def test_positive_and_negative_plastic_plateaus():
    report = run_benchmark(displacements=(-0.04, 0.04))
    a, b = report["observations"]
    assert a["observed_force_kn_per_m"] == pytest.approx(-60.0)
    assert b["observed_force_kn_per_m"] == pytest.approx(60.0)
    assert a["observed_yielded"] and b["observed_yielded"]


def test_elastic_tangent_and_softened_yield_tangent():
    report = run_benchmark(displacements=(0.0, 0.04))
    elastic, plastic = report["observations"]
    assert elastic["observed_axial_tangent"] == pytest.approx(10000.0)
    assert 0 < plastic["observed_axial_tangent"] < elastic["observed_axial_tangent"]


def test_invalid_displacement_is_not_silently_accepted():
    with pytest.raises(ValueError, match="finite"):
        run_benchmark(displacements=(float("nan"),))


def test_analytical_invalid_length_rejected():
    from slipsurface.fe2d.model.materials import BoltSpec

    spec = BoltSpec("bar", EA=1000.0, T_yield=100.0)
    with pytest.raises(ValueError, match="Length"):
        analytical_force(0.0, spec, 0.001)

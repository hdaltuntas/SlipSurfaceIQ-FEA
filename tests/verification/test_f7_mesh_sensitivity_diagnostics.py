"""F7 mesh sensitivity diagnostics never turn peak agreement into validation."""

import pytest

from slipsurface.fe2d.post.mesh_sensitivity_diagnostics import (
    mesh_sensitivity_diagnostics,
)


SIZES = (2.5, 1.8, 1.2)


def rows():
    return [
        {"h_m": h, "stage": "lift_1",
         "max_displacement_m": u,
         "supports": {"beam_moments": {"pile": moment},
                      "bar_axial_forces": {"anchor": force}}}
        for h, u, moment, force in zip(
            SIZES, (0.10, 0.08, 0.075), (12., 10., 9.5), (0., 7., 8.)
        )
    ]


def test_three_mesh_diagnostics_are_not_acceptance():
    report = mesh_sensitivity_diagnostics(rows(), SIZES, ("lift_1",))
    assert report["status"] == "diagnostic_only"
    displacement = next(x for x in report["metrics"]
                        if x["kind"] == "displacement")
    assert displacement["finest_pair_relative_change"] == pytest.approx(0.0625)
    assert "pass" not in displacement
    assert any(x["kind"] == "beam_moments" for x in report["metrics"])


def test_missing_mesh_is_incomplete_not_zero():
    report = mesh_sensitivity_diagnostics(rows()[:2], SIZES, ("lift_1",))
    assert report["status"] == "incomplete"
    displacement = next(x for x in report["metrics"]
                        if x["kind"] == "displacement")
    assert displacement["values"][-1]["value"] is None
    assert displacement["finest_pair_relative_change"] is None


def test_nonfinite_active_peak_cannot_be_compared():
    data = rows()
    data[-1]["supports"]["beam_moments"]["pile"] = float("nan")
    report = mesh_sensitivity_diagnostics(data, SIZES, ("lift_1",))
    assert report["status"] == "incomplete"
    beam = next(x for x in report["metrics"] if x["kind"] == "beam_moments")
    assert beam["status"] == "incomplete"


def test_unequal_support_tags_cannot_silently_compare():
    data = rows()
    del data[-1]["supports"]["bar_axial_forces"]["anchor"]
    report = mesh_sensitivity_diagnostics(data, SIZES, ("lift_1",))
    assert report["status"] == "incomplete"


def test_invalid_mesh_order_is_rejected():
    with pytest.raises(ValueError, match="coarse-to-fine"):
        mesh_sensitivity_diagnostics(rows(), (1.2, 1.8, 2.5), ("lift_1",))


def test_duplicate_stage_rows_are_rejected():
    data = rows()
    data.append(dict(data[0]))
    report = mesh_sensitivity_diagnostics(data, SIZES, ("lift_1",))
    assert report["status"] == "incomplete"
    assert any(x["kind"] == "data_quality" for x in report["metrics"])

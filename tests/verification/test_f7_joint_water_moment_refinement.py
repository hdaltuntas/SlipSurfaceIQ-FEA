"""F7 independent force and first-moment mesh convergence for IFACE4/6."""

from __future__ import annotations

import pytest

from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.model.materials import InterfaceSpec
from slipsurface.fe2d.post.joint_water_moment_refinement import (
    joint_water_moment_refinement,
    segmented_vertical_joint,
)

SPEC = InterfaceSpec("joint", 1e6, 1e5)


@pytest.mark.parametrize("reverse", [False, True])
def test_linear_interface_exact_force_but_moment_error_refines(reverse):
    report = joint_water_moment_refinement(
        SPEC, (1, 2, 4), etype=ElemType.IFACE4, reverse=reverse,
    )
    assert abs(report["reference_force_kn_per_m"]) == pytest.approx(78.48)
    assert abs(report["reference_moment_knm_per_m"]) == pytest.approx(209.28)
    assert report["moment_error_nonincreasing"]
    assert [row["force_status"] for row in report["rows"]] == [
        "passed", "passed", "passed",
    ]
    errors = [abs(row["moment_error_knm_per_m"]) for row in report["rows"]]
    assert errors[0] > errors[1] > errors[2] > 0
    # Composite trapezoidal integration of linear p(y), weighted by y,
    # has second-order moment error for uniform straight segments.
    assert errors[0] / errors[1] == pytest.approx(4.0, rel=1e-10)
    assert errors[1] / errors[2] == pytest.approx(4.0, rel=1e-10)
    assert not report["finest_moment_passed"]


@pytest.mark.parametrize("reverse", [False, True])
def test_quadratic_interface_linear_pressure_is_exact_at_every_resolution(reverse):
    report = joint_water_moment_refinement(
        SPEC, (1, 2, 4), etype=ElemType.IFACE6, reverse=reverse,
    )
    assert report["finest_both_passed"]
    assert report["moment_error_nonincreasing"]
    assert all(row["both_passed"] for row in report["rows"])
    assert all(abs(row["moment_error_knm_per_m"]) < 1e-9 for row in report["rows"])
    assert all(row["reference_pressure_center_y_m"] == pytest.approx(-8 / 3)
               for row in report["rows"])


def test_water_table_kink_at_coarse_mesh_fails_then_aligned_mesh_passes():
    report = joint_water_moment_refinement(
        SPEC, (1, 2, 4), etype=ElemType.IFACE6, head=-2.,
    )
    assert report["rows"][0]["force_status"] == "failed"
    assert not report["rows"][0]["both_passed"]
    assert report["rows"][1]["both_passed"]
    assert report["rows"][2]["both_passed"]
    assert report["reference_force_kn_per_m"] == pytest.approx(-19.62)


def test_mesh_connectivity_and_resolutions_are_preserved():
    mesh = segmented_vertical_joint(4, etype=ElemType.IFACE6)
    block = mesh.block("joint")
    # The second element shares its endpoint IDs on both faces with the first.
    assert block.conn[0, 1] == block.conn[1, 0]
    assert block.conn[0, 4] == block.conn[1, 3]
    assert block.conn[0, 1] != block.conn[0, 4]
    with pytest.raises(ValueError, match="strictly increasing"):
        joint_water_moment_refinement(SPEC, (2, 2))
    with pytest.raises(ValueError, match="positive integer"):
        segmented_vertical_joint(0)

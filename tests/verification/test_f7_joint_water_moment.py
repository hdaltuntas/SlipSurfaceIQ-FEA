"""F7 hydrostatic force can pass while its application moment is wrong."""

from __future__ import annotations

import json

import numpy as np
import pytest

from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.model.materials import InterfaceSpec
from slipsurface.fe2d.model.mesh import ElementBlock, Mesh
from slipsurface.fe2d.post.joint_water_moment import vertical_joint_water_moment

SPEC = InterfaceSpec("joint", 1e6, 1e5)


def wall(etype, *, reverse=False, head_top=0.):
    """One vertical 4 m segment, with duplicated opposite-side coordinates."""
    a, b = ((head_top, head_top - 4.) if not reverse
            else (head_top - 4., head_top))
    elev = [a, b]
    if etype is ElemType.IFACE6:
        elev.append((a + b) / 2.)
    face = np.array([[0., y] for y in elev])
    coords = np.vstack((face, face))
    return Mesh(
        coords,
        (ElementBlock(
            etype, np.arange(2 * len(elev))[None, :],
            np.ones(1, dtype=int), "joint",
        ),),
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_quadratic_interface_linear_pressure_has_exact_force_and_moment(reverse):
    mesh = wall(ElemType.IFACE6, reverse=reverse)
    result = vertical_joint_water_moment(mesh, "joint", SPEC, head=0.)
    assert result["both_passed"]
    assert result["force_status"] == "passed"
    assert result["status"] == "passed"
    assert abs(result["reference_force_kn_per_m"]) == pytest.approx(78.48)
    assert abs(result["reference_moment_knm_per_m"]) == pytest.approx(209.28)
    assert result["assembled_moment_knm_per_m"] == pytest.approx(
        result["reference_moment_knm_per_m"], rel=1e-12,
    )
    assert result["reference_pressure_center_y_m"] == pytest.approx(-8. / 3.)
    assert result["assembled_pressure_center_y_m"] == pytest.approx(-8. / 3.)
    json.dumps(result, allow_nan=False)


def test_linear_joint_force_correct_but_pressure_center_incorrect():
    mesh = wall(ElemType.IFACE4)
    result = vertical_joint_water_moment(mesh, "joint", SPEC, head=0.)
    # Trapezoidal integration gets the force of linear p(y) exactly, but
    # nodal lumping cannot reproduce the first moment of y*p(y) exactly.
    assert result["force_status"] == "passed"
    assert result["status"] == "failed"
    assert not result["both_passed"]
    assert result["reference_pressure_center_y_m"] == pytest.approx(-8. / 3.)
    assert result["assembled_pressure_center_y_m"] == pytest.approx(-4.)
    assert abs(result["moment_error_knm_per_m"]) > 100.


def test_dry_joint_has_zero_moment_and_no_pressure_center():
    mesh = wall(ElemType.IFACE6)
    result = vertical_joint_water_moment(mesh, "joint", SPEC, head=-5.)
    assert result["both_passed"]
    assert result["reference_force_kn_per_m"] == pytest.approx(0.)
    assert result["assembled_moment_knm_per_m"] == pytest.approx(0.)
    assert result["reference_pressure_center_y_m"] is None
    assert result["assembled_pressure_center_y_m"] is None


def test_pressure_center_shifts_with_vertical_datum():
    mesh = wall(ElemType.IFACE6, head_top=3.)
    result = vertical_joint_water_moment(mesh, "joint", SPEC, head=3.)
    assert result["both_passed"]
    assert result["reference_pressure_center_y_m"] == pytest.approx(3. - 8. / 3.)


def test_water_table_inside_quadratic_joint_fails_physical_force_gate():
    mesh = wall(ElemType.IFACE6)
    result = vertical_joint_water_moment(mesh, "joint", SPEC, head=-2.)
    assert result["force_status"] == "failed"
    assert not result["both_passed"]

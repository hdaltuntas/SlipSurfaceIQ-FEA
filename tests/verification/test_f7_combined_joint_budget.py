"""F7 independent combined effective-traction and water moment gates."""

from __future__ import annotations

import numpy as np
import pytest

from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.model.materials import InterfaceSpec
from slipsurface.fe2d.model.mesh import ElementBlock, Mesh
from slipsurface.fe2d.post.combined_joint_budget import combined_joint_force_moment

SPEC = InterfaceSpec("joint", 1e6, 1e5)


def interface(etype, *, reversed_direction=False):
    y0, y1 = (0., -4.) if not reversed_direction else (-4., 0.)
    elevations = [y0, y1]
    if etype is ElemType.IFACE6:
        elevations.append(0.5 * (y0 + y1))
    face = [[0., y] for y in elevations]
    nodes = np.array(face + face, dtype=float)
    conn = np.arange(len(nodes))[None]
    mesh = Mesh(
        nodes,
        (ElementBlock(etype, conn, np.ones(1, dtype=int), "joint"),),
    )
    return mesh, np.array([[[2., -3.]] * len(elevations)])


@pytest.mark.parametrize("reversed_direction", [False, True])
def test_quadratic_joint_combined_traction_and_water_passes(reversed_direction):
    mesh, t = interface(ElemType.IFACE6, reversed_direction=reversed_direction)
    out = combined_joint_force_moment(mesh, "joint", SPEC, t, 0.)
    assert out["status"] == "passed"
    assert out["all_passed"]
    assert out["hydrostatic_force_status"] == "passed"
    assert out["hydrostatic_moment_status"] == "passed"
    assert out["opposite_face_force_residual_kn_per_m"] < 1e-10
    assert out["opposite_face_moment_residual_knm_per_m"] < 1e-10
    assert out["force_error_kn_per_m"] < 1e-10
    assert out["moment_error_knm_per_m"] < 1e-10
    assert abs(out["water_reference_force_kn_per_m"]) == pytest.approx(78.48)
    assert abs(out["water_reference_moment_knm_per_m"]) == pytest.approx(209.28)


def test_linear_joint_combined_total_force_cannot_hide_water_moment_error():
    mesh, t = interface(ElemType.IFACE4)
    out = combined_joint_force_moment(mesh, "joint", SPEC, t, 0.)
    assert out["hydrostatic_force_status"] == "passed"
    assert out["hydrostatic_moment_status"] == "failed"
    assert out["status"] == "failed"
    assert not out["all_passed"]
    assert out["force_error_kn_per_m"] < 1e-10
    assert out["moment_error_knm_per_m"] > 100.
    assert out["opposite_face_force_residual_kn_per_m"] < 1e-10
    assert out["opposite_face_moment_residual_knm_per_m"] < 1e-10


def test_dry_interface_effective_traction_only_is_consistent():
    mesh, t = interface(ElemType.IFACE4)
    out = combined_joint_force_moment(mesh, "joint", SPEC, t, -5.)
    assert out["all_passed"]
    assert out["water_reference_force_kn_per_m"] == 0.
    assert out["water_reference_moment_knm_per_m"] == 0.
    assert out["expected_face2_fx_kn_per_m"] == pytest.approx(
        out["assembled_face2_fx_kn_per_m"]
    )
    assert out["expected_face2_moment_knm_per_m"] == pytest.approx(
        out["assembled_face2_moment_knm_per_m"]
    )


def test_water_table_inside_joint_fails_even_when_faces_balance():
    mesh, t = interface(ElemType.IFACE6)
    out = combined_joint_force_moment(mesh, "joint", SPEC, t, -2.)
    assert not out["all_passed"]
    assert out["hydrostatic_force_status"] == "failed"
    assert out["opposite_face_force_residual_kn_per_m"] < 1e-10


def test_inactive_or_invalid_traction_must_not_be_counted_as_zero():
    mesh, t = interface(ElemType.IFACE4)
    t[0, 0, 0] = np.nan
    with pytest.raises(ValueError, match="finite and active"):
        combined_joint_force_moment(mesh, "joint", SPEC, t, 0.)
    with pytest.raises(ValueError, match="finite and active"):
        combined_joint_force_moment(
            mesh, "joint", SPEC, np.zeros((1, 3, 2)), 0.
        )

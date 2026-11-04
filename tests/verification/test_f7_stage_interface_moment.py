"""F7 stage interface traction moment checks preserve signed force balance."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from slipsurface.fe2d.core.enums import Analysis, ElemType
from slipsurface.fe2d.model.materials import InterfaceSpec
from slipsurface.fe2d.model.mesh import ElementBlock, Mesh
from slipsurface.fe2d.post.stage_interface_moment import (
    effective_interface_moment_audit,
    stage_effective_interface_moment_audit,
)

SPEC = InterfaceSpec("joint", 1e6, 1e5)


def joint(etype, *, face_offset=0.):
    points = [[0., 0.], [0., -4.]]
    if etype is ElemType.IFACE6:
        points.append([0., -2.])
    opposite = [[face_offset, y] for _, y in points]
    coords = np.array(points + opposite)
    block = ElementBlock(
        etype, np.arange(len(coords))[None, :], np.ones(1, int), "joint"
    )
    return Mesh(coords, (block,))


@pytest.mark.parametrize("etype", [ElemType.IFACE4, ElemType.IFACE6])
def test_two_faces_have_equal_opposite_signed_force_and_moment(etype):
    mesh = joint(etype)
    npe = 2 if etype is ElemType.IFACE4 else 3
    traction = np.tile([2., -3.], (1, npe, 1))
    result = effective_interface_moment_audit(mesh, "joint", traction, SPEC)
    assert result["status"] == "passed"
    assert result["active_elements"] == 1
    assert result["action_reaction_force_error_kn_per_m"] < 1e-10
    assert result["action_reaction_moment_error_knm_per_m"] < 1e-10
    assert result["reference_moment_error_knm_per_m"] < 1e-10
    assert result["face1_moment_knm_per_m"] == pytest.approx(
        -result["face2_moment_knm_per_m"]
    )


def test_geometrically_separated_faces_do_not_fake_moment_reciprocity():
    mesh = joint(ElemType.IFACE4, face_offset=1.)
    traction = np.array([[[2., -3.], [2., -3.]]])
    result = effective_interface_moment_audit(mesh, "joint", traction, SPEC)
    assert result["action_reaction_force_error_kn_per_m"] < 1e-10
    assert result["action_reaction_moment_error_knm_per_m"] > 1.
    assert result["status"] == "failed"


def test_inactive_interface_reports_unsupported_not_passed():
    mesh = joint(ElemType.IFACE4)
    out = effective_interface_moment_audit(
        mesh, "joint", np.full((1, 2, 2), np.nan), SPEC
    )
    assert out["status"] == "unsupported"
    assert out["active_elements"] == 0


def test_partial_nonfinite_active_interface_is_rejected():
    mesh = joint(ElemType.IFACE4)
    t = np.zeros((1, 2, 2))
    t[0, 1, 0] = np.nan
    with pytest.raises(ValueError, match="Nonfinite active"):
        effective_interface_moment_audit(mesh, "joint", t, SPEC)


def test_stage_wrapper_reports_matching_structural_tag():
    mesh = joint(ElemType.IFACE6)
    model = SimpleNamespace(
        mesh=mesh, interfaces={"joint": SPEC},
        analysis=Analysis.PLANE_STRAIN,
    )
    stage = SimpleNamespace(interfaces={"joint": np.ones((1, 3, 2))})
    output = stage_effective_interface_moment_audit(model, stage)
    assert output["joint"]["status"] == "passed"
    assert output["joint"]["active_elements"] == 1

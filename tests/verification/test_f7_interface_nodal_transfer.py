"""F7: nodal assembly of IFACE4/IFACE6 traction and face force transfer."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from slipsurface.fe2d.core.enums import Analysis, ElemType
from slipsurface.fe2d.model.materials import InterfaceSpec
from slipsurface.fe2d.model.mesh import ElementBlock, Mesh
from slipsurface.fe2d.post.interface_nodal_audit import (
    interface_nodal_force_transfer,
    stage_interface_nodal_audit,
)


def mesh_with_interfaces(etype):
    if etype is ElemType.IFACE4:
        coords = np.array([
            [0., 0.], [2., 0.], [0., 0.], [2., 0.],
        ])
        conn = np.array([[0, 1, 2, 3]])
    else:
        coords = np.array([
            [0., 0.], [2., 0.], [1., 0.],
            [0., 0.], [2., 0.], [1., 0.],
        ])
        conn = np.array([[0, 1, 2, 3, 4, 5]])
    return Mesh(
        coords,
        (ElementBlock(etype, conn, np.array([1]), "joint"),),
    )


@pytest.mark.parametrize("etype", [ElemType.IFACE4, ElemType.IFACE6])
def test_global_nodal_assembly_has_exact_equal_opposite_face_forces(etype):
    mesh = mesh_with_interfaces(etype)
    spec = InterfaceSpec("joint", kn=1e6, ks=1e5)
    n_ip = 2 if etype is ElemType.IFACE4 else 3
    traction = np.tile(np.array([3.0, -5.0]), (1, n_ip, 1))
    result = interface_nodal_force_transfer(mesh, "joint", traction, spec)
    assert result["active_elements"] == 1
    assert result["face1_resultant"] == pytest.approx([-6., 10.], abs=1e-10)
    assert result["face2_resultant"] == pytest.approx([6., -10.], abs=1e-10)
    assert result["global_resultant"] == pytest.approx([0., 0.], abs=1e-10)
    assert result["face1_reference_error"] == pytest.approx([0., 0.], abs=1e-10)
    assert result["face2_reference_error"] == pytest.approx([0., 0.], abs=1e-10)
    assert result["nodal_forces"].shape == (mesh.nn, 2)
    assert np.all(np.isfinite(result["nodal_forces"]))


def test_inactive_interface_yields_zero_assembled_force_but_is_not_active():
    mesh = mesh_with_interfaces(ElemType.IFACE4)
    spec = InterfaceSpec("joint", kn=1e6, ks=1e5)
    result = interface_nodal_force_transfer(
        mesh, "joint", np.full((1, 2, 2), np.nan), spec
    )
    assert result["active_elements"] == 0
    assert np.all(result["nodal_forces"] == 0)
    assert np.all(result["global_resultant"] == 0)


def test_partial_nonfinite_and_wrong_shape_rejected():
    mesh = mesh_with_interfaces(ElemType.IFACE4)
    spec = InterfaceSpec("joint", kn=1e6, ks=1e5)
    with pytest.raises(ValueError, match="nonfinite active"):
        interface_nodal_force_transfer(
            mesh, "joint", np.array([[[2., 3.], [np.nan, 1.]]]), spec
        )
    with pytest.raises(ValueError, match="shape"):
        interface_nodal_force_transfer(mesh, "joint", np.zeros((1, 3, 2)), spec)


def test_stage_interface_audit_is_json_serializable_and_validates_specs():
    import json

    mesh = mesh_with_interfaces(ElemType.IFACE4)
    spec = InterfaceSpec("joint", kn=1e6, ks=1e5)
    stage = SimpleNamespace(
        interfaces={"joint": np.array([[[3., -5.], [3., -5.]]])}
    )
    model = SimpleNamespace(
        mesh=mesh, interfaces={"joint": spec}, analysis=Analysis.PLANE_STRAIN
    )
    result = stage_interface_nodal_audit(model, stage)
    assert result["joint"]["face2_fx"] == pytest.approx(6.)
    assert result["joint"]["global_residual_fx"] == pytest.approx(0., abs=1e-10)
    json.dumps(result, allow_nan=False)
    model.interfaces = {}
    with pytest.raises(ValueError, match="Missing interface properties"):
        stage_interface_nodal_audit(model, stage)

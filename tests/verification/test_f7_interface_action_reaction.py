"""F7: exact equal/opposite interface tractions in plane strain."""

from __future__ import annotations

import numpy as np
import pytest

from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.model.materials import InterfaceSpec
from slipsurface.fe2d.model.mesh import ElementBlock, Mesh
from slipsurface.fe2d.post.interface_balance import (
    interface_force_pair,
    stage_interface_pairs,
)


def sample_mesh():
    # Two faces coincide geometrically but remain separate nodal DOFs.
    return Mesh(
        np.array([[0., 0.], [2., 0.], [0., 0.], [2., 0.]]),
        (ElementBlock(
            ElemType.IFACE4, np.array([[0, 1, 2, 3]]),
            np.array([1]), "joint",
        ),),
    )


def test_constant_interface_traction_has_exact_opposite_face_resultants():
    mesh = sample_mesh()
    props = InterfaceSpec("joint", kn=1e6, ks=1e5, c=10.0)
    t = np.array([[[3., -5.], [3., -5.]]])
    forces = interface_force_pair(mesh, "joint", t, props)
    assert forces["active_elements"] == 1
    # Segment length 2 m; shear force +6 and normal force -10 on face 2.
    assert forces["face2_fx"] == pytest.approx(6.0)
    assert forces["face2_fy"] == pytest.approx(-10.0)
    assert forces["face1_fx"] == pytest.approx(-6.0)
    assert forces["face1_fy"] == pytest.approx(10.0)
    assert forces["imbalance_fx"] == pytest.approx(0.0)
    assert forces["imbalance_fy"] == pytest.approx(0.0)


def test_inactive_interface_is_not_a_spurious_zero_traction_result():
    mesh = sample_mesh()
    props = InterfaceSpec("joint", kn=1e6, ks=1e5)
    t = np.full((1, 2, 2), np.nan)
    forces = interface_force_pair(mesh, "joint", t, props)
    assert forces["active_elements"] == 0
    assert forces["face2_fx"] == 0.0
    # The active_elements count is authoritative for distinguishing absence
    # from an active but unloaded interface.


def test_invalid_active_interface_traction_rejected():
    mesh = sample_mesh()
    props = InterfaceSpec("joint", kn=1e6, ks=1e5)
    with pytest.raises(ValueError, match="nonfinite active"):
        interface_force_pair(
            mesh, "joint",
            np.array([[[0., 1.], [np.nan, 2.]]]), props,
        )
    with pytest.raises(ValueError, match="shape"):
        interface_force_pair(mesh, "joint", np.zeros((1, 3, 2)), props)


def test_stage_interface_aggregation_requires_matching_material_spec():
    from types import SimpleNamespace

    mesh = sample_mesh()
    props = InterfaceSpec("joint", kn=1e6, ks=1e5)
    stage = SimpleNamespace(interfaces={"joint": np.ones((1, 2, 2))})
    model = SimpleNamespace(
        mesh=mesh, interfaces={"joint": props},
        analysis=__import__("slipsurface.fe2d.core.enums", fromlist=["Analysis"]).Analysis.PLANE_STRAIN,
    )
    output = stage_interface_pairs(model, stage)
    assert "joint" in output
    model.interfaces = {}
    with pytest.raises(ValueError, match="Missing interface properties"):
        stage_interface_pairs(model, stage)

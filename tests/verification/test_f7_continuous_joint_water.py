"""F7 interface water transfer on physically connected two-face node chains."""

from __future__ import annotations

import json

import numpy as np
import pytest

from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.model.materials import InterfaceSpec
from slipsurface.fe2d.model.mesh import ElementBlock, Mesh
from slipsurface.fe2d.post.continuous_joint_water import continuous_joint_water_audit

SPEC = InterfaceSpec("joint", 1e6, 1e5)


def connected_mesh(etype, *, split_face=None, reverse=False):
    """2 x 2 m joint elements, each face shares its junction endpoint."""
    ys = [-4., -2., 0.]
    coords = [[0., y] for y in ys] + [[0., y] for y in ys]
    if etype is ElemType.IFACE6:
        coords.extend([[0., -3.], [0., -1.], [0., -3.], [0., -1.]])
    if etype is ElemType.IFACE4:
        conns = [[0, 1, 3, 4], [1, 2, 4, 5]]
    else:
        conns = [[0, 1, 6, 3, 4, 8], [1, 2, 7, 4, 5, 9]]
    if split_face is not None:
        # Break one face at the shared y=-2 junction without moving it.
        old = 1 if split_face == 1 else 4
        new = len(coords)
        coords.append(coords[old][:])
        conns[1][0 if split_face == 1 else (2 if etype is ElemType.IFACE4 else 3)] = new
    if reverse:
        for c in conns:
            c[0], c[1] = c[1], c[0]
            off = 2 if etype is ElemType.IFACE4 else 3
            c[off], c[off + 1] = c[off + 1], c[off]
    return Mesh(
        np.asarray(coords),
        (ElementBlock(
            etype, np.asarray(conns), np.ones(2, dtype=int), "joint",
        ),),
    )


@pytest.mark.parametrize("etype", [ElemType.IFACE4, ElemType.IFACE6])
@pytest.mark.parametrize("reverse", [False, True])
def test_two_sided_connected_joint_passes_nodal_and_hydrostatic_gates(etype, reverse):
    mesh = connected_mesh(etype, reverse=reverse)
    result = continuous_joint_water_audit(mesh, "joint", SPEC, head=0.)
    assert result["topology_status"] == "passed"
    assert result["connected_junctions"] == 1
    assert result["nodal"]["status"] == "passed"
    assert result["hydrostatic"]["status"] == "passed"
    assert result["all_passed"]
    assert abs(result["hydrostatic"]["assembled_face2_fx_kn_per_m"]) == pytest.approx(
        78.48, rel=1e-12,
    )
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("face", [1, 2])
def test_duplicate_coincident_node_ids_at_joint_are_rejected(face):
    mesh = connected_mesh(ElemType.IFACE4, split_face=face)
    with pytest.raises(ValueError, match="share node IDs"):
        continuous_joint_water_audit(mesh, "joint", SPEC, head=0.)


def test_faces_must_remain_topologically_distinct():
    mesh = connected_mesh(ElemType.IFACE4)
    conns = mesh.block("joint").conn.copy()
    conns[:, 2:] = conns[:, :2]
    corrupted = Mesh(
        mesh.coords,
        (ElementBlock(ElemType.IFACE4, conns, np.ones(2, int), "joint"),),
    )
    with pytest.raises(ValueError, match="distinct node IDs"):
        continuous_joint_water_audit(corrupted, "joint", SPEC, head=0.)


def test_two_element_water_table_at_common_node_preserves_both_gates():
    mesh = connected_mesh(ElemType.IFACE6)
    result = continuous_joint_water_audit(mesh, "joint", SPEC, head=-2.)
    assert result["all_passed"]
    assert result["connected_junctions"] == 1
    # Face-1 runs upward (-4 -> 0), so its left normal points towards
    # negative x. The face-2 hydrostatic force is therefore signed negative.
    assert result["hydrostatic"]["analytical_face2_fx_kn_per_m"] == pytest.approx(
        -19.62, rel=1e-12,
    )
    assert result["hydrostatic"]["assembled_face2_fx_kn_per_m"] == pytest.approx(
        -19.62, rel=1e-12,
    )
    assert result["hydrostatic"]["assembled_face1_fx_kn_per_m"] == pytest.approx(
        19.62, rel=1e-12,
    )

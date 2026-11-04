"""F7 joint-water face force transfer with independent hydrostatic reference."""

from __future__ import annotations

import numpy as np
import pytest

from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.model.materials import InterfaceSpec
from slipsurface.fe2d.model.mesh import ElementBlock, Mesh
from slipsurface.fe2d.post.joint_water_reference import vertical_joint_water_transfer

GAMMA = 9.81


def vertical_joint(etype, spans=((-4., 0.),), *, reverse=False):
    """Each interface segment has separate coincident face-node IDs."""
    coords = []
    elements = []
    for low, high in spans:
        top, bottom = ((high, low) if not reverse else (low, high))
        ys = [top, bottom] if etype is ElemType.IFACE4 else [
            top, bottom, (top + bottom) / 2,
        ]
        face = [[0., y] for y in ys]
        first = len(coords)
        coords.extend(face + face)
        elements.append(np.arange(first, first + 2 * len(ys)))
    return Mesh(
        np.array(coords),
        (ElementBlock(etype, np.asarray(elements), np.ones(len(spans), int), "joint"),),
    )


@pytest.mark.parametrize("etype", [ElemType.IFACE4, ElemType.IFACE6])
def test_joint_water_full_height_matches_independent_hydrostatics(etype):
    mesh = vertical_joint(etype)
    spec = InterfaceSpec("joint", kn=1e6, ks=1e5)
    result = vertical_joint_water_transfer(mesh, "joint", spec, head=0.)
    force = GAMMA * 4.**2 / 2.
    assert result["status"] == "passed"
    assert result["analytical_face2_fx_kn_per_m"] == pytest.approx(force)
    assert result["assembled_face2_fx_kn_per_m"] == pytest.approx(force, rel=1e-12)
    assert result["assembled_face1_fx_kn_per_m"] == pytest.approx(-force, rel=1e-12)
    assert result["assembled_face2_fy_kn_per_m"] == pytest.approx(0., abs=1e-12)
    assert result["action_reaction_fx_kn_per_m"] == pytest.approx(0., abs=1e-12)


def test_two_segments_meeting_at_phreatic_level_integrate_exactly():
    mesh = vertical_joint(ElemType.IFACE4, ((-4., -2.), (-2., 0.)))
    result = vertical_joint_water_transfer(
        mesh, "joint", InterfaceSpec("joint", 1e6, 1e5), head=-2.,
    )
    assert result["status"] == "passed"
    assert result["assembled_face2_fx_kn_per_m"] == pytest.approx(
        GAMMA * 2.**2 / 2, rel=1e-12,
    )


def test_water_table_cutting_quadratic_joint_is_not_falsely_certified():
    mesh = vertical_joint(ElemType.IFACE6)
    result = vertical_joint_water_transfer(
        mesh, "joint", InterfaceSpec("joint", 1e6, 1e5), head=-2.,
    )
    assert result["analytical_face2_fx_kn_per_m"] == pytest.approx(
        GAMMA * 2.**2 / 2,
    )
    assert result["status"] == "failed"
    assert result["relative_residual"] > 1e-6
    assert result["action_reaction_fx_kn_per_m"] == pytest.approx(0., abs=1e-12)


def test_reversed_joint_orientation_reverses_both_face_resultants():
    mesh = vertical_joint(ElemType.IFACE4, reverse=True)
    result = vertical_joint_water_transfer(
        mesh, "joint", InterfaceSpec("joint", 1e6, 1e5), head=0.,
    )
    assert result["status"] == "passed"
    assert result["assembled_face2_fx_kn_per_m"] == pytest.approx(
        -GAMMA * 4.**2 / 2,
    )


def test_inconsistent_segment_orientation_is_rejected():
    first = vertical_joint(ElemType.IFACE4)
    second = vertical_joint(ElemType.IFACE4, reverse=True)
    coords = np.vstack([first.coords, second.coords])
    conn = np.vstack([first.block("joint").conn, second.block("joint").conn + 4])
    mesh = Mesh(
        coords, (ElementBlock(ElemType.IFACE4, conn, np.ones(2, int), "joint"),)
    )
    with pytest.raises(ValueError, match="inconsistent normal orientation"):
        vertical_joint_water_transfer(
            mesh, "joint", InterfaceSpec("joint", 1e6, 1e5), head=0.,
        )

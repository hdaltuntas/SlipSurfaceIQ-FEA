"""F7: interface water load must reach the correct original mesh nodes."""

from __future__ import annotations

import json

import numpy as np
import pytest

from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.model.materials import InterfaceSpec
from slipsurface.fe2d.model.mesh import ElementBlock, Mesh
from slipsurface.fe2d.post.joint_water_nodal import (
    nodal_force_comparison,
    vertical_joint_nodal_water_audit,
)

GAMMA = 9.81


def vertical_joint(etype, spans=((-4., 0.),), reverse=False):
    coords, connectivity = [], []
    for low, high in spans:
        first, last = (high, low) if not reverse else (low, high)
        elevations = [first, last]
        if etype is ElemType.IFACE6:
            elevations.append(0.5 * (first + last))
        face = [[0., y] for y in elevations]
        start = len(coords)
        coords.extend(face + face)
        connectivity.append(np.arange(start, start + 2 * len(face)))
    return Mesh(
        np.asarray(coords),
        (ElementBlock(
            etype, np.asarray(connectivity),
            np.ones(len(spans), dtype=int), "joint",
        ),),
    )


@pytest.mark.parametrize("etype", [ElemType.IFACE4, ElemType.IFACE6])
@pytest.mark.parametrize("reverse", [False, True])
def test_full_hydrostatic_joint_nodal_scatter_matches_tributary_reference(
    etype, reverse,
):
    mesh = vertical_joint(etype, reverse=reverse)
    out = vertical_joint_nodal_water_audit(
        mesh, "joint", InterfaceSpec("joint", 1e6, 1e5), head=0.,
    )
    assert out["both_passed"]
    assert out["nodal"]["status"] == "passed"
    assert out["hydrostatic"]["status"] == "passed"
    assert out["nodal"]["max_abs_nodal_error_kn_per_m"] < 1e-10
    assert out["nodal"]["global_residual_fx_kn_per_m"] == pytest.approx(
        0., abs=1e-12
    )
    expected = GAMMA * 4.**2 / 2
    assert abs(out["hydrostatic"]["assembled_face2_fx_kn_per_m"]) == pytest.approx(
        expected, rel=1e-12,
    )
    json.dumps(out, allow_nan=False)


def test_split_at_water_table_passes_both_independent_gates():
    mesh = vertical_joint(
        ElemType.IFACE4, spans=((-4., -2.), (-2., 0.))
    )
    out = vertical_joint_nodal_water_audit(
        mesh, "joint", InterfaceSpec("joint", 1e6, 1e5), head=-2.,
    )
    assert out["nodal"]["status"] == "passed"
    assert out["hydrostatic"]["status"] == "passed"
    assert out["both_passed"]


def test_water_table_kink_can_pass_scatter_but_fail_hydrostatic_integration():
    mesh = vertical_joint(ElemType.IFACE6)
    out = vertical_joint_nodal_water_audit(
        mesh, "joint", InterfaceSpec("joint", 1e6, 1e5), head=-2.,
    )
    assert out["nodal"]["status"] == "passed"
    assert out["hydrostatic"]["status"] == "failed"
    assert not out["both_passed"]


def test_corrupt_nodal_loading_is_detected_without_total_resultant_cancellation():
    expected = np.array([
        [-10., 0.], [10., 0.], [10., 0.], [-10., 0.]
    ])
    corrupt = expected.copy()
    # Move load from one face node to another, keeping total force zero.
    corrupt[0, 0] -= 2.
    corrupt[1, 0] += 2.
    out = nodal_force_comparison(corrupt, expected)
    assert out["status"] == "failed"
    assert out["global_residual_fx_kn_per_m"] == pytest.approx(0.)
    assert out["max_abs_nodal_error_kn_per_m"] == pytest.approx(2.)


def test_invalid_nodal_loading_arrays_are_rejected():
    with pytest.raises(ValueError, match="identical"):
        nodal_force_comparison(np.zeros((3, 2)), np.zeros((4, 2)))
    with pytest.raises(ValueError, match="finite"):
        nodal_force_comparison(
            np.array([[np.nan, 0.]]), np.array([[0., 0.]])
        )

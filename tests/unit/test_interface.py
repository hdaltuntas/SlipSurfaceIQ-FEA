"""Interface node duplication and the Goodman joint in a full solve (direct shear)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.mesh import Domain, unstructured_mesh
from slipsurface.fe2d.mesh.structures import add_beams, insert_interface

L = 4.0
HT = 0.5  # upper block height: eccentricity of the shear couple stays in the kern


def _box(etype=ElemType.T6):
    d = Domain()
    d.add_polygon([(0, -1), (L, -1), (L, 0), (0, 0)], 1,
                  edge_names=["bottom", None, "joint", None])  # fmt: skip
    d.add_polygon([(0, 0), (L, 0), (L, HT), (0, HT)], 2, edge_names=[None, None, "top", None])
    return unstructured_mesh(d, etype=etype, h=0.2)


@pytest.mark.parametrize("etype", [ElemType.T3, ElemType.T6])
def test_insert_interface_topology(etype):
    m = _box(etype)
    nn = m.nn
    # joint edges run along +x (from the bottom block polygon: (L,0) -> (0,0) reversed?)
    e = m.edges("joint")
    m2 = insert_interface(m, "joint", "if", side="left")
    blk = m2.block("if")
    assert blk.etype is (ElemType.IFACE4 if etype is ElemType.T3 else ElemType.IFACE6)
    assert blk.ne == e.shape[0]
    npe = e.shape[1]
    f1, f2 = blk.conn[:, :npe], blk.conn[:, npe:]
    assert np.allclose(m2.coords[f1], m2.coords[f2])  # coincident faces
    assert m2.nn == nn + np.unique(e).size  # both ends on the boundary -> all duplicated
    soil = m2.block("soil")
    # no continuum element uses both an original and a copy of the same joint node
    orig = np.unique(f1)
    copy = np.unique(f2)
    uses_o = np.isin(soil.conn, orig).any(axis=1)
    uses_c = np.isin(soil.conn, copy).any(axis=1)
    assert not np.any(uses_o & uses_c)
    # the two blocks are now only connected through the interface
    yc = m2.coords[soil.conn[:, :3]].mean(axis=1)[:, 1]
    side_c = uses_c
    assert np.all(np.sign(yc[side_c]) == np.sign(yc[side_c][0]))


def test_open_line_tip_is_not_duplicated():
    d = Domain().add_polygon([(0, 0), (4, 0), (4, 4), (0, 4)], edge_names=[None, None, "top", None])
    d.add_line([(2, 4), (2, 1)], name="crack")
    m = unstructured_mesh(d, h=0.4)
    m2 = insert_interface(m, "crack", "c")
    tip = int(np.argmin(np.hypot(m.coords[:, 0] - 2, m.coords[:, 1] - 1)))
    blk = m2.block("c")
    npe = blk.conn.shape[1] // 2
    pairs = np.column_stack([blk.conn[:, :npe].ravel(), blk.conn[:, npe:].ravel()])
    shared = pairs[pairs[:, 0] == pairs[:, 1], 0]
    assert tip in shared
    top = int(np.argmin(np.hypot(m.coords[:, 0] - 2, m.coords[:, 1] - 4)))
    assert top not in shared  # on the boundary -> duplicated


@pytest.mark.parametrize("c,phi,psi", [(5.0, 30.0, 0.0), (0.0, 25.0, 10.0), (10.0, 0.0, 0.0)])
def test_direct_shear_slip_load(c, phi, psi):
    sn = 100.0
    m = insert_interface(_box(), "joint", "if", side="left")
    top = m.nodes("top")
    stages = [api.Stage("press", active_structures={"if"}, loads=(api.EdgeLoad("top", qn=sn),))]
    for k, ux in enumerate([0.002, 0.005, 0.01, 0.02]):
        stages.append(
            api.Stage(
                f"shear{k}",
                active_structures={"if"},
                loads=(api.EdgeLoad("top", qn=sn),),
                displacements=(api.Displacement("top", ux=ux),),
            )
        )
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=m,
        materials={"s": api.MaterialSpec.elastic("s", 1e5, 0.3)},
        region_material={1: "s", 2: "s"},
        fixities=(api.Fixity("bottom", True, True),),
        initial=api.InitialStress("none"),
        stages=stages,
        interfaces={"if": api.InterfaceSpec("if", kn=1e6, ks=1e5, c=c, phi=phi, psi=psi)},
    )
    res = api.run(model)
    T = abs(res.last.reactions[top, 0].sum())
    expected = (c + sn * math.tan(math.radians(phi))) * L
    assert T == pytest.approx(expected, rel=1e-3)
    assert np.all(res.last.struct_flags["if"] == api.PlasticFlag.SHEAR)
    # dilatancy lifts the upper block under constant normal stress
    lift = res.last.u[top, 1].mean() - res.stages[1].u[top, 1].mean()
    slip = 0.02 - 0.002
    if psi > 0:
        assert lift > 0.5 * math.tan(math.radians(psi)) * slip
    else:  # only elastic redistribution in the blocks
        assert abs(lift) < 0.02 * math.tan(math.radians(10.0)) * slip


def test_beam_on_interface_both_sides_keeps_wall_nodes():
    d = Domain().add_polygon([(-3, -4), (3, -4), (3, 0), (-3, 0)],
                             edge_names=["bottom", None, None, None])  # fmt: skip
    d.add_line([(0, 0), (0, -2)], name="wall")
    m = unstructured_mesh(d, h=0.4)
    wall_nodes = np.unique(m.edges("wall"))
    m = add_beams(m, "wall", "wall")
    m = insert_interface(m, "wall", "ifL", side="left")
    m = insert_interface(m, "wall", "ifR", side="right")
    soil = m.block("soil")
    # the original wall nodes now carry only the beam and the interface faces
    used = np.isin(wall_nodes, soil.conn)
    tip = int(np.argmin(np.hypot(m.coords[wall_nodes, 0], m.coords[wall_nodes, 1] + 2)))
    assert used[tip]  # the embedded tip stays shared with the soil
    assert used.sum() == 1

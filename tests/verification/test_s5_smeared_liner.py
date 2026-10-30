"""S5 — smeared shotcrete/mesh/rib liner against Timoshenko beam theory.

``LiningSystem`` EA and EI (shotcrete + two mesh layers + one steel rib) are passed
to a BEAM2 with nu = 0, so the plane-strain factor is 1. With the soil switched off:

    w = P L^3 / (3 EI) + P L / (G As)
    u = N L / EA

The soil block exists only because the stage driver requires a continuum element.
That element is fully fixed and does not share nodes with the liner.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.cad.lining import LiningSystem
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.mesh import layered_box
from slipsurface.fe2d.mesh.structures import add_beams

L = 6.0
LINING = LiningSystem(
    thickness=0.30,
    E_shotcrete=2.0e7,
    nu=0.0,
    unit_weight=0.0,
    mesh="Q257",
    mesh_layers=2,
    cover=0.04,
    rib="Özel",
    rib_area=40.0,
    rib_inertia=2500.0,
    rib_spacing=1.25,
)


def _beam_mesh():
    # Region 1 is the top strip (inactive in the beam stage). Region 2 stays on only
    # so a stage is allowed to have continuum; every one of its nodes is fixed.
    mesh = layered_box(L, [1.0, 0.0], -1.0, nx=4, ny_per_layer=[1, 1], etype=ElemType.T3)
    mesh = add_beams(mesh, "top", "liner")
    soil = next(b for b in mesh.blocks if b.etype is ElemType.T3)
    dummy = np.unique(soil.conn[soil.region == 2])
    left = set(mesh.nodes("left").tolist())
    right = set(mesh.nodes("right").tolist())
    top = mesh.nodes("top")
    fixed = np.array([n for n in top if n in left])
    tip = np.array([n for n in top if n in right])
    sets = {**mesh.node_sets, "fixed": fixed, "tip": tip, "dummy": dummy}
    return replace(mesh, node_sets=sets), int(tip[0])


def _model(mesh, loads):
    props = LINING.liner_properties()
    return api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"fill": api.MaterialSpec.elastic("fill", 1.0e4, 0.0)},
        region_material={1: "fill", 2: "fill"},
        fixities=(api.Fixity("fixed", True, True, True), api.Fixity("dummy", True, True)),
        initial=api.InitialStress("none"),
        stages=[
            api.Stage(
                "beam",
                active_regions=frozenset({2}),
                active_structures={"liner"},
                loads=loads,
            )
        ],
        liners={"liner": api.LinerSpec("liner", **props)},
    )


def _section():
    props = LINING.liner_properties()
    ea, ei = LINING.stiffness()
    assert props["E"] * props["A"] == pytest.approx(ea)
    assert props["E"] * props["I"] == pytest.approx(ei)
    g = props["E"] / 2.0  # nu = 0
    return ea, ei, g * props["As"]


def test_cantilever_tip_matches_timoshenko():
    mesh, tip = _beam_mesh()
    p = 1.0
    res = api.run(_model(mesh, (api.PointLoad(tip, 0.0, -p),)))
    _ea, ei, ga = _section()
    expected = p * L**3 / (3.0 * ei) + p * L / ga
    assert res.last.u[tip, 1] == pytest.approx(-expected, rel=1e-8)
    assert res.last.u[tip, 0] == pytest.approx(0.0, abs=1e-9)


def test_axial_extension_matches_smeared_ea():
    mesh, tip = _beam_mesh()
    n = 1000.0
    res = api.run(_model(mesh, (api.PointLoad(tip, n, 0.0),)))
    ea, _ei, _ga = _section()
    assert res.last.u[tip, 0] == pytest.approx(n * L / ea, rel=1e-8)
    assert res.last.u[tip, 1] == pytest.approx(0.0, abs=1e-9)

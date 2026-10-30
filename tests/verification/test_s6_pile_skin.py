"""S6 — pile row skin friction against the strength the CAD compiler stores.

A pile is a beam row plus two Goodman faces. Skin resistance ``T_skin`` [kN per pile]
is shared by the two faces and by the out-of-plane spacing:

    c = T_skin / (2 spacing)     =>     q_ult = T_skin / spacing   [kN/m per metre of pile]

The pile nodes are translated rigidly along the pile. With a stiff weightless soil the
only mechanism is interface slip, so the holding force is ``q_ult * L``.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.cad.supports import SupportAssignment
from slipsurface.fe2d.mesh import Domain, unstructured_mesh
from slipsurface.fe2d.mesh.structures import add_beams, insert_interface

L = 4.0
T_SKIN = 200.0
SPACING = 2.0


def _model():
    pile = SupportAssignment(
        "P",
        "pile",
        dict(D=0.8, spacing=SPACING, T_skin=T_SKIN, kn=1.0e7, ks=1.0e5, E=1.0e8,
             nu=0.0, unit_weight=0.0),
    )
    domain = Domain()
    domain.add_polygon(
        [(0.0, 0.0), (8.0, 0.0), (8.0, L), (0.0, L)],
        region=1,
        edge_names=["bottom", "right", "top", "left"],
    )
    domain.add_line([(4.0, 0.0), (4.0, L)], name="wall")
    mesh = unstructured_mesh(domain, h=1.0)
    wall_nodes = np.unique(mesh.edges("wall"))
    mesh = add_beams(mesh, "wall", pile.tag)
    for spec, side in zip(pile.interface_specs(), ("left", "right")):
        mesh = insert_interface(mesh, "wall", spec.name, side)
    names = ("bottom", "top", "left", "right")
    boundary = np.unique(np.concatenate([mesh.nodes(s) for s in names]))
    soil_fix = np.setdiff1d(boundary, wall_nodes)
    mesh = replace(mesh, node_sets={**mesh.node_sets, "pile": wall_nodes, "soil_fix": soil_fix})
    faces = pile.interface_specs()
    assert faces[0].c == pytest.approx(T_SKIN / (2.0 * SPACING))
    tags = frozenset({pile.tag, *(s.name for s in faces)})
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"soil": api.MaterialSpec.elastic("soil", 1.0e8, 0.0)},
        region_material={1: "soil"},
        fixities=(api.Fixity("soil_fix", True, True), api.Fixity("pile", True, False, True)),
        initial=api.InitialStress("none", active_structures=frozenset()),
        stages=[
            api.Stage(
                "pull",
                active_structures=tags,
                displacements=(api.Displacement("pile", uy=0.02),),
            )
        ],
        liners={pile.tag: pile.spec()},
        interfaces={s.name: s for s in faces},
        settings=api.SolverSettings(method="NR", max_iter=25),
    )
    return model, wall_nodes


def test_skin_capacity_is_t_over_spacing_times_length():
    model, wall_nodes = _model()
    res = api.run(model)
    held = res.last.reactions[wall_nodes, 1].sum()
    # Support reaction on the pile: +uy displacement is held by an upward force
    # equal to the downward skin resistance.
    expected = (T_SKIN / SPACING) * L
    assert held == pytest.approx(expected, rel=1e-8)

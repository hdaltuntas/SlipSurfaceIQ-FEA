"""F7: structural load-transfer and equilibrium of a staged cantilever liner.

This is a deliberately isolated Timoshenko beam verification, not an RS2
excavation benchmark. The active beam is supported at one end and loaded at
the other; a disconnected, fully fixed inactive continuum avoids soil
coupling. Stages raise P to 1 and then 2 kN/m and must preserve cumulative
beam forces, reactions and tip displacement.

The independent reference is w = P L^3/(3 EI) + P L/(G As) and Mroot=P L.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.mesh import layered_box
from slipsurface.fe2d.mesh.structures import add_beams

L = 6.0
E = 2.0e7
A = 0.3
I = 0.3**3 / 12.0
AS = A * 5.0 / 6.0
G = E / 2.0  # nu = 0
P = 1.0


def isolated_liner():
    mesh = layered_box(L, [1.0, 0.0], -1.0, nx=4, ny_per_layer=[1, 1],
                       etype=ElemType.T3)
    mesh = add_beams(mesh, "top", "liner")
    soil = next(block for block in mesh.continuum_blocks())
    dummy = np.unique(soil.conn[soil.region == 2])
    top = mesh.nodes("top")
    left = set(mesh.nodes("left").tolist())
    right = set(mesh.nodes("right").tolist())
    fixed = np.array([node for node in top if node in left])
    tip = np.array([node for node in top if node in right])
    assert len(fixed) == len(tip) == 1
    mesh = replace(mesh, node_sets={
        **mesh.node_sets, "fixed": fixed, "tip": tip, "dummy": dummy,
    })
    return mesh, int(tip[0])


def test_staged_liner_moment_reaction_and_displacement_balance():
    mesh, tip = isolated_liner()
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"fill": api.MaterialSpec.elastic("fill", 1.0e4, 0.0)},
        region_material={1: "fill", 2: "fill"},
        fixities=(
            api.Fixity("fixed", True, True, True),
            api.Fixity("dummy", True, True),
        ),
        initial=api.InitialStress("none", active_structures=frozenset()),
        stages=[
            api.Stage("one unit", active_regions=frozenset({2}),
                      active_structures={"liner"},
                      loads=(api.PointLoad(tip, 0.0, -P),)),
            api.Stage("two units", active_regions=frozenset({2}),
                      active_structures={"liner"},
                      loads=(api.PointLoad(tip, 0.0, -2 * P),)),
        ],
        liners={"liner": api.LinerSpec("liner", E, 0.0, A, I, AS, 0.0)},
    )
    result = api.run(model)
    assert len(result.stages) == 2
    for stage, force in zip(result.stages, (P, 2 * P)):
        expected_tip = -(force * L**3 / (3 * E * I) + force * L / (G * AS))
        assert stage.u[tip, 1] == pytest.approx(expected_tip, rel=1e-7, abs=1e-10)
        reactions = stage.reactions.sum(axis=0)
        assert reactions[0] == pytest.approx(0.0, abs=1e-8)
        assert reactions[1] == pytest.approx(force, rel=1e-8)
        assert abs(reactions[2]) == pytest.approx(force * L, rel=1e-8)
        beam_forces = stage.beams["liner"]
        assert np.max(np.abs(beam_forces[..., 2])) == pytest.approx(
            force * L, rel=1e-8
        )
        assert stage.lam == pytest.approx(1.0)
    assert np.allclose(
        result.stages[1].beams["liner"],
        2 * result.stages[0].beams["liner"],
        atol=1e-6, rtol=1e-8,
    )

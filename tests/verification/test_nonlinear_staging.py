"""An elastic path through plastic materials must survive changing active GP arrays."""

from __future__ import annotations

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.mesh import rectangle


def _model(plastic, separate_blocks=False):
    mesh = rectangle(4, 2, 4, 2)
    block = mesh.blocks[0]
    region = np.where(mesh.coords[block.conn[:, :3], 0].mean(axis=1) < 2, 1, 2)
    mesh = api.Mesh(
        mesh.coords,
        (api.ElementBlock(block.etype, block.conn, region, block.tag),),
        mesh.node_sets,
        mesh.edge_sets,
    )
    if separate_blocks:
        source = mesh.blocks[0]
        blocks = tuple(
            api.ElementBlock(
                source.etype, source.conn[region == r], region[region == r], f"soil{r}"
            )
            for r in (1, 2)
        )
        mesh = api.Mesh(mesh.coords, blocks, mesh.node_sets, mesh.edge_sets)
    mats = {}
    for name, E, nu in [("soft", 1e4, 0.3), ("stiff", 4e4, 0.2)]:
        mats[name] = (
            api.MaterialSpec.mohr_coulomb(name, E, nu, 1000, 0, gamma=18)
            if plastic
            else api.MaterialSpec.elastic(name, E, nu, gamma=18)
        )
    return api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials=mats,
        region_material={1: "soft", 2: "stiff"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        initial=api.InitialStress("gravity"),
        stages=[
            api.Stage("all"),
            api.Stage("left only", active_regions={1}),
            api.Stage("swap equal count", active_regions={2}),
            api.Stage("refill both"),
        ],
        settings=api.SolverSettings(tol_force=1e-7, tol_energy=1e-8),
    )


@pytest.mark.parametrize("separate_blocks", [False, True])
def test_plastic_driver_rebuilds_tangent_after_excavation_and_equal_count_swap(separate_blocks):
    linear = api.run(_model(False, separate_blocks))
    plastic = api.run(_model(True, separate_blocks))
    counts = [sum(v.sum() for v in stage.active.values()) for stage in plastic.stages]
    assert counts[0] > counts[1] == counts[2] and counts[3] == counts[0]
    for a, b in zip(linear.stages, plastic.stages):
        np.testing.assert_allclose(a.u, b.u, rtol=1e-7, atol=1e-12)
        for tag in a.sig:
            np.testing.assert_allclose(a.sig[tag], b.sig[tag], rtol=1e-7, atol=1e-9)
            np.testing.assert_array_equal(b.plastic[tag], 0)

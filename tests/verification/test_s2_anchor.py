"""S2 — pretensioned end anchor against an elastic spring, exact series equilibrium.

N = T0 * k_soil / (k_anchor + k_soil), u = -T0/(k_anchor + k_soil).
The anchor spacing applies to both its stiffness and its prestress; it must not be
applied again to the equivalent soil spring. A fixed continuum block is present to
exercise the regular mixed-element stage driver and changing DOF map.
"""

from __future__ import annotations

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.mesh import rectangle
from slipsurface.fe2d.mesh.structures import add_bar


@pytest.mark.parametrize("spacing", [1.0, 2.5, 4.0])
def test_pretensioned_anchor_series_equilibrium(spacing):
    base = rectangle(1, 1, 1, 1, etype=api.ElemType.Q4)
    n = base.nn
    mesh = api.Mesh(
        np.vstack([base.coords, [[2, 0], [3, 0], [5, 0]]]),
        base.blocks,
        {"soil": np.arange(n), "ends": np.array([n, n + 2]), "joint": np.array([n + 1])},
        {},
    )
    mesh = add_bar(mesh, n, n + 1, "anchor")
    mesh = add_bar(mesh, n + 1, n + 2, "spring")
    EA, T0, ks = 10000.0, 100.0, 3000.0
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"s": api.MaterialSpec.elastic("s", 1e4, 0)},
        region_material={1: "s"},
        fixities=(
            api.Fixity("soil", True, True),
            api.Fixity("ends", True, True),
            api.Fixity("joint", False, True),
        ),
        initial=api.InitialStress("none", active_structures={"spring"}),
        bolts={
            "anchor": api.BoltSpec("anchor", EA, 1e6, T0, spacing),
            "spring": api.BoltSpec("spring", 2 * ks, 1e6),
        },
        stages=[
            api.Stage("lock off", active_structures={"anchor", "spring"}),
            api.Stage("hold", active_structures={"anchor", "spring"}),
        ],
    )
    result = api.run(model)
    ka = EA / spacing  # L_anchor = 1 m
    prestress = T0 / spacing
    expected_u = -prestress / (ka + ks)
    expected_N = prestress * ks / (ka + ks)
    for stage in result.stages:
        assert stage.u[n + 1, 0] == pytest.approx(expected_u, rel=0.005)
        assert stage.bars["anchor"][0] == pytest.approx(expected_N, rel=0.005)
        assert stage.bars["spring"][0] == pytest.approx(expected_N, rel=0.005)
        np.testing.assert_allclose(stage.reactions.sum(axis=0), 0.0, atol=1e-10)
    # No new pretension increment when retaining an already active anchor.
    np.testing.assert_allclose(result.stages[0].u, result.stages[1].u, rtol=1e-12, atol=1e-14)

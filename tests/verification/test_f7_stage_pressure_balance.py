"""F7: independently balanced staged pressure and partial stress release.

This is an exact elastic reference for cumulative loading and load_split,
not a substitute for independent excavation-force integration. Pressure is
positive inward, stress is tension-positive, and reactions are kN per metre.
"""

from __future__ import annotations

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.mesh import rectangle

WIDTH = 4.0
HEIGHT = 6.0
E = 24000.0
NU = 0.25
Q = 60.0
SPLIT = 0.4
M = E * (1 - NU) / ((1 + NU) * (1 - 2 * NU))


@pytest.mark.parametrize("etype", [ElemType.T3, ElemType.T6, ElemType.Q4, ElemType.Q8])
def test_three_stage_partial_full_and_incremental_load_balance(etype):
    mesh = rectangle(WIDTH, HEIGHT, 3, 6, etype=etype, origin=(0, -HEIGHT))
    model = api.Model(
        api.Analysis.PLANE_STRAIN,
        mesh,
        {"ground": api.MaterialSpec.elastic("ground", E, NU, gamma=0.0)},
        {1: "ground"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        initial=api.InitialStress("none"),
        stages=[
            api.Stage(
                "40 percent pressure release",
                loads=(api.EdgeLoad("top", qn=Q),),
                load_split=SPLIT,
            ),
            api.Stage("full pressure", loads=(api.EdgeLoad("top", qn=Q),)),
            api.Stage("double pressure", loads=(api.EdgeLoad("top", qn=2 * Q),)),
        ],
    )
    result = api.run(model)
    top = mesh.nodes("top")
    for stage, factor in zip(result.stages, (SPLIT, 1.0, 2.0)):
        predicted_displacement = -factor * Q * HEIGHT / M
        predicted_reaction = factor * Q * WIDTH
        assert np.allclose(stage.u[top, 1], predicted_displacement, rtol=1e-7, atol=1e-9)
        assert np.sum(stage.reactions[:, 1]) == pytest.approx(
            predicted_reaction, rel=1e-7, abs=1e-7
        )
        assert np.sum(stage.reactions[:, 0]) == pytest.approx(0.0, abs=1e-7)
        assert np.mean(stage.sig["soil"][..., 1]) == pytest.approx(
            -factor * Q, rel=1e-7, abs=1e-7
        )
        assert np.isfinite(stage.u[top]).all()
    assert result.stages[0].lam == pytest.approx(SPLIT)
    assert result.stages[1].lam == pytest.approx(1.0)
    assert result.stages[2].lam == pytest.approx(1.0)

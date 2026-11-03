"""F7: nonlinear constitutive implementations must recover exact elastic limit.

Material cohesion and rock strength are deliberately set well above loading,
so Mohr-Coulomb and Hoek-Brown must reproduce an independent elastic column
solution, not merely match each other. This does not validate plastic
excavation convergence; that remains a separate benchmark gate.
"""

from __future__ import annotations

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.mesh import rectangle

E = 30000.0
NU = 0.25
HEIGHT = 6.0
WIDTH = 3.0
PRESSURE = 60.0


def analytical_settlement() -> float:
    modulus = E * (1.0 - NU) / ((1.0 + NU) * (1.0 - 2.0 * NU))
    return -PRESSURE * HEIGHT / modulus


def make_model(material, etype):
    mesh = rectangle(WIDTH, HEIGHT, 2, 4, etype=etype, origin=(0, -HEIGHT))
    return api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"rock": material},
        region_material={1: "rock"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        initial=api.InitialStress("none"),
        stages=[api.Stage("linear limit", loads=(api.EdgeLoad("top", PRESSURE),))],
    )


@pytest.mark.parametrize("etype", [ElemType.T3, ElemType.T6])
@pytest.mark.parametrize("material", [
    api.MaterialSpec.mohr_coulomb(
        "rock", E, NU, c=100000.0, phi=30.0, psi=0.0, gamma=0.0
    ),
    api.MaterialSpec.hoek_brown(
        "rock", E, NU, sigci=1.0e7, GSI=100.0, mi=10.0, gamma=0.0
    ),
], ids=["mohr_coulomb", "hoek_brown"])
def test_high_strength_plastic_models_recover_elastic_column(material, etype):
    result = api.run(make_model(material, etype))
    top = result.model.mesh.nodes("top")
    assert np.allclose(
        result.last.u[top, 1], analytical_settlement(), rtol=1e-7, atol=1e-9
    )
    reaction = result.last.reactions.sum(axis=0)
    assert reaction[0] == pytest.approx(0.0, abs=1e-6)
    assert reaction[1] == pytest.approx(PRESSURE * WIDTH, rel=1e-7)
    assert np.allclose(result.last.sig["soil"][..., 1], -PRESSURE, atol=1e-5)

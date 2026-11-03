"""F7: independent constrained-column solution for plane-strain FEM.

A laterally confined elastic column with vertical pressure has eps_x = eps_z = 0,
and the exact constrained modulus is M = E(1-nu)/((1+nu)(1-2nu)).
For a constant downward surface pressure q, u_y(top) = -q*H/M and
the bottom reactions balance q*W, per unit out-of-plane thickness.

This test deliberately derives the reference independently of FEM output.
It is a *linear elastic* verification, not a soil consolidation or plasticity
benchmark. Refinement should leave the affine displacement solution unchanged.
"""

from __future__ import annotations

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.mesh import rectangle

WIDTH = 4.0
HEIGHT = 8.0
YOUNG = 20000.0  # kPa
POISSON = 0.30
PRESSURE = 120.0  # kPa


def constrained_modulus(e: float, nu: float) -> float:
    return e * (1 - nu) / ((1 + nu) * (1 - 2 * nu))


def column(etype: ElemType, cells: int, *, staged: bool = False):
    mesh = rectangle(
        WIDTH, HEIGHT, nx=cells, ny=2 * cells,
        origin=(0.0, -HEIGHT), etype=etype,
    )
    stages = [
        api.Stage("pressure 120 kPa", loads=(api.EdgeLoad("top", qn=PRESSURE),))
    ]
    if staged:
        stages.append(
            api.Stage("pressure 240 kPa", loads=(api.EdgeLoad("top", qn=2 * PRESSURE),))
        )
    return api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={
            "elastic": api.MaterialSpec.elastic("elastic", YOUNG, POISSON, gamma=0.0)
        },
        region_material={1: "elastic"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        initial=api.InitialStress("none"),
        stages=stages,
    )


@pytest.mark.parametrize("etype", [ElemType.T3, ElemType.T6, ElemType.Q4, ElemType.Q8])
@pytest.mark.parametrize("cells", [2, 4])
def test_oedometer_analytical_displacement_and_equilibrium(etype, cells):
    model = column(etype, cells)
    result = api.run(model)
    top = model.mesh.nodes("top")
    expected = -PRESSURE * HEIGHT / constrained_modulus(YOUNG, POISSON)
    assert np.allclose(result.last.u[top, 1], expected, atol=1e-9, rtol=1e-7)
    assert np.allclose(result.last.u[top, 0], 0.0, atol=1e-9)
    # For elastic oedometric compression: syy = -q and
    # sxx = szz = -nu/(1-nu) * q; no shear should arise.
    sig = result.last.sig["soil"]
    assert np.allclose(sig[..., 0], -POISSON / (1 - POISSON) * PRESSURE,
                       atol=1e-6, rtol=1e-7)
    assert np.allclose(sig[..., 1], -PRESSURE, atol=1e-6, rtol=1e-7)
    assert np.allclose(sig[..., 2], -POISSON / (1 - POISSON) * PRESSURE,
                       atol=1e-6, rtol=1e-7)
    assert np.allclose(sig[..., 3], 0.0, atol=1e-6)
    force = result.last.reactions.sum(axis=0)
    assert force[0] == pytest.approx(0.0, abs=1e-6)
    assert force[1] == pytest.approx(PRESSURE * WIDTH, rel=1e-7, abs=1e-7)


@pytest.mark.parametrize("etype", [ElemType.T6, ElemType.Q8])
def test_oedometer_staged_pressure_superposition(etype):
    model = column(etype, 2, staged=True)
    result = api.run(model)
    top = model.mesh.nodes("top")
    expected = -PRESSURE * HEIGHT / constrained_modulus(YOUNG, POISSON)
    first = result.stage("pressure 120 kPa").u[top, 1]
    second = result.stage("pressure 240 kPa").u[top, 1]
    assert np.allclose(first, expected, atol=1e-9, rtol=1e-7)
    assert np.allclose(second, 2 * expected, atol=1e-9, rtol=1e-7)
    assert result.last.reactions[:, 1].sum() == pytest.approx(
        2 * PRESSURE * WIDTH, rel=1e-7
    )

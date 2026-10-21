"""Piezometric water level: hydrostatic equilibrium, effective stresses, water lowering."""

from __future__ import annotations

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.units import GAMMA_W
from slipsurface.fe2d.mesh import layered_box

H, D_WT, G_UNSAT, G_SAT, E, NU = 10.0, 4.0, 17.0, 20.0, 2e4, 0.3


def _column(initial_water, stages, mode="gravity"):
    # layer interface at the lowered water table so no element straddles it
    mesh = layered_box(2.0, [0.0, -D_WT], -H, 2, [8, 12])
    mat = api.MaterialSpec.elastic("s", E, NU, gamma=G_UNSAT, gamma_sat=G_SAT)
    return mesh, api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"s": mat},
        region_material={1: "s", 2: "s"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        initial=api.InitialStress(mode, water=initial_water, k0=0.5),
        stages=stages,
    )


@pytest.mark.parametrize("mode", ["gravity", "k0_field"])
def test_hydrostatic_effective_stress(mode):
    mesh, model = _column(api.WaterCondition.piezo([[0.0, 0.0]]), [], mode)
    res = api.run(model)
    xg = res.geom["soil"].xg
    depth = -xg[..., 1]
    st = res.initial
    assert np.allclose(st.pore["soil"], GAMMA_W * depth, atol=1e-9)
    assert np.allclose(st.sig["soil"][..., 1], -(G_SAT - GAMMA_W) * depth, atol=1e-8)
    # the base carries the total weight (soil + water)
    bottom = mesh.nodes("bottom")
    assert st.reactions[bottom, 1].sum() == pytest.approx(G_SAT * H * 2.0, rel=1e-10)


def test_water_table_above_ground_adds_surface_pressure():
    hw = 3.0
    mesh, model = _column(api.WaterCondition.piezo([[0.0, hw]]), [])
    res = api.run(model)
    depth = -res.geom["soil"].xg[..., 1]
    st = res.initial
    assert np.allclose(st.pore["soil"], GAMMA_W * (depth + hw))
    assert np.allclose(st.sig["soil"][..., 1], -(G_SAT - GAMMA_W) * depth, atol=1e-8)
    bottom = mesh.nodes("bottom")
    total = (G_SAT * H + GAMMA_W * hw) * 2.0
    assert st.reactions[bottom, 1].sum() == pytest.approx(total, rel=1e-10)


def test_lowering_water_table_oedometric_settlement():
    mesh, model = _column(
        api.WaterCondition.piezo([[0.0, 0.0]]),
        [api.Stage("lower", water=api.WaterCondition.piezo([[0.0, -D_WT]]))],
    )
    res = api.run(model)
    M = E * (1 - NU) / ((1 + NU) * (1 - 2 * NU))
    z = np.linspace(0, H, 20001)
    before = (G_SAT - GAMMA_W) * z
    after = np.where(z < D_WT, G_UNSAT * z, G_UNSAT * D_WT + (G_SAT - GAMMA_W) * (z - D_WT))
    settle = np.trapezoid((after - before) / M, z)
    top = mesh.nodes("top")
    u = res.last.u[top, 1]
    assert np.allclose(-u, settle, rtol=1e-6)
    # effective stresses after lowering
    depth = -res.geom["soil"].xg[..., 1]
    exp = np.where(
        depth < D_WT, G_UNSAT * depth, G_UNSAT * D_WT + (G_SAT - GAMMA_W) * (depth - D_WT)
    )
    assert np.allclose(res.last.sig["soil"][..., 1], -exp, atol=1e-6)
    p = res.last.pore["soil"]
    assert np.all(p[depth < D_WT] == 0.0)


def test_sloping_piezometric_line_interpolation():
    w = api.WaterCondition.piezo([[0.0, -1.0], [10.0, -3.0]])
    assert np.allclose(w.head(np.array([-5.0, 0.0, 5.0, 20.0])), [-1.0, -1.0, -2.0, -3.0])
    assert api.WaterCondition().head(np.array([1.0]))[0] == -np.inf

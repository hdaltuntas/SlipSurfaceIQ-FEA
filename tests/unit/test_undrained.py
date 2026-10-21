"""Undrained analysis (Faz 4): methods A/B (pore-water stiffness), C (total stress),
dissipation in a drained stage, result storage."""

from __future__ import annotations

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import Drainage
from slipsurface.fe2d.core.units import GAMMA_W
from slipsurface.fe2d.io import read_results, write_results
from slipsurface.fe2d.io.project_json import model_from_dict, model_to_dict
from slipsurface.fe2d.mesh import layered_box

H, E, NU, G_SAT, Q = 6.0, 2e4, 0.3, 20.0, 50.0
DC = E * (1 - NU) / ((1 + NU) * (1 - 2 * NU))  # constrained modulus
KP = E / (3 * (1 - 2 * NU))  # bulk modulus


def _oedometer(mat, stages):
    mesh = layered_box(1.0, [0.0], -H, 1, [6])
    return mesh, api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"s": mat},
        region_material={1: "s"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        initial=api.InitialStress("k0_field", k0=0.5, water=api.WaterCondition.piezo([[0, 0]])),
        stages=stages,
    )


def _load(name, drained=False):
    return api.Stage(
        name,
        loads=(api.EdgeLoad("top", qn=Q),),
        water=api.WaterCondition.piezo([[0, 0]]),
        drained=drained,
    )


@pytest.mark.parametrize(
    ("drainage", "kw_n"),
    [(Drainage.UNDRAINED_A, None), (Drainage.UNDRAINED_B, None), (Drainage.UNDRAINED_A, 5e5)],
)
def test_oedometric_undrained_load_then_consolidation(drainage, kw_n, tmp_path):
    soil = api.MaterialSpec.elastic("s", E, NU, gamma=G_SAT, gamma_sat=G_SAT)
    mat = soil.with_drainage(drainage, Kw_n=kw_n)
    mesh, model = _oedometer(mat, [_load("load"), _load("consolidate", drained=True)])
    res = api.run(model)
    kw = 100 * KP if kw_n is None else kw_n
    und, con = res.stages
    # undrained: the water carries Kw / (Kw + Dc) of the load, uniformly
    pe = und.excess_pore["soil"]
    assert np.allclose(pe, Q * kw / (kw + DC), rtol=1e-9)
    dsy = und.sig["soil"][..., 1] - res.initial.sig["soil"][..., 1]
    assert np.allclose(dsy, -Q * DC / (kw + DC), rtol=1e-8, atol=1e-9)
    top = mesh.nodes("top")
    assert np.allclose(und.u[top, 1], -Q * H / (kw + DC), rtol=1e-8)
    # steady pore pressure unchanged, total vertical stress = -(gamma_sat z + Q)
    depth = -res.geom["soil"].xg[..., 1]
    assert np.allclose(und.pore["soil"], GAMMA_W * depth, atol=1e-9)
    tot = und.sig["soil"][..., 1] - und.pore["soil"] - pe
    assert np.allclose(tot, -(G_SAT * depth + Q), rtol=1e-8)
    # drained stage: the excess pore pressure dissipates, drained settlement reached
    assert not con.excess_pore
    dsy = con.sig["soil"][..., 1] - res.initial.sig["soil"][..., 1]
    assert np.allclose(dsy, -Q, rtol=1e-8)
    assert np.allclose(con.u[top, 1], -Q * H / DC, rtol=1e-8)
    # storage: HDF5 field and the stage flag in the model JSON
    back = read_results(write_results(res, tmp_path / "u.h5"), model)
    assert np.array_equal(back.stages[0].excess_pore["soil"], pe)
    assert not back.stages[1].excess_pore
    m2 = model_from_dict(model_to_dict(model))
    assert [s.drained for s in m2.stages] == [False, True]
    assert m2.materials["s"].drainage is drainage


def test_drained_material_has_no_excess_pore_pressure():
    soil = api.MaterialSpec.elastic("s", E, NU, gamma=G_SAT, gamma_sat=G_SAT)
    _, model = _oedometer(soil, [_load("load")])
    st = api.run(model).stages[0]
    assert not st.excess_pore
    assert np.allclose(st.u[:, 1].min(), -Q * H / DC, rtol=1e-8)


def test_undrained_c_total_stress():
    clay = api.MaterialSpec.elastic("s", E, NU, gamma=G_SAT, gamma_sat=G_SAT)
    mat = clay.with_drainage(Drainage.UNDRAINED_C)
    mesh, model = _oedometer(mat, [_load("load")])
    res = api.run(model)
    depth = -res.geom["soil"].xg[..., 1]
    for st in (res.initial, res.stages[0]):
        assert np.allclose(st.pore["soil"], 0.0)  # no pore pressure: total stresses
        assert not st.excess_pore
    assert np.allclose(res.initial.sig["soil"][..., 1], -G_SAT * depth, rtol=1e-10)
    assert np.allclose(res.stages[0].sig["soil"][..., 1], -(G_SAT * depth + Q), rtol=1e-8)
    bottom = mesh.nodes("bottom")
    assert res.initial.reactions[bottom, 1].sum() == pytest.approx(G_SAT * H, rel=1e-10)

"""P5 — drained triaxial compression / extension and uniaxial tension, Mohr-Coulomb.

Axisymmetric sample (r in [0, 1], z in [0, 1]) with constant cell pressure (initial
stress field + radial pressure) and an axial displacement history imposed through stage
displacements. The stress state is homogeneous, so every Gauss point must follow the
closed-form stress path; the radial strain checks the (non-associated) flow rule.
Criterion: < 0.1 % (achieved to round-off).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.mesh import rectangle

E, NU, C, PHI, PSI, P = 2.0e4, 0.3, 10.0, 30.0, 10.0, 100.0
K = (1 + math.sin(math.radians(PHI))) / (1 - math.sin(math.radians(PHI)))
M = (1 + math.sin(math.radians(PSI))) / (1 - math.sin(math.radians(PSI)))
SC = 2 * C * math.sqrt(K)


def _run(eps_axial, p=P, sig_t=None):
    mesh = rectangle(1.0, 1.0, 2, 2, ElemType.T6)
    stages = [
        api.Stage(
            f"e{i}",
            loads=(api.EdgeLoad("right", qn=p),),
            displacements=(api.Displacement("top", uy=float(e)),),
        )
        for i, e in enumerate(eps_axial)
    ]
    model = api.Model(
        analysis=api.Analysis.AXISYMMETRIC,
        mesh=mesh,
        materials={"s": api.MaterialSpec.mohr_coulomb("s", E, NU, C, PHI, PSI, sig_t=sig_t)},
        region_material={1: "s"},
        fixities=(api.Fixity("left", True, False), api.Fixity("bottom", False, True)),
        initial=api.InitialStress("field", field=(-p, -p, -p, 0.0)),
        stages=stages,
        settings=api.SolverSettings(tol_force=1e-10, tol_energy=1e-12),
    )
    return mesh, api.run(model)


def _gp_stress(res, i):
    return res.stages[i].sig["soil"].reshape(-1, 4)


@pytest.mark.parametrize("mode", ["compression", "extension"])
def test_triaxial_stress_path(mode):
    sgn = -1.0 if mode == "compression" else 1.0
    eps = sgn * np.linspace(0.002, 0.03, 15)  # axial strain (H = 1)
    mesh, res = _run(eps)
    top = mesh.nodes("top")
    right = mesh.nodes("right")
    if mode == "compression":
        sa_yield = -(K * P + SC)  # |sigma_a| = k p + sc
        ratio = -M / 2  # d eps_r / d eps_a in the plastic range
    else:
        sa_yield = (SC - P) / K
        ratio = -1 / (2 * M)
    ea_y = (sa_yield + P) / E
    er_y = -NU * ea_y
    for i, ea in enumerate(eps):
        s = _gp_stress(res, i)
        sa_ex = -P + E * ea if abs(ea) < abs(ea_y) else sa_yield
        assert np.allclose(s[:, 1], sa_ex, rtol=1e-3, atol=1e-6 * P)
        assert np.allclose(s[:, [0, 2]], -P, atol=1e-6 * P)
        assert np.allclose(s[:, 3], 0.0, atol=1e-6 * P)
        u = res.stages[i].u
        assert np.allclose(u[top, 1], ea)
        er_ex = -NU * ea if abs(ea) < abs(ea_y) else er_y + ratio * (ea - ea_y)
        assert np.allclose(u[right, 0], er_ex, rtol=1e-3)
    assert np.all(res.last.plastic["soil"] > 0)


def test_uniaxial_tension_cutoff():
    st = 5.0
    eps = np.linspace(1e-4, 2e-3, 8)
    mesh, res = _run(eps, p=0.0, sig_t=st)
    right = mesh.nodes("right")
    ea_y = st / E
    for i, ea in enumerate(eps):
        s = _gp_stress(res, i)
        sa_ex = E * ea if ea < ea_y else st
        assert np.allclose(s[:, 1], sa_ex, rtol=1e-6, atol=1e-9)
        # tension cut-off flow is purely axial: lateral strain frozen at yield
        er_ex = -NU * min(ea, ea_y)
        assert np.allclose(res.stages[i].u[right, 0], er_ex, rtol=1e-6)
    # on the perfectly plastic plateau the homogeneous solution is not unique (some
    # elements may unload elastically at sigma_t), so only require tension flags
    flags = res.last.plastic["soil"]
    assert np.all(np.isin(flags, (0, api.PlasticFlag.TENSION))) and np.any(flags > 0)

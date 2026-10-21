"""P2 — elasto-plastic thick-walled cylinder under internal pressure (Hill 1950).

Plane strain (axisymmetric model with eps_z = 0), Tresca material (Mohr-Coulomb with
phi = psi = 0, k = c). With plastic radius rc the internal pressure is

    p = k [2 ln(rc/a) + 1 - rc^2/b^2]

and the outer (elastic) zone gives the exact outer-wall displacement

    u_b = 2 (1 - nu^2) k rc^2 / (E b).

sigma_z remains the intermediate principal stress for these parameters, which the
closed form assumes. Criterion: pressure-expansion curve within 2 %.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.optimize import brentq

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.mesh import rectangle

A_IN, B_OUT, E, NU, KC = 1.0, 2.0, 2.1e5, 0.3, 100.0


def p_of_rc(rc):
    return KC * (2 * np.log(rc / A_IN) + 1 - rc**2 / B_OUT**2)


def ub_exact(p):
    p_el = KC * (1 - A_IN**2 / B_OUT**2)
    if p <= p_el:  # elastic Lamé
        ca = p * A_IN**2 / (B_OUT**2 - A_IN**2)
        cb = p * A_IN**2 * B_OUT**2 / (B_OUT**2 - A_IN**2)
        return (1 + NU) / E * ((1 - 2 * NU) * ca * B_OUT + cb / B_OUT)
    rc = brentq(lambda r: p_of_rc(r) - p, A_IN, B_OUT)
    return 2 * (1 - NU**2) * KC * rc**2 / (E * B_OUT)


@pytest.mark.parametrize("etype,nr", [(ElemType.T6, 40), (ElemType.Q8, 40), (ElemType.Q4, 80)])
def test_hill_pressure_expansion(etype, nr):
    pressures = KC * np.array([0.5, 0.75, 0.9, 1.0, 1.1, 1.2, 1.3, 1.35])
    mesh = rectangle(B_OUT - A_IN, 0.1, nr, 2, etype, origin=(A_IN, 0.0), grade_x=2.0)
    model = api.Model(
        analysis=api.Analysis.AXISYMMETRIC,
        mesh=mesh,
        materials={"tresca": api.MaterialSpec.mohr_coulomb("tresca", E, NU, KC, 0.0, 0.0)},
        region_material={1: "tresca"},
        fixities=(api.Fixity("bottom", False, True), api.Fixity("top", False, True)),
        initial=api.InitialStress("none"),
        stages=[
            api.Stage(f"p{i}", loads=(api.EdgeLoad("left", qn=float(p)),))
            for i, p in enumerate(pressures)
        ],
        settings=api.SolverSettings(tol_force=1e-6, tol_energy=1e-8),
    )
    res = api.run(model)
    outer = mesh.nodes("right")
    errs = []
    for p, st in zip(pressures, res.stages):
        ub = st.u[outer, 0].mean()
        errs.append(abs(ub - ub_exact(p)) / ub_exact(p))
    assert max(errs) < 0.02, f"max error {max(errs):.3%}"
    # plastic radius at p = 1.2 k: Gauss points with r < rc are plastic
    rc = brentq(lambda r: p_of_rc(r) - pressures[5], A_IN, B_OUT)
    r = res.geom["soil"].xg[..., 0]
    pl = res.stages[5].plastic["soil"] > 0
    assert np.all(pl[r < rc - 0.04]) and not np.any(pl[r > rc + 0.04])
    # sigma_z intermediate everywhere (assumption of the closed form)
    s = res.stages[5].sig["soil"].reshape(-1, 4)
    assert np.all((s[:, 1] <= s[:, 2] + 1e-6) & (s[:, 1] >= s[:, 0] - 1e-6))

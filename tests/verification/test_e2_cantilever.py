"""E2 — cantilever beam modelled with continuum elements vs. Timoshenko's elasticity
solution (Timoshenko & Goodier; see Augarde & Deeks 2008). Criterion: tip deflection < 1 %.

Beam 0 <= x <= L, -D/2 <= y <= D/2, clamped at x = 0 with the exact displacement field
prescribed there, parabolic shear traction with resultant P (+y) at x = L.
Plane strain is obtained with E' = E/(1-nu^2), nu' = nu/(1-nu).
"""

from __future__ import annotations

import numpy as np
import pytest
from conftest import per_node_displacements

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.fem.static import StaticSolver
from slipsurface.fe2d.mesh import rectangle

E, NU, P, L, D = 1.0e5, 0.3, 10.0, 10.0, 1.0
I = D**3 / 12.0  # noqa: E741
Ep, NUp = E / (1 - NU**2), NU / (1 - NU)


def u_exact(x, y):
    ux = -P * y / (6 * Ep * I) * ((6 * L - 3 * x) * x + (2 + NUp) * (y**2 - D**2 / 4))
    uy = (
        P
        / (6 * Ep * I)
        * (3 * NUp * y**2 * (L - x) + (4 + 5 * NUp) * D**2 * x / 4 + (3 * L - x) * x**2)
    )
    return ux, uy


def shear_traction(x, n):
    y = x[:, 1]
    t = np.zeros_like(x)
    t[:, 1] = P / (2 * I) * (D**2 / 4 - y**2)  # tau_xy * n_x with n = (1, 0)
    return t


@pytest.mark.parametrize(
    "etype,nx,ny",
    [(ElemType.T6, 40, 4), (ElemType.T3, 160, 16), (ElemType.Q8, 40, 4), (ElemType.Q4, 80, 8)],
)
def test_cantilever_tip_deflection(etype, nx, ny):
    mesh = rectangle(L, D, nx, ny, etype, origin=(0.0, -D / 2))
    mesh, bcs = per_node_displacements(mesh, mesh.nodes("left"), u_exact)
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"steel": api.MaterialSpec.elastic("steel", E, NU)},
        region_material={1: "steel"},
        displacements=bcs,
        initial=api.InitialStress("none"),
        stages=[api.Stage("tip")],
    )
    res = StaticSolver(model, extra_tractions={"tip": (("right", shear_traction),)}).run()
    u = res.last.u
    tip = int(np.argmin(np.hypot(mesh.coords[:, 0] - L, mesh.coords[:, 1])))
    exact = u_exact(L, 0.0)[1]
    err = abs(u[tip, 1] - exact) / abs(exact)
    assert err < 0.01, f"tip deflection error {err:.3%}"
    # tip deflection vs. Timoshenko beam theory with kappa = 5/6 (sanity, same order)
    beam = P * L**3 / (3 * Ep * I) + P * L / (5 / 6 * Ep / (2 * (1 + NUp)) * D)
    assert abs(u[tip, 1] - beam) / beam < 0.01


@pytest.mark.parametrize("etype,nx,ny", [(ElemType.T3, 160, 16), (ElemType.T6, 40, 4)])
@pytest.mark.parametrize("order", ["default", "high"])
def test_mixed_cantilever_tip_deflection(etype, nx, ny, order):
    from slipsurface.fe2d.mesh import recombine_mesh

    mesh = recombine_mesh(
        rectangle(L, D, nx, ny, etype, origin=(0.0, -D / 2)), where=lambda x: x[:, 0] < L / 2
    )
    assert len(mesh.blocks) == 2
    mesh, bcs = per_node_displacements(mesh, mesh.nodes("left"), u_exact)
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"m": api.MaterialSpec.elastic("m", E, NU)},
        region_material={1: "m"},
        displacements=bcs,
        initial=api.InitialStress("none"),
        stages=[api.Stage("tip")],
        settings=api.SolverSettings(gauss_order=order),
    )
    res = StaticSolver(model, extra_tractions={"tip": (("right", shear_traction),)}).run()
    tip = int(np.argmin(np.hypot(mesh.coords[:, 0] - L, mesh.coords[:, 1])))
    exact = u_exact(L, 0.0)[1]
    assert abs(res.last.u[tip, 1] - exact) / abs(exact) < 0.01
    # The imposed end traction is P; global force/moment balance must be unchanged.
    np.testing.assert_allclose(res.last.reactions[:, 1].sum(), -P, atol=1e-8)

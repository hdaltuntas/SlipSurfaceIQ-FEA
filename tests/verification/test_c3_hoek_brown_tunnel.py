"""C3 — circular tunnel in a hydrostatic stress field, generalised Hoek-Brown rock mass.

Plane strain quarter model (as P3), initial stress -p0, support pressure reduced from p0
to p_i. Reference (Carranza-Torres 2004, re-derived; compression positive, sigma_r is
the minor and sigma_theta the major principal stress in the plastic ring):

* boundary of the plastic zone: ``2 (p0 - s_rp) = sci (mb s_rp / sci + s)^a``;
* equilibrium ``d s_r / dr = sci (mb s_r / sci + s)^a / r`` integrates in closed form,
  ``u^(1-a) = u_i^(1-a) + mb (1-a) ln(r / a_t)`` with ``u = mb s_r / sci + s``, which gives
  the plastic radius R_pl and the stresses in the ring;
* displacements: the flow rule of the MC-type potential, ``eps_r^p + K_psi eps_theta^p = 0``,
  i.e. ``d(r^K u)/dr = r^K (eps_r^e + K_psi eps_theta^e)``, integrated from the elastic
  solution at R_pl to the wall.

Criterion: wall displacement and plastic radius within 3 %. The FE wall displacement is
1-2 % larger than the infinite-medium reference, mostly because of the finite outer
boundary (traction p0 at 25 a): with 50 a the deviation drops further.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.integrate import quad
from scipy.optimize import brentq

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.core.errors import ModelError
from slipsurface.fe2d.fem.materials import hb_parameters
from slipsurface.fe2d.mesh import plate_with_hole

A, P0, E, NU, SCI, GSI, MI = 1.0, 1.0e4, 2.0e6, 0.25, 2.0e4, 40.0, 10.0
MB, S, AA = hb_parameters(GSI, MI)


def hb_tunnel(p_i: float, psi: float) -> tuple[float, float]:
    """Plastic radius and radial wall displacement (tension +, i.e. negative inwards)."""
    k = (1 + math.sin(math.radians(psi))) / (1 - math.sin(math.radians(psi)))
    G = E / (2 * (1 + NU))
    s_rp = brentq(lambda x: 2 * (P0 - x) - SCI * (MB * x / SCI + S) ** AA, -S * SCI / MB, P0)
    if p_i >= s_rp:
        return A, -(P0 - p_i) * A / (2 * G)
    u_i, u_p = MB * p_i / SCI + S, MB * s_rp / SCI + S
    R = A * math.exp((u_p ** (1 - AA) - u_i ** (1 - AA)) / (MB * (1 - AA)))

    def s_r(r: float) -> float:
        u = (u_i ** (1 - AA) + MB * (1 - AA) * math.log(r / A)) ** (1 / (1 - AA))
        return (u - S) * SCI / MB

    def rhs(r: float) -> float:
        sr = s_r(r)
        st = sr + SCI * (MB * sr / SCI + S) ** AA
        dr, dt = P0 - sr, P0 - st  # stress change, tension positive
        er = ((1 - NU) * dr - NU * dt) / (2 * G)
        et = ((1 - NU) * dt - NU * dr) / (2 * G)
        return r**k * (er + k * et)

    u_R = -(P0 - s_rp) * R / (2 * G)
    return R, (u_R * R**k - quad(rhs, A, R, epsabs=0, epsrel=1e-12)[0]) / A**k


@pytest.mark.parametrize("psi", [0.0, 10.0, 20.0])
def test_c3_hoek_brown_tunnel(psi):
    p_i = 500.0
    mesh = plate_with_hole(A, 25.0, 60, 48, ElemType.T6, grade=40.0)
    rock = api.MaterialSpec.hoek_brown("rock", E, NU, SCI, GSI, MI, psi=psi)
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"rock": rock},
        region_material={1: "rock"},
        fixities=(api.Fixity("x_sym", False, True), api.Fixity("y_sym", True, False)),
        initial=api.InitialStress("field", field=(-P0, -P0, -P0, 0.0)),
        stages=[
            api.Stage(
                "unload",
                loads=(
                    api.EdgeLoad("hole", qn=p_i),
                    api.EdgeLoad("outer_x", qn=P0),
                    api.EdgeLoad("outer_y", qn=P0),
                ),
            )
        ],
        settings=api.SolverSettings(tol_force=1e-5, tol_energy=1e-7),
    )
    res = api.run(model)
    R_ex, ua_ex = hb_tunnel(p_i, psi)
    assert R_ex > 1.5 * A  # a substantial plastic ring
    hole = mesh.nodes("hole")
    ur = np.einsum("ij,ij->i", res.last.u[hole], mesh.coords[hole]) / A
    err_u = abs(ur.mean() - ua_ex) / abs(ua_ex)
    assert err_u < 0.03, f"wall displacement error {err_u:.3%}"
    assert np.ptp(ur) < 0.01 * abs(ua_ex)
    r = np.hypot(*res.geom["soil"].xg.reshape(-1, 2).T)
    pl = res.last.plastic["soil"].ravel() > 0
    R_fe = 0.5 * (r[pl].max() + r[~pl].min())
    assert abs(R_fe - R_ex) / R_ex < 0.03, f"plastic radius {R_fe:.4f} vs {R_ex:.4f}"


def test_hb_parameters_and_spec_validation():
    mb, s, a = hb_parameters(100.0, 10.0)
    assert (mb, s) == pytest.approx((10.0, 1.0)) and a == pytest.approx(0.5, abs=2e-3)
    with pytest.raises(ModelError):
        api.MaterialSpec.hoek_brown("x", E, NU, -1.0, GSI, MI)

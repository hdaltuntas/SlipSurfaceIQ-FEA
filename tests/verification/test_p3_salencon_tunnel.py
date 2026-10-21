"""P3 — circular tunnel in a hydrostatic stress field, Mohr-Coulomb (Salençon 1969).

Plane strain quarter model, initial stress -p0 everywhere; the support pressure on the
hole is reduced from p0 to p_i (the unbalanced force is applied gradually by the stage
driver). Reference (compression positive, Kp = (1+sin phi)/(1-sin phi), H = c cot phi):

    p_cr = (2 p0 - sc) / (1 + Kp),     R_pl = a [2 (p0 + H) / ((1 + Kp)(p_i + H))]^(1/(Kp-1))

The wall displacement follows from the flow rule eps_r^p + K_psi eps_theta^p = 0 in the
plastic ring (sigma_z intermediate), i.e. du/dr + K_psi u/r = eps_r^e + K_psi eps_theta^e,
integrated from the elastic-plastic boundary (u = -(p0 - p_cr) R_pl / 2G) to the wall.
Criterion: plastic radius and wall displacement within 3 %.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.integrate import quad

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.mesh import plate_with_hole

A, P0, E, NU, C, PHI = 1.0, 100.0, 1.0e4, 0.25, 10.0, 30.0


def salencon(p_i, psi):
    kp = (1 + math.sin(math.radians(PHI))) / (1 - math.sin(math.radians(PHI)))
    m = (1 + math.sin(math.radians(psi))) / (1 - math.sin(math.radians(psi)))
    sc = 2 * C * math.sqrt(kp)
    H = C / math.tan(math.radians(PHI))
    G = E / (2 * (1 + NU))
    p_cr = (2 * P0 - sc) / (1 + kp)
    if p_i >= p_cr:
        return A, -(P0 - p_i) * A / (2 * G)
    R = A * (2 * (P0 + H) / ((1 + kp) * (p_i + H))) ** (1 / (kp - 1))

    def eps_e(r):  # elastic strain increments from the initial state (tension +)
        sr = -((p_i + H) * (r / A) ** (kp - 1) - H)
        st = -(kp * (p_i + H) * (r / A) ** (kp - 1) - H)
        dr, dt = sr + P0, st + P0
        return ((1 - NU) * dr - NU * dt) / (2 * G), ((1 - NU) * dt - NU * dr) / (2 * G)

    def rhs(r):
        er, et = eps_e(r)
        return r**m * (er + m * et)

    uR = -(P0 - p_cr) * R / (2 * G)
    ua = (uR * R**m - quad(rhs, A, R, epsabs=0, epsrel=1e-12)[0]) / A**m
    return R, ua


@pytest.mark.parametrize("psi", [0.0, 15.0, 30.0])
def test_tunnel_ground_reaction(psi):
    p_i = 10.0
    mesh = plate_with_hole(A, 25.0, 60, 48, ElemType.T6, grade=40.0)
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"rock": api.MaterialSpec.mohr_coulomb("rock", E, NU, C, PHI, psi)},
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
    R_ex, ua_ex = salencon(p_i, psi)
    hole = mesh.nodes("hole")
    ur = np.einsum("ij,ij->i", res.last.u[hole], mesh.coords[hole]) / A
    err_u = abs(ur.mean() - ua_ex) / abs(ua_ex)
    assert err_u < 0.03, f"wall displacement error {err_u:.3%}"
    assert np.ptp(ur) < 0.01 * abs(ua_ex)  # axisymmetric response
    # plastic radius: boundary between plastic and elastic Gauss points
    r = np.hypot(*res.geom["soil"].xg.reshape(-1, 2).T)
    pl = res.last.plastic["soil"].ravel() > 0
    R_fe = 0.5 * (r[pl].max() + r[~pl].min())
    assert abs(R_fe - R_ex) / R_ex < 0.03, f"plastic radius {R_fe:.4f} vs {R_ex:.4f}"

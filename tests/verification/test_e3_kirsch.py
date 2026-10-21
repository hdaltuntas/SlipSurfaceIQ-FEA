"""E3 — circular hole in an infinite plate under biaxial remote stress (Kirsch).

Quarter model with symmetry conditions; the exact Kirsch stress field is applied as
traction on the outer boundary so the result is free of finite-domain error.
Criterion: hoop stress on the hole wall within 1 % of the maximum.
"""

from __future__ import annotations

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.fem.static import StaticSolver
from slipsurface.fe2d.mesh import plate_with_hole
from slipsurface.fe2d.post import nodal_average

A_HOLE, SX, SY = 1.0, 1.0, 0.4  # remote sxx, syy (tension positive)


def kirsch_polar(r, th, S):
    """Polar stresses for remote uniaxial stress S along x."""
    a2, a4 = (A_HOLE / r) ** 2, (A_HOLE / r) ** 4
    c2, s2 = np.cos(2 * th), np.sin(2 * th)
    srr = S / 2 * (1 - a2) + S / 2 * (1 - 4 * a2 + 3 * a4) * c2
    stt = S / 2 * (1 + a2) - S / 2 * (1 + 3 * a4) * c2
    srt = -S / 2 * (1 + 2 * a2 - 3 * a4) * s2
    return srr, stt, srt


def kirsch_cart(x, y):
    r, th = np.hypot(x, y), np.arctan2(y, x)
    srr1, stt1, srt1 = kirsch_polar(r, th, SX)
    srr2, stt2, srt2 = kirsch_polar(r, th - np.pi / 2, SY)
    srr, stt, srt = srr1 + srr2, stt1 + stt2, srt1 + srt2
    c, s = np.cos(th), np.sin(th)
    sxx = srr * c * c + stt * s * s - 2 * srt * s * c
    syy = srr * s * s + stt * c * c + 2 * srt * s * c
    sxy = (srr - stt) * s * c + srt * (c * c - s * s)
    return sxx, syy, sxy


def traction(x, n):
    sxx, syy, sxy = kirsch_cart(x[:, 0], x[:, 1])
    return np.column_stack([sxx * n[:, 0] + sxy * n[:, 1], sxy * n[:, 0] + syy * n[:, 1]])


@pytest.mark.parametrize("etype,nr,nt", [(ElemType.T6, 24, 48), (ElemType.T3, 64, 128)])
def test_kirsch_hoop_stress(etype, nr, nt):
    mesh = plate_with_hole(A_HOLE, 5.0, nr, nt, etype, grade=6.0)
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"rock": api.MaterialSpec.elastic("rock", 1.0e4, 0.25)},
        region_material={1: "rock"},
        fixities=(api.Fixity("x_sym", False, True), api.Fixity("y_sym", True, False)),
        initial=api.InitialStress("none"),
        stages=[api.Stage("remote")],
    )
    res = StaticSolver(
        model, extra_tractions={"remote": (("outer_x", traction), ("outer_y", traction))}
    ).run()
    s = nodal_average(mesh, res.last.sig)
    hole = mesh.nodes("hole")
    x, y = mesh.coords[hole].T
    th = np.arctan2(y, x)
    stt_fe = (
        s[hole, 0] * np.sin(th) ** 2
        + s[hole, 1] * np.cos(th) ** 2
        - 2 * s[hole, 3] * np.sin(th) * np.cos(th)
    )
    stt_ex = SX * (1 - 2 * np.cos(2 * th)) + SY * (1 + 2 * np.cos(2 * th))
    err = np.max(np.abs(stt_fe - stt_ex)) / np.max(np.abs(stt_ex))
    tol = 0.01 if etype is ElemType.T6 else 0.03  # T3 nodal recovery is first order
    assert err < tol, f"hoop stress error {err:.3%}"
    # Gauss-point stresses over the whole domain
    xg = res.geom["soil"].xg.reshape(-1, 2)
    ex = np.column_stack(kirsch_cart(xg[:, 0], xg[:, 1]))
    fe = res.last.sig["soil"].reshape(-1, 4)[:, [0, 1, 3]]
    assert np.max(np.abs(fe - ex)) / np.max(np.abs(stt_ex)) < (
        0.01 if etype is ElemType.T6 else 0.05
    )

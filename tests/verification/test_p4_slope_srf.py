"""P4 — homogeneous slope, shear strength reduction (Griffiths & Lane 1999, Example 1).

2:1 slope, H = 10 m, no foundation layer (rigid rough base at toe level),
c'/(gamma H) = 0.05, phi' = 20°, psi = 0, gamma = 20 kN/m3, E = 1e5 kPa, nu = 0.3.
Reference: simplified Bishop with a circular-slip search (computed here; Griffiths &
Lane quote 1.38 from the Bishop & Morgenstern charts). Criterion: FS within 3 %.

FE mesh convergence (T6, NR, bisection tol 0.01): h = 2.0 → 1.416, 1.5 → 1.396,
1.0 → 1.377, 0.7 → 1.367 — within 1 % of Bishop (1.378) on the finer meshes.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import minimize

from slipsurface.fe2d import api
from slipsurface.fe2d.fem.srf import strength_reduction
from slipsurface.fe2d.mesh import Domain, unstructured_mesh

H, RUN, CREST, C, PHI, GAMMA = 10.0, 2.0, 20.0, 10.0, 20.0, 20.0


def bishop_fs(xc, yc, R, nslice=120):
    """Simplified Bishop FS of one circle (inf if kinematically invalid)."""
    if R <= 0 or R > yc:  # rigid base at y = 0
        return np.inf
    x = np.linspace(0.0, RUN * H + CREST, 3000)
    ground = np.clip(x / RUN, 0.0, H)
    yb = yc - np.sqrt(np.maximum(R * R - (x - xc) ** 2, 0.0))
    inside = (np.abs(x - xc) < R) & (yb < ground)
    idx = np.flatnonzero(inside)
    if idx.size < 10 or np.any(np.diff(idx) != 1) or idx[-1] == x.size - 1:
        return np.inf
    xe = np.linspace(x[idx[0]], x[idx[-1]], nslice + 1)
    xm, b = 0.5 * (xe[1:] + xe[:-1]), np.diff(xe)
    h = np.maximum(
        np.clip(xm / RUN, 0, H) - (yc - np.sqrt(np.maximum(R * R - (xm - xc) ** 2, 0))), 0
    )
    W = GAMMA * h * b
    sa = (xm - xc) / R
    ca = np.sqrt(1 - sa**2)
    drive = np.sum(W * sa)
    if drive <= 0:
        return np.inf
    tp, F = np.tan(np.radians(PHI)), 1.5
    for _ in range(100):
        Fn = np.sum((C * b + W * tp) / (ca + sa * tp / F)) / drive
        if abs(Fn - F) < 1e-9:
            break
        F = Fn
    return F


def bishop_min():
    best = (np.inf, None)
    for xc in np.linspace(-5, 20, 11):
        for yc in np.linspace(11, 40, 12):
            for R in np.linspace(6, yc, 10):
                f = bishop_fs(xc, yc, R)
                if f < best[0]:
                    best = (f, (xc, yc, R))
    res = minimize(lambda p: bishop_fs(*p), best[1], method="Nelder-Mead",
                   options={"xatol": 1e-3, "fatol": 1e-6})  # fmt: skip
    return min(res.fun, best[0])


def test_bishop_reference():
    assert abs(bishop_min() - 1.38) < 0.01


def test_slope_factor_of_safety():
    d = Domain().add_polygon(
        [(0, 0), (RUN * H + CREST, 0), (RUN * H + CREST, H), (RUN * H, H)],
        edge_names=["base", "right", "crest", "face"],
    )
    mesh = unstructured_mesh(d, h=1.5)
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={
            "soil": api.MaterialSpec.mohr_coulomb("soil", 1e5, 0.3, C, PHI, 0.0, gamma=GAMMA)
        },
        region_material={1: "soil"},
        fixities=(api.Fixity("base", True, True), api.Fixity("right", True, False)),
        initial=api.InitialStress("gravity"),
    )
    res = strength_reduction(model)
    fs_le = bishop_min()
    assert abs(res.factor - fs_le) / fs_le < 0.03, f"FS {res.factor:.3f} vs Bishop {fs_le:.3f}"
    assert res.F_failed - res.factor <= 0.01 + 1e-12
    # the failure mechanism localises along the slope (toe region moves most)
    u = np.linalg.norm(np.nan_to_num(res.u_failed), axis=1)
    x_max = mesh.coords[np.argmax(u), 0]
    assert 0.0 <= x_max <= RUN * H + 2.0

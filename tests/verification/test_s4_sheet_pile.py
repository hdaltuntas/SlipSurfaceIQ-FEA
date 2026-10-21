"""S4 — cantilever sheet pile in (nearly) cohesionless sand.

Retained height H = 4 m excavated in two 2 m lifts, embedment D = 6 m, steel sheet pile
EI = 42 000 kNm2/m. Sand: gamma = 18, phi = 30°, c = 1 kPa, psi = 0, E = 30 MPa, K0 =
1 - sin(phi). Rough interfaces on both faces (R = 0.67 -> wall friction delta = 21.1°),
wall and interfaces installed "wished in place" after the K0 stage.

References (written here from scratch):

* beam-spring (Winkler): Hermite beam on elasto-plastic springs, initial pressure K0 sv'
  (reset to K0 sv' on the excavation side after each lift), limited by Ka / Kp with wall
  friction (Lancellotta 2002 closed form) and the cohesion terms; staged like the FE
  model. Subgrade modulus from Vesic: k_h ~ 0.65 (E B^4/EI)^(1/12) E / (1 - nu^2) / B.
  M_max is insensitive to k_h (2e3..1e5 kN/m3: 83.7 .. 78.4 kNm/m).
* limit equilibrium, free-earth (Blum) maximum moment with full passive resistance.

Measured (T6, line search): FE M_max = 71.8 / 72.2 / 73.8 kNm/m for h = 0.5 / 0.35 / 0.25
at y = -5.1 m; beam-spring 78.5 at z = 5.2 m; LE 78.2. Criterion: M_max within 10 %.

Note: a *smooth* wall (R -> 0) in this nearly cohesionless sand does not converge (a
frictionless joint lets the near-surface soil slide down the wall with ~zero strength);
see docs/verification.md.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.mesh import DistanceSize, Domain, unstructured_mesh
from slipsurface.fe2d.mesh.structures import add_beams, insert_interface

H, D = 4.0, 6.0
GAM, PHI, C, E, NU = 18.0, 30.0, 1.0, 3.0e4, 0.3
EI, EA = 4.2e4, 3.4e6
R_INTER = 0.67
K0 = 1.0 - math.sin(math.radians(PHI))
DELTA = math.degrees(math.atan(R_INTER * math.tan(math.radians(PHI))))
LIFTS = (2.0, 4.0)


# ------------------------------------------------------------------- references
def lancellotta(phi: float, delta: float) -> tuple[float, float]:
    """Ka, Kp for a vertical wall and horizontal ground with wall friction delta."""
    p, d = math.radians(phi), math.radians(delta)
    r = math.sqrt(math.sin(p) ** 2 - math.sin(d) ** 2)
    a = math.asin(math.sin(d) / math.sin(p))
    Kp = math.cos(d) / (1 - math.sin(p)) * (math.cos(d) + r) * math.exp((a + d) * math.tan(p))
    Ka = math.cos(d) / (1 + math.sin(p)) * (math.cos(d) - r) * math.exp(-(a - d) * math.tan(p))
    return Ka, Kp


def beam_spring(kh: float, n: int = 200) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Staged Winkler analysis; returns depth z (down), moment M, displacement u (+x)."""
    L = H + D
    Ka, Kp = lancellotta(PHI, DELTA)
    z = np.linspace(0.0, L, n + 1)
    h = L / n
    trib = np.full(n + 1, h)
    trib[[0, -1]] = h / 2
    nd = 2 * (n + 1)
    K = np.zeros((nd, nd))
    hh = h * h
    ke = (EI / h**3) * np.array(
        [
            [12, 6 * h, -12, 6 * h],
            [6 * h, 4 * hh, -6 * h, 2 * hh],
            [-12, -6 * h, 12, -6 * h],
            [6 * h, 2 * hh, -6 * h, 4 * hh],
        ]
    )
    for e in range(n):
        K[2 * e : 2 * e + 4, 2 * e : 2 * e + 4] += ke
    iw = np.arange(0, nd, 2)
    ca, cp = 2 * C * math.sqrt(Ka), 2 * C * math.sqrt(Kp)
    lo_r, hi_r = np.maximum(Ka * GAM * z - ca, 0.0), Kp * GAM * z + cp
    pr = K0 * GAM * z  # retained side (right), pushes -x
    W = np.zeros(nd)
    for exc in LIFTS:
        on = z > exc + 1e-12
        sv = GAM * np.maximum(z - exc, 0.0)
        lo_l, hi_l = np.maximum(Ka * sv - ca, 0.0), Kp * sv + cp
        pl0 = np.where(on, np.clip(K0 * sv, lo_l, hi_l), 0.0)  # excavation side, pushes +x
        pr0, u0 = pr.copy(), W[iw].copy()

        def state(Wv, pr0=pr0, pl0=pl0, u0=u0, on=on, lo_l=lo_l, hi_l=hi_l):
            du = Wv[iw] - u0
            tr, tl = pr0 + kh * du, pl0 - kh * du
            F = np.zeros(nd)
            F[iw] = (np.where(on, np.clip(tl, lo_l, hi_l), 0.0) - np.clip(tr, lo_r, hi_r)) * trib
            kt = ((tr > lo_r) & (tr < hi_r)) * kh + (on & (tl > lo_l) & (tl < hi_l)) * kh
            return F - K @ Wv, kt, np.clip(tr, lo_r, hi_r)

        R, kt, pr = state(W)
        scale = max(np.abs(R).max(), 1.0)
        for _ in range(200):
            if np.abs(R).max() < 1e-7 * scale:
                break
            Kt = K.copy()
            Kt[iw, iw] += kt * trib + 1e-6 * kh * trib
            dW = np.linalg.solve(Kt, R)
            a = 1.0
            while True:  # backtracking on ||R||
                R2, kt2, pr2 = state(W + a * dW)
                if np.linalg.norm(R2) < np.linalg.norm(R) or a < 1e-6:
                    break
                a *= 0.5
            W, R, kt, pr = W + a * dW, R2, kt2, pr2
        else:  # pragma: no cover
            raise RuntimeError("beam-spring reference did not converge")
    th = W[1::2]
    M = np.zeros(n + 1)
    M[1:-1] = EI * (th[2:] - th[:-2]) / (2 * h)
    return z, M, W[iw]


def le_free_earth_mmax() -> tuple[float, float]:
    """Blum free-earth maximum moment (full passive) and the depth of zero shear."""
    Ka, Kp = lancellotta(PHI, DELTA)
    zs = np.linspace(0.0, 3 * H, 60001)
    pa = np.maximum(Ka * GAM * zs - 2 * C * math.sqrt(Ka), 0.0)
    pp = np.where(zs > H, Kp * GAM * (zs - H) + 2 * C * math.sqrt(Kp), 0.0)
    net = pa - pp
    dz = zs[1] - zs[0]
    V = np.cumsum(net) * dz
    i0 = int(np.flatnonzero((zs > H) & (V <= 0))[0])
    return float(np.sum(net[:i0] * (zs[i0] - zs[:i0])) * dz), float(zs[i0])


def kh_vesic() -> float:
    return 0.65 * (E * 1.0 / EI) ** (1 / 12) * E / (1 - NU**2)


def test_references_consistent():
    Ka, Kp = lancellotta(PHI, 0.0)  # smooth wall: Rankine
    assert Ka == pytest.approx(1 / 3) and Kp == pytest.approx(3.0)
    m_le, _ = le_free_earth_mmax()
    z, M, _ = beam_spring(1e6)  # stiff springs -> close to the limit-equilibrium moment
    assert abs(np.abs(M).max() - m_le) / m_le < 0.02


# ------------------------------------------------------------------- FE model
def _fe_model(h: float):
    W, B = 25.0, 22.0
    wall = np.array([[0.0, 0.0], [0.0, -(H + D)]])
    d = Domain()
    d.add_polygon([(-W, -B), (W, -B), (W, 0), (-W, 0)], 1,
                  edge_names=["bottom", "right", "top", "left"])  # fmt: skip
    d.add_polygon([(-W, -LIFTS[0]), (0, -LIFTS[0]), (0, 0), (-W, 0)], 2)
    d.add_polygon([(-W, -LIFTS[1]), (0, -LIFTS[1]), (0, -LIFTS[0]), (-W, -LIFTS[0])], 3)
    d.add_line(wall, name="wall")
    mesh = unstructured_mesh(d, h=DistanceSize(h, 2.5, 1.2, lines=[wall]))
    mesh = add_beams(mesh, "wall", "wall")
    mesh = insert_interface(mesh, "wall", "ifL", side="left")
    mesh = insert_interface(mesh, "wall", "ifR", side="right")
    sand = api.MaterialSpec.mohr_coulomb("sand", E, NU, C, PHI, 0.0, gamma=GAM)
    ifs = {
        k: api.InterfaceSpec.from_soil(k, sand, R=R_INTER, t_v=0.1, R_stiffness=1.0)
        for k in ("ifL", "ifR")
    }
    E_steel = 2.1e8
    S = frozenset({"wall", "ifL", "ifR"})
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"sand": sand},
        region_material={1: "sand", 2: "sand", 3: "sand"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        initial=api.InitialStress("k0_field", active_structures=frozenset()),
        stages=[
            api.Stage("install", active_structures=S),
            api.Stage("lift1", active_regions={1, 3}, active_structures=S),
            api.Stage("lift2", active_regions={1}, active_structures=S),
        ],
        liners={
            "wall": api.LinerSpec(
                "wall", E_steel, 0.0, EA / E_steel, EI / E_steel, 0.5 * EA / E_steel
            )
        },  # fmt: skip
        interfaces=ifs,
        settings=api.SolverSettings(line_search=True),
    )
    return mesh, model


def test_cantilever_sheet_pile_max_moment():
    mesh, model = _fe_model(h=0.5)
    res = api.run(model)
    blk = mesh.block("wall")
    M = res.last.beams["wall"][:, :, 2]
    y = mesh.coords[blk.conn, 1]
    i = np.unravel_index(np.abs(M).argmax(), M.shape)
    m_fe, y_fe = float(np.abs(M).max()), float(y[i])

    z, Mbs, ubs = beam_spring(kh_vesic())
    m_bs, z_bs = float(np.abs(Mbs).max()), float(z[np.abs(Mbs).argmax()])
    m_le, _ = le_free_earth_mmax()

    assert abs(m_fe - m_bs) / m_bs < 0.10, (m_fe, m_bs)
    assert abs(m_fe - m_le) / m_le < 0.10, (m_fe, m_le)
    assert abs(-y_fe - z_bs) < 0.5  # same depth of the maximum
    # wall head displacement (towards the excavation) of the same order
    top = int(np.argmax(mesh.coords[blk.conn[:, 0], 1]))
    u_top = res.last.u[blk.conn[top, 0], 0]
    assert u_top < 0 and abs(u_top - ubs[0]) / abs(ubs[0]) < 0.3
    # moment vanishes at the free head and the toe
    assert abs(M[top, 0]) < 0.02 * m_fe

"""S1 — circular tunnel with an elastic liner in elastic ground (Einstein & Schwartz 1979).

Deep tunnel, in-situ stresses sigma_v = -P, sigma_h = -K P, liner installed when the
tunnel is excavated (no relaxation), plane strain. The reference is the closed-form
interaction solution behind Einstein & Schwartz, derived here so that every convention
is explicit:

* ground: elastic plane with a hole; the change of boundary traction (contact stress minus
  in-situ traction) in Fourier modes n = 0 and n = 2 (Michell stress function
  phi = (C1 + C2 r^-2) cos 2theta); wall displacements by integrating the strains from
  infinity. Without liner this reduces to the Kirsch wall displacement.
* liner: thin extensible ring, E' = E/(1 - nu^2), curvature kappa = (w'' - v')/R^2;
* compatibility: radial and tangential (no slip) or radial only (full slip, zero shear).

FE: quarter model, T6 ground, Timoshenko BEAM2 liner on the excavation boundary; the full
slip case puts a zero-thickness interface (ks ~ 0) between liner and ground.
Criterion: thrust N and moment M amplitudes within 5 %.
"""

from __future__ import annotations

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.mesh import DistanceSize, Domain, arc, unstructured_mesh
from slipsurface.fe2d.mesh.structures import add_beams, insert_interface

R, P, K = 3.0, 1000.0, 0.5
EM, NUM = 5.0e5, 0.25
EL, NUL, T = 3.0e7, 0.2, 0.3
A_L, I_L = T, T**3 / 12


def reference(slip: bool):
    """Returns (N0, N2, M2): N = N0 + N2 cos 2theta (tension +), M = M2 cos 2theta,
    theta from the horizontal axis."""
    G = EM / (2 * (1 + NUM))
    Ep = EL / (1 - NUL**2)
    a_r, b_r = Ep * A_L / R**2, Ep * I_L / R**4
    S, D = P * (1 + K) / 2, P * (1 - K) / 2  # in situ: sr0 = -S + D cos2t, t0 = -D sin2t
    # mode 0: ring W0 = q0 / a_r = ground -(q0 + S) R / 2G
    q0 = -S * R / (2 * G) / (1 / a_r + R / (2 * G))
    N0 = Ep * A_L * (q0 / a_r) / R  # E'A W0 / R

    def ring(qr, qt, n=2):
        X = (n * qt - qr) / (a_r * (n * n - 1))
        Y = (n * qr - qt) / (b_r * n * n * (n * n - 1))
        W = (n * Y - X) / (n * n - 1)
        V = Y - n * W
        return W, V, a_r * R * X, -b_r * R * R * n * Y  # W, V, N, M

    def ground(sr, tc):
        A2, B2 = sr - D, tc + D
        a = (B2 - A2) / 2
        b = (-B2 - 2 * a) / 6
        Ur = R / (2 * G) * (4 * (1 - NUM) * a + 2 * b)
        Ut = R / G * ((2 * NUM - 1) * a + b)
        return Ur, Ut

    def residual(x):
        sr, tc = (x[0], x[1]) if not slip else (x[0], 0.0)
        W, V, _, _ = ring(sr, tc)
        Ur, Ut = ground(sr, tc)
        return np.array([W - Ur, V - Ut]) if not slip else np.array([W - Ur])

    n = 1 if slip else 2
    r0 = residual(np.zeros(2))
    J = np.column_stack([residual(np.eye(2)[k]) - r0 for k in range(n)])
    x = np.linalg.solve(J, -r0)
    sr, tc = (x[0], 0.0) if slip else (x[0], x[1])
    _, _, N2, M2 = ring(sr, tc)
    return N0, N2, M2


def test_reference_ring_equilibrium():
    """Curved-beam equilibrium: with no tangential load N2 = M2 / R (any slip case)."""
    _, N2, M2 = reference(True)
    assert N2 == pytest.approx(M2 / R, rel=1e-12)


def test_reference_reduces_to_kirsch_without_liner():
    # with a vanishing liner the ground wall displacement is Kirsch's
    G = EM / (2 * (1 + NUM))
    S, D = P * (1 + K) / 2, P * (1 - K) / 2
    A2, B2 = -D, D  # free surface: contact stresses zero
    a = (B2 - A2) / 2
    b = (-B2 - 2 * a) / 6
    Ur = R / (2 * G) * (4 * (1 - NUM) * a + 2 * b)
    assert Ur == pytest.approx(P * R * (1 - K) * (3 - 4 * NUM) / (4 * G))
    assert -S * R / (2 * G) == pytest.approx(-P * R * (1 + K) / (4 * G))


def _model(slip: bool):
    L = 20 * R
    ring_pts = arc(0.0, 0.0, R, 0.0, np.pi / 2, 48)
    d = Domain()
    d.add_polygon([(0, 0), (L, 0), (L, L), (0, L)], 1,
                  edge_names=["x_axis", "outer_x", "outer_y", "y_axis"])  # fmt: skip
    core = np.vstack([[[0.0, 0.0]], ring_pts])
    d.add_polygon(core, 2, edge_names=[None] + ["lining"] * 48 + [None])
    d.add_point(R, 0.0, "liner_a")
    d.add_point(0.0, R, "liner_b")
    mesh = unstructured_mesh(d, h=DistanceSize(0.12, 4.0, 1.15, lines=[ring_pts]))
    mesh = add_beams(mesh, "lining", "liner")
    structures = {"liner"}
    interfaces = {}
    if slip:
        mesh = insert_interface(mesh, "lining", "joint", side="right")
        interfaces["joint"] = api.InterfaceSpec("joint", kn=1e9, ks=1.0)
        structures.add("joint")
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"rock": api.MaterialSpec.elastic("rock", EM, NUM)},
        region_material={1: "rock", 2: "rock"},
        fixities=(
            api.Fixity("x_axis", False, True),
            api.Fixity("y_axis", True, False),
            api.Fixity("liner_a", False, False, rz=True),
            api.Fixity("liner_b", False, False, rz=True),
        ),
        initial=api.InitialStress("field", field=(-K * P, -P, -0.5 * (1 + K) * P, 0.0)),
        stages=[
            api.Stage(
                "excavate_and_line",
                active_regions={1},
                active_structures=structures,
                loads=(api.EdgeLoad("outer_x", qn=K * P), api.EdgeLoad("outer_y", qn=P)),
            )
        ],
        liners={"liner": api.LinerSpec("liner", EL, NUL, A_L, I_L, 5 / 6 * A_L)},
        interfaces=interfaces,
    )
    return mesh, model


def _fit(mesh, res):
    blk = mesh.block("liner")
    X = mesh.coords[blk.conn].mean(axis=1)
    th = np.arctan2(X[:, 1], X[:, 0])
    F = res.last.beams["liner"]
    N = F[:, :, 0].mean(axis=1)
    M = F[:, :, 2].mean(axis=1)
    A = np.column_stack([np.ones_like(th), np.cos(2 * th)])
    return np.linalg.lstsq(A, N, rcond=None)[0], np.linalg.lstsq(A, M, rcond=None)[0]


@pytest.mark.parametrize("slip", [False, True])
def test_lined_tunnel_thrust_and_moment(slip):
    N0, N2, M2 = reference(slip)
    mesh, model = _model(slip)
    res = api.run(model)
    (n0, n2), (m0, m2) = _fit(mesh, res)
    scaleN = abs(N0) + abs(N2)
    assert abs(n0 - N0) / abs(N0) < 0.05, (n0, N0)
    assert abs(n2 - N2) / scaleN < 0.05, (n2, N2)
    assert abs(abs(m2) - abs(M2)) / abs(M2) < 0.05, (m2, M2)
    assert abs(m0) < 0.05 * abs(M2)

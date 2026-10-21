"""S1 — lined elastic tunnel, no-slip Einstein & Schwartz (1979).

Reference DOI: 10.1061/AJGEB6.0000786. Equations and parameter set independently
published by Itasca's verification example (see docs/phase3-verification.md).
Units kN, m, kPa. Analytical T is compression positive; core N is tension positive.
The model is a quarter plane-strain tunnel; far-field boundary is 20R or 40R.
"""

from __future__ import annotations

import numpy as np

from slipsurface.fe2d import api
from slipsurface.fe2d.mesh import plate_with_hole
from slipsurface.fe2d.mesh.structures import add_beams


def einstein_schwartz(th):
    R, P, K, E, nu, Es, nus, t = 5.0, 600.0, 0.5, 48000.0, 0.34, 25e6, 0.15, 0.125
    C = E * R * (1 - nus * nus) / (Es * t * (1 - nu * nu))
    F = E * R**3 * (1 - nus * nus) / (Es * (t**3 / 12) * (1 - nu * nu))
    a0 = C * F * (1 - nu) / (C + F + C * F * (1 - nu))
    beta = ((6 + F) * C * (1 - nu) + 2 * F * nu) / (3 * F + 3 * C + 2 * C * F * (1 - nu))
    b2 = C * (1 - nu) / (2 * (C * (1 - nu) + 4 * nu - 6 * beta - 3 * beta * C * (1 - nu)))
    a2 = beta * b2
    T = P * R / 2 * ((1 + K) * (1 - a0) + (1 - K) * (1 + 2 * a2) * np.cos(2 * th))
    M = P * R * R / 4 * (1 - K) * (1 - 2 * a2 + 2 * b2) * np.cos(2 * th)
    return T, M


def run(nr, nt, L):
    mesh = add_beams(plate_with_hole(5, L, nr, nt, grade=40), "hole", "liner")
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"s": api.MaterialSpec.elastic("s", 48000, 0.34)},
        region_material={1: "s"},
        liners={"liner": api.LinerSpec("liner", 25e6, 0.15, 0.125, 0.125**3 / 12, 5 * 0.125 / 6)},
        fixities=(api.Fixity("x_sym", False, True, True), api.Fixity("y_sym", True, False, True)),
        initial=api.InitialStress("field", field=(-300, -600, -306, 0)),
        stages=[
            api.Stage(
                "lined",
                active_structures={"liner"},
                loads=(api.EdgeLoad("outer_x", qn=300), api.EdgeLoad("outer_y", qn=600)),
            )
        ],
    )
    res = api.run(model)
    blk = mesh.block("liner")
    X = mesh.coords[blk.conn].mean(axis=1)
    th = np.arctan2(X[:, 1], X[:, 0])
    T, M = einstein_schwartz(th)
    f = res.last.beams["liner"].mean(axis=1)
    errors = np.array(
        [
            np.max(np.abs(f[:, 0] + T)) / np.max(np.abs(T)),
            np.max(np.abs(f[:, 2] - M)) / np.max(np.abs(M)),
        ]
    )
    return errors


def test_lined_tunnel_no_slip_mesh_and_domain_convergence():
    # Einstein--Schwartz: simultaneous installation/excavation, thin no-slip liner.
    # Refine the continuum and chordal beam mesh together. Both signed fields (N and M),
    # not only their maximum magnitudes, are checked over the entire quarter ring.
    coarse = run(8, 16, 100)
    medium = run(16, 32, 100)
    fine = run(24, 48, 100)
    distant = run(40, 80, 200)
    for error in (coarse, medium, fine, distant):
        assert np.all(error < 0.05), error
    assert np.all(medium < coarse), (coarse, medium)
    assert np.all(fine < medium), (medium, fine)
    print(
        f"S1 relative errors N/M: coarse={coarse}, medium={medium}, fine={fine}, distant={distant}"
    )

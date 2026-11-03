"""F7: independently derived Kirsch elastic cavity response under hydrostatic stress.

A circular hole with radius a in an infinite, isotropic plane-strain elastic
medium initially carries hydrostatic compression p0. After the hole boundary
has a pressure pi (p0 > pi), the stress increments in polar coordinates are

    delta_sigma_rr = +(p0-pi)*a**2/r**2
    delta_sigma_tt = -(p0-pi)*a**2/r**2
    u_r = -(p0-pi)*a**2/(2*G*r),  G=E/[2(1+nu)].

Sign convention: tension positive. This is an *infinite-domain* reference
compared against a large but finite square quarter-domain, not an assertion
that the finite outer boundary has the same exact analytical solution.
"""

from __future__ import annotations

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.mesh import plate_with_hole

RADIUS = 1.0
OUTER = 25.0
P0 = 100.0
PI = 10.0
E = 10000.0
NU = 0.25
G = E / (2 * (1 + NU))


def kirsch_radial_displacement(r: np.ndarray) -> np.ndarray:
    return -(P0 - PI) * RADIUS**2 / (2 * G * r)


def kirsch_radial_increment(r: np.ndarray) -> np.ndarray:
    return (P0 - PI) * RADIUS**2 / r**2


def build_elastic_cavity(nr: int, nt: int):
    mesh = plate_with_hole(RADIUS, OUTER, nr, nt, ElemType.T6, grade=30.0)
    return api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"rock": api.MaterialSpec.elastic("rock", E, NU)},
        region_material={1: "rock"},
        fixities=(
            api.Fixity("x_sym", False, True),
            api.Fixity("y_sym", True, False),
        ),
        initial=api.InitialStress("field", field=(-P0, -P0, -P0, 0.0)),
        stages=[
            api.Stage(
                "Elastic cavity pressure relaxation",
                loads=(
                    api.EdgeLoad("hole", qn=PI),
                    api.EdgeLoad("outer_x", qn=P0),
                    api.EdgeLoad("outer_y", qn=P0),
                ),
            )
        ],
    )


def radial_displacement(coords: np.ndarray, values: np.ndarray) -> np.ndarray:
    r = np.linalg.norm(coords, axis=1)
    return np.einsum("ij,ij->i", coords, values) / r


@pytest.mark.parametrize("nr,nt", [(12, 16), (20, 24), (28, 32)])
def test_kirsch_wall_displacement_three_mesh_resolutions(nr, nt):
    model = build_elastic_cavity(nr, nt)
    solved = api.run(model)
    nodes = model.mesh.nodes("hole")
    displacements = radial_displacement(
        model.mesh.coords[nodes], solved.last.u[nodes],
    )
    reference = float(kirsch_radial_displacement(np.array([RADIUS]))[0])
    assert reference < 0
    # The square domain is finite: allow truncation and discretization error.
    assert np.isfinite(displacements).all()
    assert np.mean(displacements) == pytest.approx(reference, rel=0.06)
    assert np.ptp(displacements) < 0.06 * abs(reference)


def test_kirsch_radial_stress_increment_is_balanced_by_hoop_stress():
    model = build_elastic_cavity(20, 24)
    solved = api.run(model)
    xg = solved.geom["soil"].xg.reshape(-1, 2)
    stress = solved.last.sig["soil"].reshape(-1, 4)
    r = np.linalg.norm(xg, axis=1)
    # Sample the well-resolved annulus, away from outer truncation.
    mask = (r > 1.5 * RADIUS) & (r < 4 * RADIUS)
    assert np.count_nonzero(mask) > 20
    nx, ny = xg[mask, 0] / r[mask], xg[mask, 1] / r[mask]
    sxx, syy, _szz, txy = stress[mask].T
    radial = nx * nx * sxx + ny * ny * syy + 2 * nx * ny * txy
    hoop = ny * ny * sxx + nx * nx * syy - 2 * nx * ny * txy
    predicted = kirsch_radial_increment(r[mask])
    # Compare increments from initial hydrostatic stress, not total stress.
    mean_rr_error = np.mean(np.abs(radial + P0 - predicted))
    mean_tt_error = np.mean(np.abs(hoop + P0 + predicted))
    assert mean_rr_error / np.mean(predicted) < 0.10
    assert mean_tt_error / np.mean(predicted) < 0.10

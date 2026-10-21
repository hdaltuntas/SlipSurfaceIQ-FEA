"""S4 preliminary structural checks for an unanchored sheet pile.

Two independent benchmarks: an exact Timoshenko/Winkler transfer solution, and
an idealized Rankine active/passive pressure diagram with a toe reaction.
Neither substitutes for the roadmap's coupled continuum-soil comparison against
the user's independent sheet-pile tool (see docs/phase3-verification.md).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.mesh import rectangle


def run(n):
    H, D = 5.0, 10.0
    L = H + D
    EI = 2e6
    GA = 4e6
    k = 20000.0
    gamma = 18.0
    ka = 1 / 3
    # z measures depth from free top; nodes ordered from top to toe.
    z = np.linspace(0, L, n + 1)
    base = rectangle(1, 1, 1, 1, etype=api.ElemType.Q4)
    off = base.nn
    coords = np.vstack([base.coords, np.column_stack([np.full(n + 1, 3.0), -z])])
    con = np.column_stack([off + np.arange(n), off + np.arange(1, n + 1)])
    blocks = [
        *base.blocks,
        api.ElementBlock(api.ElemType.BEAM2, con, np.zeros(n, dtype=int), "wall"),
    ]
    # lateral Winkler springs at wall nodes below excavation, tributary weights.
    weights = np.full(n + 1, L / n)
    weights[[0, -1]] *= 0.5
    # discontinuity at H: soil only below H, half weight at the interface.
    weights[z < H] = 0
    weights[np.isclose(z, H)] *= 0.5
    extra = []
    barcon = []
    ea = []
    for i in np.flatnonzero(weights):
        anchor = len(coords) + len(extra)
        extra.append([4.0, -z[i]])
        barcon.append([off + i, anchor])
        ea.append(k * weights[i])
    coords = np.vstack([coords, extra])
    bolts = {}
    for j, (conn, EA) in enumerate(zip(barcon, ea)):
        tag = f"s{j}"
        blocks.append(api.ElementBlock(api.ElemType.BAR2, np.array([conn]), np.array([0]), tag))
        bolts[tag] = api.BoltSpec(tag, EA, 1e12)
    mesh = api.Mesh(
        coords,
        blocks,
        {
            "fixed": np.r_[np.arange(off), np.arange(off + n + 1, len(coords))],
            "wall": off + np.arange(n + 1),
        },
        {},
    )
    # Consistent nodal forces for triangular active pressure in the exposed length.
    F = np.zeros(n + 1)
    for i in range(n):
        lo, hi = z[i], z[i + 1]
        if hi <= H + 1e-10:
            h = hi - lo
            q0, q1 = ka * gamma * lo, ka * gamma * hi
            F[i] += h * (2 * q0 + q1) / 6
            F[i + 1] += h * (q0 + 2 * q1) / 6
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"s": api.MaterialSpec.elastic("s", 1e4, 0)},
        region_material={1: "s"},
        fixities=(api.Fixity("fixed", True, True), api.Fixity("wall", False, True)),
        initial=api.InitialStress("none", active_structures=set(bolts) | {"wall"}),
        liners={"wall": api.LinerSpec("wall", 2e8, 0, 1, EI / 2e8, GA / 1e8)},
        bolts=bolts,
        stages=[
            api.Stage(
                "load",
                active_structures=set(bolts) | {"wall"},
                loads=tuple(api.PointLoad(off + i, fx=f) for i, f in enumerate(F) if f),
            )
        ],
    )
    r = api.run(model)
    # Independent exact piecewise state-space solution (matrix exponential).
    from scipy.linalg import expm

    def transfer(z, spring):
        A = np.zeros((6, 6))
        A[0, 1] = 1
        A[0, 3] = -1 / GA
        A[1, 2] = 1 / EI
        A[2, 3] = 1
        A[3, 0] = -spring
        A[3, 4] = 1
        A[4, 5] = 1
        return expm(A * z)

    T = transfer(H, 0)
    U = transfer(D, k)
    forcing = T[:4, 5] * ka * gamma
    end_matrix = U[:4, :4] @ T[:4, :4]
    end_forcing = U[:4, :4] @ forcing
    first = np.zeros(6)
    first[:2] = np.linalg.solve(end_matrix[2:4, :2], -end_forcing[2:4])
    first[5] = ka * gamma
    interface = T @ first
    interface[4:] = 0

    def ref_at(x):
        return np.column_stack(
            [
                (transfer(xx, 0) @ first)[:4] if xx <= H else (transfer(xx - H, k) @ interface)[:4]
                for xx in np.atleast_1d(x)
            ]
        )

    moment = r.last.beams["wall"].mean(axis=1)[:, 2]
    ref = ref_at(0.5 * (z[:-1] + z[1:]))[2]
    assert np.max(np.abs(moment - ref)) / np.max(np.abs(ref)) < 0.01
    assert abs(r.last.u[off, 0] - ref_at(0)[0, 0]) / abs(ref_at(0)[0, 0]) < 0.01
    assert np.max(np.abs(ref_at(L)[2:])) < 1e-8  # independent reference free toe
    reaction = r.last.reactions[:, 0]
    np.testing.assert_allclose(reaction.sum() + F.sum(), 0, atol=1e-8)
    np.testing.assert_allclose(np.sum(-coords[:, 1] * reaction) + np.sum(z * F), 0, atol=1e-7)
    print(
        f"S4-Winkler n={n}: Mmax={abs(moment).max():.6f}, reference={abs(ref).max():.6f}, "
        f"relative field error={np.max(abs(moment - ref)) / abs(ref).max():.6%}"
    )
    return np.max(abs(moment - ref)) / abs(ref).max()


def test_sheet_pile_on_winkler_springs_matches_exact_transfer_solution():
    coarse = run(60)
    fine = run(120)
    assert fine < 0.4 * coarse


@pytest.mark.parametrize("phi", [25.0, 30.0, 35.0])
def test_sheet_pile_rankine_pressure_moment_balance(phi):
    # Idealized active/passive pressure diagram with a concentrated reaction at the toe.
    # D solves moment equilibrium about the toe; this is a prescribed-pressure structural
    # benchmark, not a calibration of the independent Winkler model above.
    H, gamma = 5.0, 18.0
    ka = math.tan(math.pi / 4 - math.radians(phi) / 2) ** 2
    kp = 1 / ka
    D = H / ((kp / ka) ** (1 / 3) - 1)
    z = np.r_[np.linspace(0, H, 41), H + np.linspace(0, D, 61)[1:]]
    n = len(z) - 1
    base = rectangle(1, 1, 1, 1, etype=api.ElemType.Q4)
    off = base.nn
    coords = np.vstack([base.coords, np.column_stack([np.full(n + 1, 3.0), -z])])
    block = api.ElementBlock(
        api.ElemType.BEAM2,
        np.column_stack([off + np.arange(n), off + np.arange(1, n + 1)]),
        np.zeros(n, dtype=int),
        "wall",
    )
    mesh = api.Mesh(
        coords,
        (*base.blocks, block),
        {"soil": np.arange(off), "wall": off + np.arange(n + 1), "toe": np.array([off + n])},
        {},
    )
    pressure = gamma * (ka * z - kp * np.maximum(z - H, 0))
    F = np.zeros(n + 1)
    for i, h in enumerate(np.diff(z)):
        F[i] += h * (2 * pressure[i] + pressure[i + 1]) / 6
        F[i + 1] += h * (pressure[i] + 2 * pressure[i + 1]) / 6
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"s": api.MaterialSpec.elastic("s", 1e4, 0)},
        region_material={1: "s"},
        fixities=(
            api.Fixity("soil", True, True),
            api.Fixity("wall", False, True),
            api.Fixity("toe", True, False, True),
        ),
        liners={"wall": api.LinerSpec("wall", 2e8, 0, 1, 0.01, 0.1)},
        initial=api.InitialStress("none", active_structures={"wall"}),
        stages=[
            api.Stage(
                "rankine",
                active_structures={"wall"},
                loads=tuple(api.PointLoad(off + i, fx=f) for i, f in enumerate(F) if f),
            )
        ],
    )
    result = api.run(model)
    mid = (z[:-1] + z[1:]) / 2
    moment = gamma * (ka * mid**3 - kp * np.maximum(mid - H, 0) ** 3) / 6
    fe = result.last.beams["wall"].mean(axis=1)[:, 2]
    peak_z = H / (1 - math.sqrt(ka / kp))
    peak = gamma * (ka * peak_z**3 - kp * (peak_z - H) ** 3) / 6
    assert np.max(abs(fe - moment)) / peak < 0.01
    assert abs(np.max(fe) - peak) / peak < 0.01
    assert abs(result.last.reactions[off + n, 2]) < 1e-7
    np.testing.assert_allclose(result.last.reactions[:, 0].sum() + F.sum(), 0, atol=1e-7)

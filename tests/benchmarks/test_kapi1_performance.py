"""Kapı 1 performance criterion: 50k-node T6 linear elastic model solved in < 5 s.

Measured: element precompute + DOF map + CSR pattern + stiffness assembly + gravity
initial stage + one load stage (two factorisations). Run with ``pytest -m benchmark``.
"""

from __future__ import annotations

import time

import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.mesh import rectangle


@pytest.mark.benchmark
def test_50k_node_t6_under_5s():
    mesh = rectangle(100.0, 50.0, 112, 112)  # (2*112+1)^2 = 50 625 nodes
    assert mesh.nn >= 50_000
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"s": api.MaterialSpec.elastic("s", 3e4, 0.3, gamma=19.0)},
        region_material={1: "s"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        stages=[api.Stage("q", loads=(api.EdgeLoad("top", qn=100.0),))],
    )
    t0 = time.perf_counter()
    res = api.run(model)
    dt = time.perf_counter() - t0
    print(f"\n50k-node T6: {dt:.2f} s total; timings {res.initial.timings} {res.last.timings}")
    assert dt < 5.0


@pytest.mark.benchmark
def test_unstructured_50k_node_t6():
    """Delaunay/Ruppert mesh of a tunnel section (≈50k T6 nodes) + elastic solve."""
    from slipsurface.fe2d.mesh import DistanceSize, Domain, circle, unstructured_mesh

    ring = circle(0.0, -25.0, 5.0, 96)
    d = Domain().add_polygon(
        [(-50, -60), (50, -60), (50, 0), (-50, 0)], edge_names=["bottom", "right", "top", "left"]
    )
    d.add_polygon(ring, 2, name="tunnel")
    t0 = time.perf_counter()
    mesh = unstructured_mesh(d, h=DistanceSize(0.12, 2.6, 1.1, lines=[ring], closed=[True]))
    t_mesh = time.perf_counter() - t0
    assert mesh.nn >= 50_000
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"s": api.MaterialSpec.elastic("s", 3e4, 0.3, gamma=19.0)},
        region_material={1: "s", 2: "s"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        stages=[api.Stage("q", loads=(api.EdgeLoad("top", qn=100.0),))],
    )
    t0 = time.perf_counter()
    res = api.run(model)
    t_solve = time.perf_counter() - t0
    print(
        f"\nunstructured {mesh.nn} nodes: mesh {t_mesh:.2f} s, solve {t_solve:.2f} s; "
        f"timings {res.initial.timings} {res.last.timings}"
    )
    assert t_solve < 5.0
    assert t_mesh < 10.0

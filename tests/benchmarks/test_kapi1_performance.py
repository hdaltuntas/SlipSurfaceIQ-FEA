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

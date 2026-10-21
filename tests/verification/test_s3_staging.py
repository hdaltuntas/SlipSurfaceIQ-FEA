"""S3 — staged excavation in an elastic layer; Kapı 3 stage-splitting invariance.

* multi-stage excavation (3 lifts) ends in the same state as excavating everything in one
  stage (linear elasticity), difference < 1e-8;
* a stage split by ``load_split = alpha`` followed by a completion stage equals the
  unsplit stage, for several alpha;
* excavating and backfilling: refilled elements start stress free and the reported
  displacement of re-activated nodes starts from zero.
"""

from __future__ import annotations

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.mesh import Domain, unstructured_mesh

# soil region 1, pit lifts 2 (top) .. 4 (bottom)
LIFTS = [(-2.0, 0.0, 2), (-4.0, -2.0, 3), (-6.0, -4.0, 4)]


def _mesh():
    d = Domain().add_polygon([(0, -20), (30, -20), (30, 0), (0, 0)], 1,
                             edge_names=["bottom", "right", "top", "left"])  # fmt: skip
    for y0, y1, r in LIFTS:
        d.add_polygon([(0, y0), (6, y0), (6, y1), (0, y1)], r)
    return unstructured_mesh(d, h=1.0)


def _model(mesh, stages):
    return api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"s": api.MaterialSpec.elastic("s", 3e4, 0.3, gamma=19.0)},
        region_material={1: "s", 2: "s", 3: "s", 4: "s"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        initial=api.InitialStress("gravity"),
        stages=stages,
    )


def _compare(r1, r2, tol=1e-8):
    a, b = r1.last, r2.last
    m = ~np.isnan(a.u[:, 0])
    assert np.array_equal(m, ~np.isnan(b.u[:, 0]))
    assert np.abs(a.u[m] - b.u[m]).max() <= tol * np.abs(a.u[m]).max()
    s1, s2 = a.sig["soil"], b.sig["soil"]
    assert np.abs(s1 - s2).max() <= tol * np.abs(s1).max()


def test_multistage_excavation_equals_single_stage():
    mesh = _mesh()
    one = api.run(_model(mesh, [api.Stage("all", active_regions={1})]))
    multi = api.run(
        _model(
            mesh,
            [
                api.Stage("lift1", active_regions={1, 3, 4}),
                api.Stage("lift2", active_regions={1, 4}),
                api.Stage("lift3", active_regions={1}),
            ],
        )
    )
    _compare(one, multi)
    # the pit is empty: its nodes off the soil boundary have no displacement
    inner = (mesh.coords[:, 0] < 5.9) & (mesh.coords[:, 1] > -5.9)
    assert np.all(np.isnan(one.last.u[inner, 0]))
    assert not one.last.active["soil"][mesh.blocks[0].region > 1].any()
    # excavation unloading heaves the pit bottom
    bottom = (np.abs(mesh.coords[:, 1] + 6.0) < 1e-9) & (mesh.coords[:, 0] < 5.5)
    assert np.all(one.last.u[bottom, 1] > 0)


@pytest.mark.parametrize("alpha", [0.25, 0.4, 0.9])
def test_load_split_invariance(alpha):
    mesh = _mesh()
    full = api.run(_model(mesh, [api.Stage("exc", active_regions={1})]))
    split = api.run(
        _model(
            mesh,
            [
                api.Stage("relax", active_regions={1}, load_split=alpha),
                api.Stage("rest", active_regions={1}),
            ],
        )
    )
    assert split.stages[0].lam == alpha
    _compare(full, split)
    # the first stage carries alpha of the excavation displacement (linear elasticity)
    m = ~np.isnan(full.last.u[:, 0])
    assert np.allclose(split.stages[0].u[m], alpha * full.last.u[m], atol=1e-12)


def test_backfill_starts_stress_free():
    mesh = _mesh()
    res = api.run(
        _model(
            mesh,
            [
                api.Stage("dig", active_regions={1}),
                api.Stage("fill", active_regions={1, 4}, reset_displacements=True),
            ],
        )
    )
    blk = mesh.blocks[0]
    fill = blk.region == 4
    s = res.last.sig["soil"][fill]
    # refilled layer only carries its own weight (|sigma_v| <= gamma * 2 m)
    assert np.abs(s[..., 1]).max() <= 19.0 * 2.0 * 1.05
    nodes_fill = np.unique(blk.conn[fill])
    assert np.all(np.isfinite(res.last.u[nodes_fill, 0]))
    # the fill settles under its own weight
    top_fill = nodes_fill[np.abs(mesh.coords[nodes_fill, 1] + 4.0) < 1e-9]
    assert np.all(res.last.u[top_fill, 1] < 0)

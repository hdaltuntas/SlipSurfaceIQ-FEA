"""Prescribed homogeneous tension, elastic unloading and reloading at a common apex."""

from dataclasses import replace

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.errors import NonConvergence
from slipsurface.fe2d.fem.materials.mohr_coulomb import MohrCoulomb
from slipsurface.fe2d.mesh import rectangle


def _model(etype, cutoff):
    mesh = rectangle(1.0, 1.0, 2, 2, etype=etype)
    centre = int(np.flatnonzero(np.all(mesh.coords == [0.5, 0.5], axis=1))[0])
    for i in range(mesh.nn):
        mesh.node_sets[f"n{i}"] = np.array([i])
    soil = api.MaterialSpec.mohr_coulomb("sand", 3e4, 0.3, 0.0, 30.0, 0.0, sig_t=cutoff)
    return api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"sand": soil},
        region_material={1: "sand"},
        initial=api.InitialStress("field", field=(-10.0, -10.0, -10.0, 0.0)),
        stages=[
            api.Stage(
                name,
                displacements=tuple(
                    api.Displacement(f"n{i}", ux=None if i == centre else e * x, uy=e * y)
                    for i, (x, y) in enumerate(mesh.coords)
                ),
            )
            for name, e in [("tension", 4e-4), ("unload", 3e-4), ("reload", 4e-4)]
        ],
        settings=api.SolverSettings(tol_force=1e-10, tol_energy=1e-12, gauss_order="high"),
    )


@pytest.mark.parametrize(
    "etype", [api.ElemType.T3, api.ElemType.T6, api.ElemType.Q4, api.ElemType.Q8]
)
def test_explicit_zero_cutoff_follows_analytic_staged_stress_path(etype):
    m = _model(etype, 0.0)
    assert m.materials["sand"].params["sig_t"] == 0.0
    result = api.run(m)
    elastic = MohrCoulomb(3e4, 0.3, 0.0, 30.0, 0.0, sig_t=0.0)
    expected = [np.zeros(4), elastic._D @ np.array([-1e-4, -1e-4, 0.0, 0.0]), np.zeros(4)]
    for stage, stress, e in zip(result.stages, expected, [4e-4, 3e-4, 4e-4]):
        np.testing.assert_allclose(stage.u, e * m.mesh.coords, atol=1e-12)
        for values in stage.sig.values():
            np.testing.assert_allclose(values, np.broadcast_to(stress, values.shape), atol=1e-9)
            assert elastic.yield_function(values).max() < 1e-8
        assert all(np.all(flags != 255) for flags in stage.plastic.values())
        np.testing.assert_allclose(np.sum(stage.reactions, axis=0), 0.0, atol=1e-9)


def test_omitted_cutoff_cannot_accept_the_same_tension_path():
    with pytest.raises(NonConvergence) as caught:
        api.run(_model(api.ElemType.Q8, None))
    assert 0.0 <= caught.value.lam < 1.0
    assert caught.value.history.steps[-1].termination == "material_return"


@pytest.mark.parametrize("ratio", [0.0, 1e-8, 1e-6, 1e-4])
def test_apex_iteration_stiffness_follows_same_loading_unloading_path(ratio):
    m = _model(api.ElemType.Q8, 0.0)
    m.materials["sand"] = api.MaterialSpec.mohr_coulomb(
        "sand", 3e4, 0.3, 0, 30, 0, rankine_at_apex=True
    )
    m.settings = replace(m.settings, apex_stiffness_ratio=ratio)
    result = api.run(m)
    elastic = MohrCoulomb(3e4, 0.3, 0, 30, 0)
    expected = [np.zeros(4), elastic.elastic_D() @ [-1e-4, -1e-4, 0, 0], np.zeros(4)]
    for stage, stress, e in zip(result.stages, expected, [4e-4, 3e-4, 4e-4]):
        np.testing.assert_allclose(stage.u, e * m.mesh.coords, atol=1e-12)
        for values in stage.sig.values():
            np.testing.assert_allclose(values, np.broadcast_to(stress, values.shape), atol=1e-9)
        np.testing.assert_allclose(stage.reactions.sum(axis=0), 0, atol=1e-9)

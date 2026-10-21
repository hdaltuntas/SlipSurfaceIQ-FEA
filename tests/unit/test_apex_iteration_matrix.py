"""Optional quasi-Newton apex stiffness never replaces the stress derivative."""

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.fem.static import StaticSolver
from slipsurface.fe2d.io import model_from_dict, model_to_dict
from slipsurface.fe2d.mesh import rectangle


def _solver(c=0.0, cutoff=None):
    return StaticSolver(
        api.Model(
            analysis=api.Analysis.PLANE_STRAIN,
            mesh=rectangle(1.0, 1.0, 2, 2, api.ElemType.Q8),
            materials={
                "m": api.MaterialSpec.mohr_coulomb(
                    "m", 3e4, 0.3, c, 30, 0, sig_t=cutoff, rankine_at_apex=cutoff is None
                )
            },
            region_material={1: "m"},
            initial=api.InitialStress("none"),
            fixities=(api.Fixity("bottom", True, True),),
            settings=api.SolverSettings(apex_stiffness_ratio=1e-6),
        )
    )


@pytest.mark.parametrize("lower_cutoff", [False, True])
def test_apex_iteration_matrix_preserves_exact_tangents_and_residual(lower_cutoff):
    solver = _solver(c=10.0 if lower_cutoff else 0.0, cutoff=0.0 if lower_cutoff else None)
    state, _ = solver.initial_state()
    sysm, lay = solver.system, solver._layout
    du = np.zeros(sysm.dm.ndof)
    for comp in (0, 1):
        ids = sysm.dm.node_dofs[:, comp]
        present = ids >= 0
        du[ids[present]] = 1e-4 * solver.mesh.coords[present, comp]
    trial, force = solver.integrate(state, du, sysm, lay)
    originals = {k: d.copy() for k, d in trial.D.items()}
    exact_K = solver._stiffness(sysm, trial.D, trial.K)
    matrices = solver._iteration_tangents(sysm, trial.D, trial.sig, trial.flag, 1e-6)
    approximate_K = solver._stiffness(sysm, matrices, trial.K)
    elastic, structures = solver._elastic_DK(sysm)
    elastic_K = solver._stiffness(sysm, elastic, structures)
    if lower_cutoff:
        np.testing.assert_allclose(approximate_K.toarray(), exact_K.toarray())
    else:
        np.testing.assert_array_equal(exact_K.toarray(), 0)
        np.testing.assert_allclose(approximate_K.toarray(), 1e-6 * elastic_K.toarray(), atol=1e-14)
    for key in trial.D:
        np.testing.assert_array_equal(trial.D[key], originals[key])
    again, again_force = solver.integrate(state, du, sysm, lay)
    np.testing.assert_array_equal(again_force, force)
    for key in trial.sig:
        np.testing.assert_array_equal(again.sig[key], trial.sig[key])
    assert solver._iteration_tangents(sysm, trial.D, trial.sig, trial.flag, 0) is trial.D


def test_apex_options_survive_json_and_legacy_settings_default_to_exact():
    model = _solver().model
    doc = model_to_dict(model)
    loaded = model_from_dict(doc)
    assert loaded.settings.apex_stiffness_ratio == 1e-6
    material = loaded.materials["m"].with_strength_factor(1.5625)
    assert material.params["rankine_at_apex"]
    doc["settings"].pop("apex_stiffness_ratio")
    assert model_from_dict(doc).settings.apex_stiffness_ratio == 0


@pytest.mark.parametrize("ratio", [-1e-6, float("nan"), float("inf"), 1.1])
def test_invalid_apex_stiffness_ratio_is_rejected(ratio):
    with pytest.raises(ValueError, match="apex_stiffness_ratio"):
        api.SolverSettings(apex_stiffness_ratio=ratio)

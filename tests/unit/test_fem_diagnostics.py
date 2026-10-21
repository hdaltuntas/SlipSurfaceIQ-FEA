"""Audit quantities use known mappings/matrices; diagnostics must not change them."""

from dataclasses import replace

import numpy as np
import pytest
import scipy.sparse as sp

from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.fem.diagnostics import (
    jacobian_report,
    spatial_stress_report,
    stiffness_report,
)
from slipsurface.fe2d.mesh import rectangle


def test_jacobian_distinguishes_size_and_shape():
    mesh = rectangle(2.0, 1.0, 1, 1, etype=ElemType.Q4)
    a = jacobian_report(mesh)["soil"]
    b = jacobian_report(replace(mesh, coords=mesh.coords * 0.01))["soil"]
    assert a["min_detJ"] == pytest.approx(0.5)
    assert a["max_condition_2_J"] == pytest.approx(2.0)
    assert a["min_scaled_J"] == pytest.approx(1.0)
    assert b["min_detJ"] == pytest.approx(a["min_detJ"] * 1e-4)
    assert b["max_condition_2_J"] == pytest.approx(a["max_condition_2_J"])


def test_midnodes_are_used_and_degenerate_geometry_is_reported():
    mesh = rectangle(1.0, 1.0, 1, 1, etype=ElemType.Q8)
    coords = mesh.coords.copy()
    mid = mesh.blocks[0].conn[0, 6]
    coords[mid, 1] += 0.2
    report = jacobian_report(replace(mesh, coords=coords))["soil"]
    assert report["max_condition_2_J"] > 1.1
    # Corner area remains positive, but a displaced midnode folds the mapping.
    coords[mid, 1] = 0.0
    flat = jacobian_report(replace(mesh, coords=coords))["soil"]
    assert flat["nonpositive_detJ_gp"] >= 1
    assert flat["singular_J_gp"] >= 1
    assert flat["max_condition_2_J"] is None


def test_inverted_jacobian_is_not_hidden_by_absolute_value():
    mesh = rectangle(1.0, 1.0, 1, 1, etype=ElemType.Q8)
    coords = mesh.coords.copy()
    coords[mesh.blocks[0].conn[0, 6], 1] = -0.5
    report = jacobian_report(replace(mesh, coords=coords))["soil"]
    assert report["min_detJ"] < 0
    assert report["nonpositive_detJ_gp"] > 0


def test_positive_but_slender_element_has_large_jacobian_condition():
    mesh = rectangle(1.0, 1e-9, 1, 1, etype=ElemType.Q4)
    report = jacobian_report(mesh)["soil"]
    assert report["min_detJ"] > 0
    assert report["max_condition_2_J"] == pytest.approx(1e9)


def test_condition_number_reports_units_and_scaling_separately():
    K = sp.diags([1.0, 1e-8], format="csc")
    before = K.copy()
    report = stiffness_report(K)
    assert report["raw"]["condition_1_estimate"] == pytest.approx(1e8)
    assert report["diagonal_congruence"]["condition_1_estimate"] == pytest.approx(1.0)
    np.testing.assert_array_equal(K.toarray(), before.toarray())


def test_unsymmetric_and_indefinite_matrices_are_not_called_singular():
    K = np.array([[2.0, 3.0], [0.0, 1.0]])
    report = stiffness_report(K)
    assert report["raw"]["condition_1_estimate"] == pytest.approx(np.linalg.cond(K, 1))
    assert report["relative_asymmetry_1"] > 0
    indefinite = stiffness_report(np.diag([1.0, -2.0]))
    assert indefinite["raw"]["status"] == "factored"
    assert indefinite["nonpositive_diagonal"] == 1


def test_singular_matrix_is_explicit():
    report = stiffness_report([[1.0, 1.0], [1.0, 1.0]])
    assert report["raw"]["status"] == "factorization_failed"
    assert report["raw"]["condition_1_estimate"] is None


def test_condition_estimate_is_repeatable_and_preserves_global_rng():
    K = sp.diags([-np.ones(3), 3 * np.ones(4), -np.ones(3)], [-1, 0, 1])
    state = np.random.get_state()  # noqa: NPY002 - deliberately check the legacy global RNG
    a = stiffness_report(K)
    b = stiffness_report(K)
    assert a == b
    after = np.random.get_state()  # noqa: NPY002 - same global state used by SciPy's t>1 path
    assert state[0] == after[0] and state[2:] == after[2:]
    np.testing.assert_array_equal(state[1], after[1])


@pytest.mark.parametrize("K", [np.zeros((0, 0)), np.ones((2, 3)), [[np.nan]]])
def test_bad_matrix_rejected(K):
    with pytest.raises(ValueError):
        stiffness_report(K)


def test_spatial_stress_norm_uses_tensor_shear_and_fixed_neighborhoods():
    xg = np.array([[0.1, 0.0], [0.6, 0.0], [0.8, 0.0]])
    sig = np.array([[0.0, 0.0, 0.0, 2.0], [1.0, 0.0, 0.0, 0.0], [3.0, 0.0, 0.0, 0.0]])
    report = spatial_stress_report(
        xg, sig, np.array([1.0, 1.0, 3.0]), {"corner": [0.0, 0.0], "empty": [10.0, 0.0]}
    )
    assert report["corner"]["nearest_gp_stress_norm"] == pytest.approx(np.sqrt(8.0))
    assert report["corner"]["annulus_mean_stress_norm"] == pytest.approx(2.5)
    assert report["empty"]["max_stress_norm_in_radius"] is None
    assert report["empty"]["annulus_mean_stress_norm"] is None

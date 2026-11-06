"""Independent unilateral normal-contact tests; legacy interface dispatch is unchanged."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

import numpy as np
import pytest

from slipsurface.fe2d.core.enums import Analysis, ElemType
from slipsurface.fe2d.fem.unilateral_contact import (
    ContactStatus,
    UnilateralNormalContactGroup,
    normal_contact_response,
)
from slipsurface.fe2d.model.mesh import ElementBlock

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/f7_unilateral_contact_benchmark.py"
BENCH = runpy.run_path(str(SCRIPT))


def make_group(n=2, *, ne=1, kn=2000.0, initial_gap=0.0):
    face = np.array([[0., 0.], [4., 0.], [2., 0.]])[:n]
    coords = np.tile(np.vstack([face, face]), (ne, 1))
    conn = np.arange(2*n*ne).reshape(ne, 2*n)
    block = ElementBlock(ElemType.IFACE4 if n == 2 else ElemType.IFACE6,
                         conn, np.zeros(ne, dtype=int), "contact")
    return UnilateralNormalContactGroup(block, coords, kn=kn, initial_gap=initial_gap)


def test_hand_calculated_opening_reversal_then_real_reclosure():
    group = make_group()
    state = group.zero_state()
    normal = [0.006, -0.001, -0.006, 0.004]
    expected_gaps = [0.006, 0.005, -0.001, 0.003]
    expected_node_y = [0., 0., -4., 0.]  # weight=L/2=2, sigma=-2 kPa in compression
    for delta, gap, force_y in zip(normal, expected_gaps, expected_node_y):
        du = np.array([[0., 0., 0., 0., 0., delta, 0., delta]])
        trial, force, _, _ = group.integrate(state, np.array([0]), du)
        np.testing.assert_allclose(trial["gap"], gap, atol=1e-17)
        np.testing.assert_allclose(force[0, [5, 7]], force_y, atol=1e-12)
        state["gap"][:] = trial["gap"]
    assert state["gap"].min() > 0


def test_zero_gap_force_and_one_sided_derivatives_are_explicit():
    t, d, flag, energy = normal_contact_response(np.array([0.]), 2000.)
    assert t[0] == energy[0] == 0
    assert d[0] == 2000 and flag[0] == ContactStatus.TOUCHING
    eps = 1e-7
    closed = normal_contact_response(np.array([-eps]), 2000.)[0]
    opened = normal_contact_response(np.array([eps]), 2000.)[0]
    assert (t[0]-closed[0])/eps == pytest.approx(2000.)
    assert (opened[0]-t[0])/eps == 0


@pytest.mark.parametrize("n", [2, 3])
def test_mixed_open_and_closed_integration_points(n):
    group = make_group(n)
    gaps = np.array([-0.002, 0.003, -0.001])[:n]
    du = np.zeros((1, 4*n))
    du[0, 2*n+1::2] = gaps
    trial, forces, matrix, flags = group.integrate(group.zero_state(), np.array([0]), du)
    weights = np.array([2., 2.] if n == 2 else [2/3, 2/3, 8/3])
    expected = weights * np.array([-4., 0., -2.])[:n]
    np.testing.assert_allclose(forces[0, 2*n+1::2], expected)
    assert flags[0, 1] == ContactStatus.OPEN
    assert not matrix[0, 2*(n+1)+1].any()
    assert group.stored_energy(trial)[0] >= 0


@pytest.mark.parametrize("n", [2, 3])
def test_rigid_motion_and_tangential_motion_do_not_create_force(n):
    group = make_group(n)
    for du in (np.tile([0.3, -0.01], 2*n)[None, :],
               np.array([[0.]* (2*n) + [0.2, 0.]*n])):
        trial, f, _, _ = group.integrate(group.zero_state(), np.array([0]), du)
        np.testing.assert_allclose(trial["gap"], 0, atol=1e-16)
        np.testing.assert_allclose(f, 0, atol=1e-12)


def test_initial_clearance_is_not_a_plastic_offset():
    group = make_group(initial_gap=0.003)
    state = group.zero_state()
    for target, expected in ((-0.002, 0.), (-0.004, -4.)):
        du = np.array([[0., 0., 0., 0., 0., target, 0., target]])
        trial, f, _, _ = group.integrate(state, np.array([0]), du)
        assert f[0, 5] == pytest.approx(expected, abs=1e-12)
        np.testing.assert_allclose(state["gap"], 0.003)  # trials never auto-commit
        np.testing.assert_allclose(trial["gap"], target+0.003)


def test_subset_order_reset_and_empty_selection():
    group = make_group(ne=3, initial_gap=0.002)
    state = group.zero_state()
    du = np.zeros((2, 8))
    du[:, [5, 7]] = [[-0.003], [0.002]]
    ids = np.array([2, 0])
    trial, _, _, _ = group.integrate(state, ids, du)
    state["gap"][ids] = trial["gap"]
    np.testing.assert_allclose(state["gap"][:, 0], [0.004, 0.002, -0.001])
    group.activate(state, np.array([2]))
    np.testing.assert_allclose(state["gap"][:, 0], [0.004, 0.002, 0.002])
    out = group.integrate(state, np.array([], dtype=int), np.empty((0, 8)))
    assert out[1].shape == (0, 8) and out[2].shape == (0, 8, 8)


def test_selected_path_subdivision_does_not_erase_gap_memory():
    group = make_group()
    for target in (0.006, 0.005, -0.001, 0.004):
        outputs = []
        for subdivisions in (1, 4, 32):
            state = group.zero_state()
            du = np.zeros((1, 8))
            du[0, [5, 7]] = target/subdivisions
            for _ in range(subdivisions):
                trial, force, _, _ = group.integrate(state, np.array([0]), du)
                state["gap"][:] = trial["gap"]
            outputs.append((state["gap"].copy(), force.copy()))
        for gap, force in outputs[1:]:
            np.testing.assert_allclose(gap, outputs[0][0], atol=1e-16)
            np.testing.assert_allclose(force, outputs[0][1], atol=1e-11)


@pytest.mark.parametrize("etype", ["IFACE4", "IFACE6"])
@pytest.mark.parametrize("angle", [0., 37., -63.])
@pytest.mark.parametrize("gap0", [0., 0.002])
def test_history_full_tangent_retry_and_independent_energy(etype, angle, gap0):
    result = BENCH["run_history"](etype, angle, gap0)
    assert result["status"] == "passed"
    assert result["step_count"] == 9


@pytest.mark.parametrize("etype", ["IFACE4", "IFACE6"])
@pytest.mark.parametrize("angle", [0., 37., -63.])
@pytest.mark.parametrize("gap0", [0., 0.002])
def test_force_driven_assembled_contact_with_parallel_spring(etype, angle, gap0):
    result = BENCH["run_force_controlled"](etype, angle, gap0)
    assert result["status"] == "passed"
    assert len(result["steps"]) == 7


@pytest.mark.parametrize("bad", [True, -1., 0., float("nan"), float("inf"), [2000.], "2000"])
def test_invalid_stiffness_rejected(bad):
    with pytest.raises(ValueError):
        normal_contact_response([0.], bad)


@pytest.mark.parametrize("bad", [True, -0.001, float("nan"), float("inf"), [0.], "0"])
def test_invalid_initial_gap_rejected(bad):
    with pytest.raises(ValueError):
        make_group(initial_gap=bad)


@pytest.mark.parametrize("bad", [[True], [float("nan")], [float("inf")], [1j], ["0"]])
def test_invalid_gap_values_rejected(bad):
    with pytest.raises(ValueError):
        normal_contact_response(bad, 2000.)


@pytest.mark.parametrize("ids", [[0, 0], [-1], [1], [0.0], [True], [[0]]])
def test_invalid_element_selection_rejected(ids):
    group = make_group()
    with pytest.raises(ValueError):
        group.integrate(group.zero_state(), np.array(ids), np.zeros((1, 8)))


@pytest.mark.parametrize("state", [{}, {"t": np.zeros((1, 2, 2))},
                                    {"gap": np.zeros((2, 1))},
                                    {"gap": np.full((1, 2), np.nan)}])
def test_invalid_or_legacy_traction_state_is_not_accepted(state):
    with pytest.raises(ValueError):
        make_group().integrate(state, np.array([0]), np.zeros((1, 8)))


def test_hydraulics_nonfinite_displacement_and_wrong_shapes_are_rejected():
    g = make_group()
    for increment, water in ((np.zeros((1, 8)), np.zeros((1, 2))),
                             (np.zeros(8), None), (np.full((1, 8), np.nan), None)):
        with pytest.raises(ValueError):
            g.integrate(g.zero_state(), np.array([0]), increment, water)


def test_unsupported_geometry_and_analysis_are_rejected():
    n = 3
    face = np.array([[0., 0.], [4., 0.], [2., 0.]])
    coords = np.vstack([face, face])
    block = ElementBlock(ElemType.IFACE6, np.arange(2*n)[None, :], np.array([0]), "joint")
    with pytest.raises(ValueError, match="plane strain"):
        UnilateralNormalContactGroup(block, coords, kn=2000., analysis=Analysis.AXISYMMETRIC)
    curves = coords.copy()
    curves[[2, 5], 1] = 0.1
    with pytest.raises(ValueError, match="straight"):
        UnilateralNormalContactGroup(block, curves, kn=2000.)
    separated = coords.copy()
    separated[3:, 1] = 0.1
    with pytest.raises(ValueError, match="coincide"):
        UnilateralNormalContactGroup(block, separated, kn=2000.)
    with pytest.raises(ValueError, match="Degenerate"):
        UnilateralNormalContactGroup(block, np.zeros_like(coords), kn=2000.)


def test_overflow_rejected_instead_of_nan_or_inf_acceptance():
    with pytest.raises(ValueError):
        normal_contact_response([-1e308], 1e308)


@pytest.mark.parametrize("corrupt", ["gap", "force", "tangent", "status", "state", "nan"])
def test_benchmark_fails_under_deliberate_kernel_corruption(monkeypatch, corrupt):
    original = UnilateralNormalContactGroup.integrate

    def broken(self, state, ids, du_e, p=None):
        trial, force, tangent, status = original(self, state, ids, du_e, p)
        if corrupt == "gap":
            trial["gap"] += 0.1
        elif corrupt == "force":
            force += 1.0
        elif corrupt == "tangent":
            tangent += 2.0
        elif corrupt == "status":
            status[:] = 99
        elif corrupt == "state":
            state["gap"] += 0.1
        else:
            force[:] = np.nan
        return trial, force, tangent, status

    monkeypatch.setattr(UnilateralNormalContactGroup, "integrate", broken)
    assert BENCH["run_history"]()["status"] == "failed"


def test_cli_report_is_strict_json_and_success(tmp_path, monkeypatch, capsys):
    out = tmp_path / "contact.json"
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--output", str(out)])
    assert BENCH["main"]() == 0
    import json

    data = json.loads(out.read_text())
    assert data["history_step_count"] == 108
    assert data["force_controlled_step_count"] == 84
    assert "NaN" not in out.read_text()
    assert "passed" in capsys.readouterr().out

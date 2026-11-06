"""Committed-history regressions; contact-gap equivalence is a separate question."""

from __future__ import annotations

import copy
import json
import runpy
import sys
from pathlib import Path

import numpy as np
import pytest

_MODULE = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "scripts" / "f7_interface_history_benchmark.py")
)
run_history = _MODULE["run_history"]
history_cases = _MODULE["history_cases"]
reference_step = _MODULE["reference_step"]
contact_gap_comparison = _MODULE["contact_gap_comparison"]


@pytest.mark.parametrize("case", history_cases(), ids=lambda c: c["name"])
@pytest.mark.parametrize("element", ["IFACE4", "IFACE6"])
@pytest.mark.parametrize("angle", [0.0, 37.0, -63.0])
def test_committed_history_forces_tangents_and_trial_isolation(case, element, angle):
    result = run_history(case, element_type=element, angle_deg=angle)
    assert result["status"] == "passed", result
    assert result["step_count"] == len(case["steps"])
    assert all(row["uncommitted_trials_leave_state_unchanged"] for row in result["results"])
    assert all(row["flags_match"] for row in result["results"])
    json.dumps(result, allow_nan=False)


def test_hand_calculated_cyclic_shear_retains_residual_stress():
    rows = run_history(history_cases()[0])["results"]
    # ks=1000, kn=2000, tan(phi)=1/2, c=5: strength at sigma=-20 is 15.
    for index, expected in ((2, [15.0, -20.0]), (3, [10.0, -20.0]),
                            (4, [-5.0, -20.0]), (5, [-15.0, -20.0])):
        np.testing.assert_allclose(rows[index]["reference"]["traction"], expected, atol=1e-12)
    assert rows[5]["total_jump_m"][0] == 0.0
    assert rows[5]["observed_traction_kpa"][0][0] == pytest.approx(-15.0)


def test_hand_calculated_dilatant_compression_and_unloading():
    rows = run_history(history_cases()[1])["results"]
    # lambda=(40 - 10 - 5)/(1000 + 2000/8)=0.02.
    np.testing.assert_allclose(rows[2]["reference"]["traction"], [20.0, -30.0])
    np.testing.assert_allclose(rows[2]["reference_plastic_jump_m"], [0.02, 0.005])
    np.testing.assert_allclose(rows[3]["reference"]["traction"], [15.0, -30.0])
    np.testing.assert_allclose(rows[4]["reference"]["traction"], [0.0, -30.0], atol=1e-12)


def test_corner_then_unloading_then_reverse_shear():
    rows = run_history(history_cases()[3])["results"]
    np.testing.assert_allclose(rows[1]["reference"]["traction"], [4.5, 1.0])
    np.testing.assert_allclose(rows[2]["reference"]["traction"], [2.5, -1.0])
    np.testing.assert_allclose(rows[3]["reference"]["traction"], [-11.9, -13.8])


@pytest.mark.parametrize("name", ["cyclic_frictional_shear", "cyclic_dilatant_shear",
                                  "tensile_cap_opening_reversal"])
@pytest.mark.parametrize("element", ["IFACE4", "IFACE6"])
def test_selected_straight_path_substeps_match_independent_endpoint_reference(name, element):
    case = next(c for c in history_cases() if c["name"] == name)
    reference_rows = run_history(case, element_type=element)["results"]
    n = 2 if element == "IFACE4" else 3
    loc = [0.0, 4.0] if n == 2 else [0.0, 4.0, 2.0]
    face = np.column_stack([loc, np.zeros(n)])
    block = _MODULE["ElementBlock"](_MODULE["ElemType"][element],
                                     np.arange(2 * n)[None], np.array([0]), "joint")
    spec = _MODULE["InterfaceSpec"](
        "joint", kn=case["kn"], ks=case["ks"], c=case["cohesion"],
        phi=case["phi"], psi=case["psi"], sig_t=case["tensile_cap"],
    )
    group = _MODULE["InterfaceGroup"](block, np.vstack([face, face]), spec,
                                      _MODULE["Analysis"].PLANE_STRAIN)
    state, ids, previous = group.zero_state(), np.array([0]), np.zeros(2)
    for target, reference in zip(case["steps"], reference_rows):
        current = np.asarray(target[:2])
        du = np.zeros((1, 4 * n))
        du[0, 2 * n:] = np.tile((current - previous) / 4, n)
        for _ in range(4):
            updated = group.integrate(state, ids, du, None)[0]
            state["t"][ids] = updated["t"]
        np.testing.assert_allclose(state["t"][0], np.tile(reference["reference"]["traction"],
                                                         (n, 1)), atol=1e-10, rtol=1e-10)
        previous = current


@pytest.mark.parametrize("corruption", ["reset_history", "mutate_state", "traction", "force",
                                        "tangent", "flags", "nan"])
def test_history_or_output_corruption_fails_instead_of_looking_green(monkeypatch, corruption):
    group_type = _MODULE["InterfaceGroup"]
    original = group_type.integrate

    def damaged(self, state, ids, du, p):
        source = self.zero_state() if corruption == "reset_history" else state
        updated, force, tangent, flags = original(self, source, ids, du, p)
        if corruption == "mutate_state":
            state["t"] += 0.01
        elif corruption == "traction":
            updated["t"] += 0.25
        elif corruption == "force":
            force[0, 0] += 1.0
        elif corruption == "tangent":
            tangent[0, 0, 0] += 1.0
        elif corruption == "flags":
            flags[:] = 0
        elif corruption == "nan":
            updated["t"][0, 0, 0] = np.nan
        return updated, force, tangent, flags

    monkeypatch.setattr(group_type, "integrate", damaged)
    result = run_history(history_cases()[0])
    assert result["status"] == "failed"
    json.dumps(result, allow_nan=False)


def test_normal_cap_is_not_certified_as_unilateral_geometric_contact():
    result = run_history(history_cases()[2])
    assert result["status"] == "passed"  # implemented elastoplastic law only
    diagnostic = contact_gap_comparison(result)
    assert diagnostic["status"] == "not_equivalent"
    point = diagnostic["points"][3]
    assert point["geometric_gap_m"] == pytest.approx(0.005)
    assert point["unbonded_contact_normal_kpa"] == 0.0
    np.testing.assert_allclose(point["native_normal_kpa"], [-2.0, -2.0])
    assert "not a passed physical" in diagnostic["warning"]


def test_nonfinite_gap_result_stays_incomplete():
    history = run_history(history_cases()[2])
    history["results"][3]["observed_traction_kpa"] = None
    result = contact_gap_comparison(history)
    assert result["status"] == "incomplete"
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("jump,memory", [([np.nan, 0], [0, 0]), ([0], [0, 0]),
                                         ([0, 0], [np.inf, 0])])
def test_invalid_reference_history_inputs_rejected(jump, memory):
    with pytest.raises(ValueError):
        reference_step(history_cases()[0], jump, memory, "elastic", 1)


@pytest.mark.parametrize("arguments", [{"length": 0}, {"length": np.nan},
                                      {"angle_deg": np.inf}, {"element_type": "Q4"}])
def test_invalid_history_geometry_rejected(arguments):
    with pytest.raises(ValueError):
        run_history(history_cases()[0], **arguments)


def test_wrong_branch_is_not_silently_projected():
    with pytest.raises(ValueError, match="inadmissible"):
        reference_step(history_cases()[0], [0.04, -0.01], [0.0, 0.0], "elastic", 1)


def test_empty_history_rejected():
    case = copy.deepcopy(history_cases()[0])
    case["steps"] = []
    with pytest.raises(ValueError, match="Nonempty"):
        run_history(case)


@pytest.mark.parametrize("require_contact,exit_code", [(False, 0), (True, 1)])
def test_cli_preserves_evidence_and_contact_requirement(monkeypatch, tmp_path, capsys,
                                                       require_contact, exit_code):
    main = _MODULE["main"]
    summary = {"status": "passed", "unilateral_contact_gap_comparison": {
        "status": "not_equivalent"}, "physical_validation": "not_established"}
    monkeypatch.setitem(main.__globals__, "run_benchmark", lambda: copy.deepcopy(summary))
    output = tmp_path / "history.json"
    args = ["history", "--output", str(output)]
    if require_contact:
        args.append("--require-unilateral-contact")
    monkeypatch.setattr(sys, "argv", args)
    assert main() == exit_code
    assert json.loads(output.read_text())["requested_contract_passed"] == (exit_code == 0)
    assert capsys.readouterr().out

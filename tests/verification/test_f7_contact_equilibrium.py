"""Bounded contact equilibrium: actual solutions, independent references, corruption."""

from __future__ import annotations

import copy
import json
import pickle
import runpy
import sys
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.post.contact_equilibrium import (
    UnsupportedContactBudget,
    contact_equilibrium_by_stage,
    contact_stage_equilibrium,
)

_ROOT = Path(__file__).resolve().parents[2]
_LAYER = runpy.run_path(str(_ROOT / "scripts/f7_contact_static_benchmark.py"))
_BENCH = runpy.run_path(str(_ROOT / "scripts/f7_contact_equilibrium_benchmark.py"))


@lru_cache(maxsize=20)
def _solved(etype="IFACE4", gap=0.0, mode="force"):
    model, _ = _LAYER["build_model"](element_type=etype, initial_gap=gap, mode=mode)
    return api.run(model)


@pytest.fixture
def result():
    return copy.deepcopy(_solved())


@pytest.mark.parametrize("etype", ["IFACE4", "IFACE6"])
@pytest.mark.parametrize("gap", [0.0, 0.002])
@pytest.mark.parametrize("mode", ["force", "displacement"])
def test_all_existing_native_histories_balance(etype, gap, mode):
    result = _solved(etype, gap, mode)
    report = contact_equilibrium_by_stage(result)
    assert report["status"] == "passed", report
    assert report["stage_count"] == 7
    for row in report["stages"]:
        assert row["checks"]["nodal_force_kn_per_m"]["status"] == "passed"
        assert len(row["partitions"]) == 2
        assert row["partitions"][0]["kind"] == "continuum_component"
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("etype", ["IFACE4", "IFACE6"])
@pytest.mark.parametrize("gap", [0.0, 0.002])
@pytest.mark.parametrize("turned", [False, True])
def test_eccentric_edge_and_point_loads_match_independent_force_and_moment(etype, gap, turned):
    model, references = _BENCH["build_loaded_model"](
        element_type=etype, initial_gap=gap, quarter_turn=turned
    )
    result = api.run(model)
    report = contact_equilibrium_by_stage(result)
    assert report["status"] == "passed", report
    assert report["stage_count"] == 6
    for row, expected in zip(report["stages"], references):
        np.testing.assert_allclose(row["external_resultant"], expected, atol=1e-12)
        np.testing.assert_allclose(row["reaction_resultant"], -np.array(expected), atol=1e-8)
    off = report["stages"][3]
    assert off["checks"]["gap_pressure_law_kpa"]["status"] == "not_applicable"
    assert off["partitions"][0]["contact_action"] == [0.0, 0.0, 0.0]
    assert report["stages"][4]["checks"]["gap_pressure_law_kpa"]["status"] == "passed"


def test_origin_translation_is_correct_for_both_force_systems(result):
    one = contact_stage_equilibrium(result, 3)
    two = contact_stage_equilibrium(result, 3, origin=(4.0, -3.0))
    for key in ("external_resultant", "reaction_resultant"):
        a, b = one[key], two[key]
        assert b[:2] == pytest.approx(a[:2])
        assert b[2] == pytest.approx(a[2] - 4 * a[1] - 3 * a[0])
    assert two["status"] == "passed"


def test_balanced_false_reactions_cannot_hide_behind_global_zero(result):
    st = result.stages[3]
    base = result.model.mesh.nodes("base")[0]
    top = result.model.mesh.nodes("top")[0]
    st.reactions[base, 1] += 2.0
    st.reactions[top, 1] -= 2.0
    report = contact_stage_equilibrium(result, 3)
    assert report["checks"]["global_force_kn_per_m"]["status"] == "passed"
    assert report["status"] == "failed"
    assert report["checks"]["nodal_force_kn_per_m"]["status"] == "failed"
    assert any(p["status"] == "failed" for p in report["partitions"])


def test_free_node_reaction_detected_even_when_global_resultants_cancel(result):
    block = result.model.mesh.block("contact")
    first, second = int(block.conn[0, 0]), int(block.conn[0, 2])
    result.stages[3].reactions[first, 1] -= 1.0
    result.stages[3].reactions[second, 1] += 1.0
    row = contact_stage_equilibrium(result, 3)
    assert row["checks"]["global_force_kn_per_m"]["status"] == "passed"
    assert row["checks"]["global_moment_knm_per_m"]["status"] == "passed"
    assert row["checks"]["reaction_on_free_or_inactive_dof"]["status"] == "failed"


def test_corrupt_pressure_cancels_globally_but_fails_nodally_and_in_law(result):
    result.stages[3].interfaces["contact"][..., 1] -= 1.0
    row = contact_stage_equilibrium(result, 3)
    assert row["checks"]["global_force_kn_per_m"]["status"] == "passed"
    assert row["checks"]["gap_pressure_law_kpa"]["status"] == "failed"
    assert row["checks"]["nodal_force_kn_per_m"]["status"] == "failed"


def test_corrupt_bulk_stress_cannot_pass_a_global_only_audit(result):
    key = next(iter(result.stages[3].sig))
    result.stages[3].sig[key][..., 1] += 3.0
    row = contact_stage_equilibrium(result, 3)
    assert row["checks"]["global_force_kn_per_m"]["status"] == "passed"
    assert row["status"] == "failed"


def test_zero_net_force_couple_is_a_moment_failure(result):
    nodes = result.model.mesh.nodes("top")
    result.stages[3].reactions[nodes[0], 1] += 1.0
    result.stages[3].reactions[nodes[-1], 1] -= 1.0
    row = contact_stage_equilibrium(result, 3)
    assert row["checks"]["global_force_kn_per_m"]["status"] == "passed"
    assert row["checks"]["global_moment_knm_per_m"]["status"] == "failed"


@pytest.mark.parametrize("field", ["contact_gap", "contact_status", "interfaces", "sig", "active"])
def test_missing_evidence_is_invalid_not_unsupported_or_pass(result, field):
    getattr(result.stages[3], field).clear()
    report = contact_equilibrium_by_stage(result)
    assert report["status"] == "failed"
    assert report["stages"][3]["status"] == "invalid"
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize(
    "bad",
    [
        "nan_reaction",
        "nan_stress",
        "nonzero_pore",
        "false_activity",
        "wrong_gap",
        "wrong_name",
        "wrong_lambda",
        "moment_reaction",
    ],
)
def test_invalid_or_corrupted_snapshots_never_pass(result, bad):
    st = result.stages[3]
    soil = result.model.mesh.continuum_blocks()[0].tag
    if bad == "nan_reaction":
        st.reactions[0, 0] = np.nan
    elif bad == "nan_stress":
        st.sig[soil][0, 0, 1] = np.nan
    elif bad == "nonzero_pore":
        st.pore[soil] = np.ones(st.sig[soil].shape[:-1])
    elif bad == "false_activity":
        st.active["contact"][:] = False
    elif bad == "wrong_gap":
        st.contact_gap["contact"] *= 2.0
    elif bad == "wrong_name":
        st.name = "not_this_stage"
    elif bad == "wrong_lambda":
        st.lam = 0.5
    else:
        st.reactions[0, 2] = 0.1
    report = contact_equilibrium_by_stage(result)
    assert report["status"] == "failed"
    assert report["stages"][3]["status"] in ("failed", "invalid")
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize(
    "bad",
    [
        "partial",
        "gravity",
        "wet",
        "seismic",
        "material",
        "excavation",
        "initial_topology",
        "goodman",
        "method",
    ],
)
def test_out_of_scope_is_explicit_not_weakened_acceptance(result, bad):
    model = result.model
    if bad == "gravity":
        model.initial = replace(model.initial, mode="gravity")
    elif bad == "initial_topology":
        model.initial = replace(model.initial, active_regions=set())
    elif bad == "goodman":
        model.interfaces["contact"] = api.InterfaceSpec("contact", 2000.0, 0.0)
    elif bad == "method":
        model.settings = replace(model.settings, method="mNR")
    else:
        value = {
            "partial": {"load_split": 0.5},
            "wet": {"water": api.WaterCondition("piezo_line", np.array([[0.0, 2.0], [2.0, 2.0]]))},
            "seismic": {"seismic_kh": 0.1},
            "material": {"material_override": {1: "solid"}},
            "excavation": {"active_regions": set()},
        }[bad]
        model.stages[0] = replace(model.stages[0], **value)
    with pytest.raises(UnsupportedContactBudget):
        contact_stage_equilibrium(result, 0)
    assert contact_equilibrium_by_stage(result)["stages"][0]["status"] == "unsupported"


@pytest.mark.parametrize("origin", [(True, 0), (np.nan, 0), (0,), ("1", "2"), (np.inf, 2)])
def test_invalid_origin_rejected(result, origin):
    with pytest.raises(ValueError):
        contact_stage_equilibrium(result, 0, origin=origin)


@pytest.mark.parametrize("index", [-1, 99, True, "0", 0.0])
def test_invalid_index_rejected(result, index):
    with pytest.raises(ValueError):
        contact_stage_equilibrium(result, index)


@pytest.mark.parametrize("tol", [0.0, -1.0, np.nan, np.inf, True, "1e-8"])
def test_invalid_tolerance_rejected(result, tol):
    with pytest.raises(ValueError):
        contact_stage_equilibrium(result, 0, force_atol=tol)


def test_duplicate_names_do_not_replace_stage_identity(result):
    for i, stage in enumerate(result.stages):
        stage.name = "same"
        result.model.stages[i] = replace(result.model.stages[i], name="same")
    report = contact_equilibrium_by_stage(result)
    assert report["status"] == "passed"
    assert [r["stage_index"] for r in report["stages"]] == list(range(7))


def test_postprocessing_never_mutates_the_result_or_calls_native_contact(result, monkeypatch):
    from slipsurface.fe2d.fem.unilateral_contact import StagedNormalContactGroup

    def forbidden(*args, **kwargs):
        pytest.fail("Audit must not execute native contact integration")

    before = pickle.dumps(result)
    monkeypatch.setattr(StagedNormalContactGroup, "integrate", forbidden)
    assert contact_equilibrium_by_stage(result)["status"] == "passed"
    assert pickle.dumps(result) == before


@pytest.mark.parametrize("fmt", ["h5", "ssproj"])
def test_snapshot_roundtrip_preserves_equilibrium_evidence(result, tmp_path, fmt):
    path = tmp_path / ("contact." + fmt)
    if fmt == "h5":
        api.save_results(result, path)
        restored = api.load_results(path)
    else:
        api.save_project(result.model, path, result)
        restored = api.load_project(path).results
    assert contact_equilibrium_by_stage(restored) == contact_equilibrium_by_stage(result)


def test_incomplete_stage_sequence_and_empty_report_are_not_success(result):
    result.stages.pop()
    report = contact_equilibrium_by_stage(result)
    assert report["status"] == "failed"
    assert all(r["status"] == "invalid" for r in report["stages"])
    result.stages.clear()
    assert contact_equilibrium_by_stage(result)["status"] == "failed"


@pytest.mark.parametrize("status,exit_code", [("passed", 0), ("failed", 1)])
def test_cli_preserves_evidence_and_exit_contract(tmp_path, monkeypatch, status, exit_code):
    main = _BENCH["main"]
    monkeypatch.setitem(main.__globals__, "run_benchmark", lambda: {"status": status})
    path = tmp_path / "evidence.json"
    monkeypatch.setattr(sys, "argv", ["benchmark", "--output", str(path)])
    assert main() == exit_code
    assert json.loads(path.read_text())["status"] == status

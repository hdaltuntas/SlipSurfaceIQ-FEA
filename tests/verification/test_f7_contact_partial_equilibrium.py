"""Fixed-topology load-split contact history: references, rejection and corruption."""

from __future__ import annotations

import copy
import json
import pickle
import runpy
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.post.contact_equilibrium import contact_equilibrium_by_stage
from slipsurface.fe2d.post.contact_partial_equilibrium import contact_partial_equilibrium_by_stage

_BENCH = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts"
                            / "f7_contact_partial_benchmark.py"))


@lru_cache(maxsize=20)
def _solved(etype="IFACE4", gap=0.0, mode="force"):
    model, _, _ = _BENCH["build_partial_layer"](element_type=etype, initial_gap=gap, mode=mode)
    return api.run(model)


@pytest.fixture
def result():
    return copy.deepcopy(_solved())


@pytest.mark.parametrize("etype", ["IFACE4", "IFACE6"])
@pytest.mark.parametrize("gap", [0.0, 0.002])
@pytest.mark.parametrize("mode", ["force", "displacement", "mixed"])
def test_partial_layers_match_exact_force_gap_and_reaction_history(etype, gap, mode):
    row = _BENCH["run_layer_case"](element_type=etype, initial_gap=gap, mode=mode)
    assert row["status"] == "passed", row
    assert row["stage_count"] == 7
    assert all(r["status"] == "passed" for r in row["analytical_layer_checks"])
    json.dumps(row, allow_nan=False)


@pytest.mark.parametrize("etype", ["IFACE4", "IFACE6"])
@pytest.mark.parametrize("gap", [0.0, 0.002])
@pytest.mark.parametrize("turned", [False, True])
def test_partial_eccentric_point_and_edge_histories_balance(etype, gap, turned):
    row = _BENCH["run_eccentric_case"](
        element_type=etype, initial_gap=gap, quarter_turn=turned,
    )
    assert row["status"] == "passed", row
    assert row["stage_count"] == 6
    assert all(r["status"] == "passed" for r in row["analytical_applied_checks"])


def test_hand_calculated_recursive_load_weights():
    np.testing.assert_allclose(_BENCH["weighted_targets"]([10, 20, 0], [.5, .25, .5]),
                               [5, 8.75, 4.375])
    np.testing.assert_allclose(_BENCH["weighted_targets"]([10, 10, 10], [.5, .5, .5]),
                               [5, 7.5, 8.75])


def test_previous_actual_load_is_retained_not_previous_target_or_alpha_target(result):
    report = contact_partial_equilibrium_by_stage(result)
    first, second = report["stages"][:2]
    assert first["external_resultant"][1] == pytest.approx(2.4)
    assert second["external_resultant"][1] == pytest.approx(3.7)
    history = second["load_history"]
    assert history["previous_applied_resultant_about_global_zero"][1] == pytest.approx(2.4)
    assert history["target_resultant_about_global_zero"][1] == 5.0
    assert second["external_resultant"][1] not in (2.5, 5.5)


def test_repeated_partial_targets_in_native_solver():
    model, _, _ = _BENCH["build_partial_layer"]()
    first = model.stages[0]
    model.stages = [replace(first, name="same", load_split=.5) for _ in range(3)]
    result = api.run(model)
    report = contact_partial_equilibrium_by_stage(result)
    assert report["status"] == "passed"
    assert [r["external_resultant"][1] for r in report["stages"]] == pytest.approx([3, 4.5, 5.25])


def test_original_full_stage_gate_still_rejects_partial_histories(result):
    original = contact_equilibrium_by_stage(result)
    assert original["status"] == "failed"
    assert original["stages"][0]["status"] == "unsupported"


def test_full_stage_histories_match_original_audit():
    model, _, _ = _BENCH["build_partial_layer"]()
    model.stages = [replace(st, load_split=1.0) for st in model.stages]
    result = api.run(model)
    old = contact_equilibrium_by_stage(result)
    new = contact_partial_equilibrium_by_stage(result)
    assert old["status"] == new["status"] == "passed"
    for a, b in zip(old["stages"], new["stages"]):
        for field in ("external_resultant", "reaction_resultant", "global_residual"):
            assert a[field] == b[field]
        for name, check in a["checks"].items():
            assert check == b["checks"][name]


@pytest.mark.parametrize("field", ["sig", "reactions", "contact_gap", "interfaces", "active"])
def test_bad_predecessor_blocks_later_claims_even_after_full_stage(result, field):
    st = result.stages[1]
    if field == "reactions":
        st.reactions[0, 0] = np.nan
    else:
        getattr(st, field).clear()
    report = contact_partial_equilibrium_by_stage(result)
    assert report["stages"][0]["status"] == "passed"
    assert report["stages"][1]["status"] == "invalid"
    assert all(r["status"] == "blocked" and r["blocked_by_stage_index"] == 1
               for r in report["stages"][2:])
    json.dumps(report, allow_nan=False)


def test_equal_opposite_false_reactions_cannot_hide_behind_global_balance(result):
    st, model = result.stages[3], result.model
    st.reactions[model.mesh.nodes("base")[0], 1] += 2.0
    st.reactions[model.mesh.nodes("top")[0], 1] -= 2.0
    report = contact_partial_equilibrium_by_stage(result)
    row = report["stages"][3]
    assert row["checks"]["global_force_kn_per_m"]["status"] == "passed"
    assert row["checks"]["nodal_force_kn_per_m"]["status"] == "failed"
    assert row["status"] == "failed"
    assert report["stages"][4]["status"] == "blocked"


@pytest.mark.parametrize("bad", ["stress", "pressure", "gap", "status", "moment", "free_reaction"])
def test_corrupted_current_fields_fail_and_block_dependents(result, bad):
    st, model = result.stages[4], result.model
    if bad == "stress":
        next(iter(st.sig.values()))[..., 1] += 1.0
    elif bad == "pressure":
        st.interfaces["contact"][..., 1] -= 1.0
    elif bad == "gap":
        st.contact_gap["contact"] *= 2.0
    elif bad == "status":
        st.contact_status["contact"][:] = 0
    elif bad == "moment":
        st.reactions[0, 2] = 1.0
    else:
        st.reactions[model.mesh.nodes("bottom")[0], 1] += 1.0
    report = contact_partial_equilibrium_by_stage(result)
    assert report["status"] == "failed"
    assert report["stages"][4]["status"] in ("failed", "invalid")
    assert report["stages"][5]["status"] == "blocked"


@pytest.mark.parametrize("fraction", [0, -1, 1.1, True, np.nan, np.inf, "0.4"])
def test_invalid_accepted_fraction_never_passes(result, fraction):
    result.stages[1].lam = fraction
    report = contact_partial_equilibrium_by_stage(result)
    assert report["stages"][1]["status"] == "invalid"
    assert report["stages"][2]["status"] == "blocked"


def test_declared_fraction_must_match_accepted_record(result):
    result.stages[1].lam = .4
    assert contact_partial_equilibrium_by_stage(result)["stages"][1]["status"] == "invalid"
    result.stages[1].lam = .5
    result.model.stages[1] = replace(result.model.stages[1], load_split=True)
    assert contact_partial_equilibrium_by_stage(result)["stages"][1]["status"] == "invalid"


@pytest.mark.parametrize("bad", ["missing", "extra", "name"])
def test_sequence_identity_is_not_inferred_from_stage_names(result, bad):
    if bad == "missing":
        result.stages.pop()
    elif bad == "extra":
        result.stages.append(copy.deepcopy(result.last))
    else:
        result.stages[1].name = "different"
    report = contact_partial_equilibrium_by_stage(result)
    assert report["status"] == "failed"
    assert all(r["status"] != "passed" for r in report["stages"][1:])


def test_duplicate_stage_names_are_distinct_and_no_data_mutates(result):
    for i, st in enumerate(result.stages):
        st.name = "same"
        result.model.stages[i] = replace(result.model.stages[i], name="same")
    before = pickle.dumps(result)
    report = contact_partial_equilibrium_by_stage(result)
    assert report["status"] == "passed"
    assert [r["stage_index"] for r in report["stages"]] == list(range(7))
    assert pickle.dumps(result) == before


@pytest.mark.parametrize("bad", ["initial_stress", "initial_reaction", "initial_gap",
                                 "initial_u", "initial_lambda", "missing_initial"])
def test_initial_evidence_is_verified_before_history(result, bad):
    st = result.initial
    if bad == "initial_stress":
        next(iter(st.sig.values()))[..., 2] = 1.0
    elif bad == "initial_reaction":
        st.reactions[0, 0] = 1e-10
    elif bad == "initial_gap":
        st.contact_gap["contact"][:] = .001
        st.contact_status["contact"][:] = 0
    elif bad == "initial_u":
        st.u[:] = 1.0
    elif bad == "initial_lambda":
        st.lam = .5
    else:
        st.sig.clear()
    report = contact_partial_equilibrium_by_stage(result)
    assert report["initial_status"] == "invalid"
    assert all(r["status"] == "blocked" for r in report["stages"])


@pytest.mark.parametrize("bad", ["activation", "support", "wet", "excavation", "material",
                                 "seismic", "initial_gravity"])
def test_unsupported_release_and_physics_are_not_accepted(result, bad):
    model = result.model
    if bad == "initial_gravity":
        model.initial = replace(model.initial, mode="gravity")
    else:
        changes = {
            "activation": {"active_structures": set()},
            "support": {"displacements": (api.Displacement("bottom", uy=0.0),)},
            "wet": {"water": api.WaterCondition("piezo_line", np.array([[0, 1], [2, 1]]))},
            "excavation": {"active_regions": set()},
            "material": {"material_override": {1: "solid"}},
            "seismic": {"seismic_kh": .1},
        }[bad]
        model.stages[1] = replace(model.stages[1], **changes)
    report = contact_partial_equilibrium_by_stage(result)
    assert report["status"] == "failed"
    if bad == "initial_gravity":
        assert report["initial_status"] == "unsupported"
    else:
        assert report["stages"][1]["status"] == "unsupported"
        assert all(r["status"] == "blocked" for r in report["stages"][2:])


@pytest.mark.parametrize("bad", [0, -1, True, np.nan, np.inf, "1e-8"])
def test_invalid_tolerances_rejected(result, bad):
    with pytest.raises(ValueError, match="tolerances"):
        contact_partial_equilibrium_by_stage(result, rtol=bad)


def test_origin_changes_moment_not_force_or_acceptance(result):
    one = contact_partial_equilibrium_by_stage(result)
    two = contact_partial_equilibrium_by_stage(result, origin=(3.5, -2.0))
    assert one["status"] == two["status"] == "passed"
    for a, b in zip(one["stages"], two["stages"]):
        for field in ("external_resultant", "reaction_resultant"):
            x, y = a[field], b[field]
            assert y[:2] == pytest.approx(x[:2])
            assert y[2] == pytest.approx(x[2] - 3.5*x[1] - 2.0*x[0], abs=1e-10)


@pytest.mark.parametrize("fmt", ["h5", "ssproj", "json"])
def test_persistence_preserves_partial_lambdas_and_auditable_history(result, tmp_path, fmt):
    path = tmp_path / ("history."+fmt)
    if fmt == "h5":
        api.save_results(result, path)
        restored = api.load_results(path)
    elif fmt == "ssproj":
        api.save_project(result.model, path, result)
        restored = api.load_project(path).results
    else:
        api.save_model(result.model, path)
        restored = api.run(api.load_model(path))
    report = contact_partial_equilibrium_by_stage(restored)
    assert report["status"] == "passed"
    assert [s.lam for s in restored.stages] == [s.lam for s in result.stages]
    for original, row in zip(contact_partial_equilibrium_by_stage(result)["stages"],
                             report["stages"]):
        assert row["external_resultant"] == original["external_resultant"]
        assert row["reaction_resultant"] == pytest.approx(original["reaction_resultant"], abs=1e-10)


def test_inactive_contact_fixed_throughout_is_not_falsely_welded():
    model, _, _ = _BENCH["build_partial_layer"]()
    model.initial = replace(model.initial, active_structures=set())
    model.stages = [replace(st, active_structures=set()) for st in model.stages]
    result = api.run(model)
    report = contact_partial_equilibrium_by_stage(result)
    assert report["status"] == "passed"
    assert all(r["checks"]["gap_pressure_law_kpa"]["status"] == "not_applicable"
               for r in report["stages"])


def test_benchmark_cli_fails_when_audit_is_corrupted(monkeypatch, tmp_path):
    fn = _BENCH["main"]
    monkeypatch.setitem(fn.__globals__, "run_benchmark", lambda: {"status": "failed"})
    destination = tmp_path / "bad.json"
    monkeypatch.setattr("sys.argv", ["benchmark", "--output", str(destination)])
    assert fn() == 1
    assert json.loads(destination.read_text())["status"] == "failed"

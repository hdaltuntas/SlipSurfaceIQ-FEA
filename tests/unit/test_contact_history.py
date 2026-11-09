"""Exact point histories from native results: identity, order, units and atomic export."""

from __future__ import annotations

import copy
import csv
import runpy
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.io.contact_history_csv import export_contact_history_csv
from slipsurface.fe2d.post.contact_history import contact_history_segments, contact_point_history
from slipsurface.fe2d.post.contact_results import contact_points

_BUILD = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts"
                           / "f7_contact_static_benchmark.py"))["build_model"]


@pytest.fixture(scope="module", params=["IFACE4", "IFACE6"])
def native(request):
    model, _ = _BUILD(element_type=request.param)
    return api.run(model)


def test_history_is_exact_initial_plus_accepted_snapshots(native):
    history = contact_point_history(native, "contact", 0, 0)
    assert len(history) == 8
    for i, (sample, snapshot) in enumerate(zip(history, [native.initial, *native.stages])):
        assert sample.stage_index == i
        assert sample.stage_name == snapshot.name
        assert sample.load_factor == snapshot.lam
        assert sample.contact == contact_points(native, snapshot, "contact")[0]
    assert history[1].contact.gap_m == pytest.approx(0.006)
    assert history[2].contact.gap_m == pytest.approx(0.005)
    assert history[1].contact.pressure_kpa == history[2].contact.pressure_kpa == 0.0
    assert history[5].contact.gap_m < 0 and history[5].contact.pressure_kpa > 0


def test_mm_plots_keep_raw_metre_data_and_order(native):
    history = contact_point_history(native, "contact", 0, 0)
    segments = contact_history_segments(history, "contact_gap")
    assert len(segments) == 1
    assert segments[0][1] == pytest.approx((1, 6.0))
    assert segments[0][2] == pytest.approx((2, 5.0))
    assert history[1].contact.gap_m == pytest.approx(0.006)
    with pytest.raises(ValueError, match="categorical"):
        contact_history_segments(history, "contact_status")


def test_missing_and_inactive_stages_break_lines_without_erasing_rows(native):
    result = copy.deepcopy(native)
    result.stages[1].contact_gap.clear()  # snapshot 2 unavailable
    st = result.stages[3]  # snapshot 4 inactive
    st.active["contact"][:] = False
    st.contact_gap["contact"][:] = np.nan
    st.contact_status["contact"][:] = 255
    st.interfaces["contact"][:] = np.nan
    history = contact_point_history(result, "contact", 0, 0)
    assert history[2].contact.availability == "unavailable"
    assert history[4].contact.status == "INACTIVE"
    for field in ("contact_gap", "contact_pressure"):
        parts = contact_history_segments(history, field)
        assert [[i for i, _ in part] for part in parts] == [[0, 1], [3], [5, 6, 7]]
    assert history[2].contact.pressure_kpa is None
    assert history[4].contact.gap_m is None


def test_all_missing_measurements_produce_no_graph(native):
    result = copy.deepcopy(native)
    for st in [result.initial, *result.stages]:
        st.contact_gap.clear()
    history = contact_point_history(result, "contact", 0, 0)
    assert len(history) == 8
    assert contact_history_segments(history, "contact_gap") == ()
    assert contact_history_segments(history, "contact_pressure") == ()


def test_repeated_names_and_partial_loads_do_not_reorder_or_merge(native):
    result = copy.deepcopy(native)
    for st in [result.initial, *result.stages]:
        st.name = "same name"
        st.lam = 0.5
        st.u[:] = 42.0  # reported displacement is never an opening reference
    history = contact_point_history(result, "contact", 0, 0)
    assert [s.stage_index for s in history] == list(range(8))
    assert all(s.load_factor == 0.5 for s in history)
    assert history[1].contact.gap_m == pytest.approx(0.006)
    assert history[2].contact.gap_m == pytest.approx(0.005)


def test_each_point_and_quadratic_order_stay_distinct(native):
    block = native.model.mesh.block("contact")
    n = block.etype.nen // 2
    for ip in range(n):
        history = contact_point_history(native, "contact", np.int64(0), np.int64(ip))
        assert all((s.contact.face1_node, s.contact.face2_node) ==
                   (block.conn[0, ip], block.conn[0, n + ip]) for s in history)
    if n == 3:
        mid = contact_point_history(native, "contact", 0, 2)[0].contact
        assert mid.x_m == pytest.approx(1.0)


def test_coincident_interfaces_have_separate_histories(native):
    result = copy.deepcopy(native)
    block = result.model.mesh.block("contact")
    result.model.mesh = replace(result.model.mesh, blocks=(
        *result.model.mesh.blocks, replace(block, tag="other")))
    result.model.interfaces["other"] = result.model.interfaces["contact"]
    for st in [result.initial, *result.stages]:
        for key in ("active", "contact_gap", "contact_status", "interfaces"):
            getattr(st, key)["other"] = getattr(st, key)["contact"].copy()
        st.contact_gap["other"][:] = 0.015
        st.contact_status["other"][:] = 0
        st.interfaces["other"][:] = 0
    a = contact_point_history(result, "contact", 0, 0)
    b = contact_point_history(result, "other", 0, 0)
    assert a[0].contact.x_m == b[0].contact.x_m
    assert a[1].contact.gap_m != b[1].contact.gap_m
    assert all(s.contact.gap_m == 0.015 for s in b)


@pytest.mark.parametrize("element,point", [(-1, 0), (1, 0), (False, 0), (0.0, 0),
                                           (0, -1), (0, 99), (0, True), (0, "0")])
def test_invalid_identity_is_rejected(native, element, point):
    with pytest.raises(ValueError, match="index"):
        contact_point_history(native, "contact", element, point)


@pytest.mark.parametrize("factor", [float("nan"), float("inf"), True, -0.1, 1.1, "1"])
def test_invalid_late_stage_load_factor_is_rejected(native, factor):
    result = copy.deepcopy(native)
    result.last.lam = factor
    with pytest.raises(ValueError, match="load factor"):
        contact_point_history(result, "contact", 0, 0)


def test_goodman_and_unknown_tag_rejected(native):
    with pytest.raises(ValueError, match="declared"):
        contact_point_history(native, "unknown", 0, 0)
    result = copy.deepcopy(native)
    result.model.interfaces["contact"] = api.InterfaceSpec("legacy", 2000, 0)
    with pytest.raises(ValueError, match="declared"):
        contact_point_history(result, "contact", 0, 0)


@pytest.mark.parametrize("bad", ["gap", "status", "traction", "name", "overflow"])
def test_corrupted_late_stage_cannot_be_partially_exported(native, tmp_path, bad):
    result = copy.deepcopy(native)
    if bad == "gap":
        result.last.contact_gap["contact"][:] = np.nan
    elif bad == "status":
        result.last.contact_status["contact"][:] = 99
    elif bad == "traction":
        result.last.interfaces["contact"][..., 0] = 1.0
    elif bad == "name":
        result.last.name = None
    else:
        result.last.contact_gap["contact"][:] = 1e308
        result.last.contact_status["contact"][:] = 0
        result.last.interfaces["contact"][:] = 0
    path = tmp_path / "history.csv"
    path.write_bytes(b"existing destination")
    with pytest.raises(ValueError):
        export_contact_history_csv(result, path, "contact", 0, 0)
    assert path.read_bytes() == b"existing destination"


def test_csv_retains_index_units_missing_values_and_original_identity(native, tmp_path):
    result = copy.deepcopy(native)
    result.stages[2].contact_gap.clear()
    path = tmp_path / "history.csv"
    export_contact_history_csv(result, path, "contact", 0, 0)
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [int(r["stage_index"]) for r in rows] == list(range(8))
    assert float(rows[1]["gap_m"]) == pytest.approx(0.006)
    assert rows[3]["gap_m"] == rows[3]["pressure_kPa"] == ""
    assert rows[3]["status"] == "UNAVAILABLE"
    assert float(rows[5]["pressure_kPa"]) == -float(rows[5]["normal_traction_kPa"])
    assert len({(r["tag"], r["element"], r["point"], r["face1_node"], r["face2_node"])
                for r in rows}) == 1


def test_project_roundtrip_preserves_history_and_csv(native, tmp_path):
    project, a, b = (tmp_path / name for name in ("history.ssproj", "before.csv", "after.csv"))
    api.save_project(native.model, project, native)
    restored = api.load_project(project).results
    assert contact_point_history(restored, "contact", 0, 0) == contact_point_history(
        native, "contact", 0, 0)
    export_contact_history_csv(native, a, "contact", 0, 0)
    export_contact_history_csv(restored, b, "contact", 0, 0)
    assert a.read_bytes() == b.read_bytes()

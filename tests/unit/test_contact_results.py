"""Stored native contact results: units, identity, missing evidence and atomic CSV."""

from __future__ import annotations

import copy
import csv
import runpy
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.io.report import export_contact_csv
from slipsurface.fe2d.post.contact_results import contact_points, normal_contact_tags

_BUILD = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts"
                           / "f7_contact_static_benchmark.py"))["build_model"]


@pytest.fixture(scope="module", params=["IFACE4", "IFACE6"])
def native(request):
    model, _ = _BUILD(element_type=request.param)
    return api.run(model)


def test_native_reversal_keeps_stored_open_gap_and_zero_pressure(native):
    for st, expected in zip(native.stages[:2], (0.006, 0.005)):
        points = contact_points(native, st, "contact")
        assert len(points) == native.model.mesh.block("contact").etype.nen // 2
        assert {p.status for p in points} == {"OPEN"}
        assert all(p.gap_m == pytest.approx(expected) for p in points)
        assert all(p.display_value("contact_gap") == pytest.approx(expected * 1000)
                   for p in points)
        assert all(p.pressure_kpa == 0 for p in points)
        assert all(p.normal_traction_kpa == 0 for p in points)


def test_reset_reporting_datum_is_not_used_as_gap(native):
    st = copy.deepcopy(native.stages[3])
    before = contact_points(native, st)
    st.u[:] = 123.45  # deliberately unrelated displacement datum
    assert contact_points(native, st) == before
    assert all(p.gap_m < 0 and p.pressure_kpa > 0 for p in before)
    assert {p.status for p in before} == {"COMPRESSED"}


def test_point_and_face_identity_preserved_in_quadratic_order(native):
    points = contact_points(native)
    block = native.model.mesh.block("contact")
    n = block.etype.nen // 2
    assert [p.point for p in points] == list(range(n))
    for p in points:
        assert (p.face1_node, p.face2_node) == (block.conn[0, p.point], block.conn[0, p.point + n])
        assert [p.x_m, p.y_m] == pytest.approx(native.model.mesh.coords[p.face1_node])
    if n == 3:
        assert points[0].x_m < points[2].x_m < points[1].x_m


def test_touching_is_its_own_category(native):
    st = copy.deepcopy(native.last)
    st.contact_gap["contact"][:] = 0
    st.interfaces["contact"][:] = 0
    st.contact_status["contact"][:] = 1
    assert all(p.status == "TOUCHING" for p in contact_points(native, st))


@pytest.mark.parametrize("missing", ["contact_gap", "contact_status", "interfaces"])
def test_missing_optional_fields_are_unavailable_not_zero(native, missing):
    st = copy.deepcopy(native.last)
    getattr(st, missing).clear()
    points = contact_points(native, st)
    assert all(p.availability == "unavailable" and p.status == "UNAVAILABLE" for p in points)
    assert all(p.gap_m is None and p.pressure_kpa is None for p in points)
    assert all(p.display_value("contact_status") is None for p in points)


def test_inactive_points_have_no_fabricated_measurements(native):
    st = copy.deepcopy(native.last)
    st.active["contact"][:] = False
    st.contact_gap["contact"][:] = np.nan
    st.contact_status["contact"][:] = 255
    st.interfaces["contact"][:] = np.nan
    points = contact_points(native, st)
    assert all(p.status == "INACTIVE" and not p.active for p in points)
    assert all(p.availability == "inactive" and p.gap_m is None for p in points)


def test_neighboring_interfaces_are_not_merged(native):
    result = copy.deepcopy(native)
    block = result.model.mesh.block("contact")
    result.model.mesh = replace(result.model.mesh,
                                blocks=(*result.model.mesh.blocks, replace(block, tag="other")))
    result.model.interfaces["other"] = result.model.interfaces["contact"]
    st = result.last
    for name in ("active", "contact_gap", "contact_status", "interfaces"):
        getattr(st, name)["other"] = getattr(st, name)["contact"].copy()
    st.contact_gap["other"][:] = 0.005
    st.contact_status["other"][:] = 0
    st.interfaces["other"][:] = 0
    points = contact_points(result)
    assert len(points) == 2 * len(contact_points(result, tag="contact"))
    assert {p.status for p in points if p.tag == "other"} == {"OPEN"}
    assert {p.status for p in points if p.tag == "contact"} == {"COMPRESSED"}


@pytest.mark.parametrize("bad", [
    "mask_missing", "mask_numeric", "gap_shape", "gap_nan", "gap_bool", "gap_string",
    "status_unknown", "status_float", "status_bool", "status_contradiction", "shear",
    "tension", "traction_nan", "inactive_stale", "malformed_map", "open_pressure",
])
def test_malformed_evidence_fails_closed(native, bad):
    st = copy.deepcopy(native.last)
    if bad == "mask_missing":
        st.active.pop("contact")
    elif bad == "mask_numeric":
        st.active["contact"] = np.ones(1)
    elif bad == "gap_shape":
        st.contact_gap["contact"] = np.zeros(1)
    elif bad == "gap_nan":
        st.contact_gap["contact"][:] = np.nan
    elif bad == "gap_bool":
        st.contact_gap["contact"] = st.contact_gap["contact"].astype(bool)
    elif bad == "gap_string":
        st.contact_gap["contact"] = st.contact_gap["contact"].astype(str)
    elif bad == "status_unknown":
        st.contact_status["contact"][:] = 42
    elif bad == "status_float":
        st.contact_status["contact"] = st.contact_status["contact"].astype(float)
    elif bad == "status_bool":
        st.contact_status["contact"] = st.contact_status["contact"].astype(bool)
    elif bad == "status_contradiction":
        st.contact_status["contact"][:] = 0
    elif bad == "shear":
        st.interfaces["contact"][..., 0] = 1
    elif bad == "tension":
        st.interfaces["contact"][..., 1] = 1
    elif bad == "traction_nan":
        st.interfaces["contact"][:] = np.nan
    elif bad == "inactive_stale":
        st.active["contact"][:] = False
    elif bad == "malformed_map":
        st.contact_gap = None
    else:
        st.contact_gap["contact"][:] = 0.005
        st.contact_status["contact"][:] = 0
    with pytest.raises(ValueError):
        contact_points(native, st)


def test_goodman_is_not_contact_gap_data(native):
    result = copy.deepcopy(native)
    result.model.interfaces["contact"] = api.InterfaceSpec("joint", 2000, 0)
    assert normal_contact_tags(result.model) == ()
    assert contact_points(result) == ()
    with pytest.raises(ValueError, match="not a declared"):
        contact_points(result, tag="contact")


@pytest.mark.parametrize("fmt", ["h5", "ssproj"])
def test_saved_snapshots_keep_same_contact_points(native, tmp_path, fmt):
    path = tmp_path / f"contact.{fmt}"
    if fmt == "h5":
        api.save_results(native, path)
        restored = api.load_results(path)
    else:
        api.save_project(native.model, path, native)
        restored = api.load_project(path).results
    assert contact_points(restored) == contact_points(native)


def test_csv_all_stages_units_signs_and_identity(native, tmp_path):
    path = tmp_path / "points.csv"
    export_contact_csv(native, path, all_stages=True)
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    n = native.model.mesh.block("contact").etype.nen // 2
    assert len(rows) == n * (1 + len(native.stages))
    first = next(row for row in rows if row["stage"] == native.stages[0].name)
    assert float(first["gap_m"]) == pytest.approx(0.006)
    assert first["status"] == "OPEN"
    final = rows[-1]
    assert float(final["normal_traction_kPa"]) < 0 < float(final["pressure_kPa"])
    assert int(final["point"]) == n - 1


def test_csv_unavailable_data_is_blank_and_not_successful_measurement(native, tmp_path):
    result = copy.deepcopy(native)
    result.last.contact_gap.clear()
    path = tmp_path / "old.csv"
    export_contact_csv(result, path)
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert all(row["gap_m"] == row["pressure_kPa"] == row["status_code"] == "" for row in rows)
    assert all(row["availability"] == "unavailable" for row in rows)


def test_invalid_late_stage_cannot_overwrite_existing_csv(native, tmp_path):
    result = copy.deepcopy(native)
    result.last.contact_status["contact"][:] = 42
    path = tmp_path / "existing.csv"
    path.write_text("preserve me", encoding="utf-8")
    with pytest.raises(ValueError):
        export_contact_csv(result, path, all_stages=True)
    assert path.read_text(encoding="utf-8") == "preserve me"

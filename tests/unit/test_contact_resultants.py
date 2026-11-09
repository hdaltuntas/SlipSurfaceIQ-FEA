"""Stored contact actions: independent resultants, native signs and atomic CSV."""

from __future__ import annotations

import copy
import csv
import math
import runpy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.fem.static import StageResult
from slipsurface.fe2d.fem.unilateral_contact import UnilateralNormalContactGroup
from slipsurface.fe2d.io.contact_resultants_csv import export_contact_resultants_csv
from slipsurface.fe2d.post.contact_resultants import contact_resultants

_BUILD = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts"
                           / "f7_contact_static_benchmark.py"))["build_model"]


def fixture_result(etype="IFACE4", angle=0.0, length=4.0, pressures=None):
    n = 2 if etype == "IFACE4" else 3
    a = math.radians(angle)
    direction = np.array([math.cos(a), math.sin(a)])
    locations = np.array([0.0, 1.0] if n == 2 else [0.0, 1.0, 0.5])
    first = np.array([2.0, -3.0]) + length*locations[:, None]*direction
    block = api.ElementBlock(api.ElemType[etype], np.arange(2*n)[None, :],
                             np.array([0]), "contact")
    mesh = api.Mesh(np.vstack([first, first]), (block,))
    p = np.full(n, 5.0) if pressures is None else np.asarray(pressures)
    stage = StageResult("snapshot", np.zeros_like(mesh.coords), {},
                        np.zeros((mesh.nn, 3)), active={"contact": np.array([True])},
                        interfaces={"contact": np.stack([np.zeros(n), -p], axis=-1)[None]},
                        contact_gap={"contact": -p[None]/2000},
                        contact_status={"contact": np.where(p[None] > 0, 2, 1).astype(np.uint8)})
    model = SimpleNamespace(mesh=mesh, analysis=api.Analysis.PLANE_STRAIN,
                            interfaces={"contact": api.InterfaceSpec.unilateral_normal("c", 2000)})
    return SimpleNamespace(model=model, initial=stage, stages=[], last=stage)


@pytest.mark.parametrize("etype", ["IFACE4", "IFACE6"])
@pytest.mark.parametrize("angle", [0.0, 37.0, -63.0, 180.0])
def test_uniform_pressure_matches_closed_form_force_and_moment(etype, angle):
    result = fixture_result(etype, angle)
    row, = contact_resultants(result, origin=(1.5, 0.25))
    a = math.radians(angle)
    direction, normal = np.array([math.cos(a), math.sin(a)]), np.array([-math.sin(a), math.cos(a)])
    expected_force = 20.0*normal
    center = np.array([2.0, -3.0]) + 2*direction - [1.5, 0.25]
    expected_moment = center[0]*expected_force[1] - center[1]*expected_force[0]
    assert row.availability == "available"
    assert row.pressure_integral == pytest.approx(20.0)
    assert (row.face2.fx, row.face2.fy, row.face2.moment) == pytest.approx(
        [*expected_force, expected_moment])
    assert (row.face1.fx, row.face1.fy, row.face1.moment) == pytest.approx(
        [-expected_force[0], -expected_force[1], -expected_moment])
    assert row.active_length_m == pytest.approx(4.0)


def test_quadratic_midpoint_weight_and_linear_pressure_moment():
    # p(s)=2+s on s=[0,4], integral=16; moment about first point = 112/3.
    result = fixture_result("IFACE6", pressures=[2.0, 6.0, 4.0])
    row, = contact_resultants(result, origin=(2.0, -3.0))
    assert row.pressure_integral == pytest.approx(16.0)
    assert row.face2.fy == pytest.approx(16.0)
    assert row.face2.moment == pytest.approx(112.0/3.0)


def test_iface4_nonuniform_moment_is_discrete_quadrature_not_continuous_recovery():
    row, = contact_resultants(fixture_result("IFACE4", pressures=[2.0, 6.0]), origin=(2.0, -3.0))
    assert row.face2.fy == pytest.approx(16.0)
    assert row.face2.moment == pytest.approx(48.0)  # native endpoint quadrature
    assert row.face2.moment != pytest.approx(112.0/3.0)


@pytest.mark.parametrize("etype", ["IFACE4", "IFACE6"])
@pytest.mark.parametrize("angle", [0.0, 37.0, -63.0])
def test_actions_are_negative_of_native_assembled_internal_contributions(etype, angle):
    result = fixture_result(etype, angle)
    mesh, block = result.model.mesh, result.model.mesh.blocks[0]
    group = UnilateralNormalContactGroup(block, mesh.coords, kn=2000)
    n = block.etype.nen//2
    state = {"gap": np.array([[-0.001, -0.003] if n == 2 else [-0.001, -0.003, -0.002]])}
    trial, f, _, status = group.integrate(state, np.array([0]), np.zeros((1, 4*n)))
    st = result.last
    st.contact_gap["contact"] = trial["gap"]
    st.contact_status["contact"] = status
    st.interfaces["contact"][..., 1] = 2000*trial["gap"]
    row, = contact_resultants(result, origin=(0.5, -0.75))
    force = f[0].reshape(2*n, 2)
    for sl, face in ((slice(0, n), row.face1), (slice(n, 2*n), row.face2)):
        positions = mesh.coords[sl] - [0.5, -0.75]
        internal = force[sl]
        moment = np.sum(positions[:, 0]*internal[:, 1] - positions[:, 1]*internal[:, 0])
        assert [face.fx, face.fy, face.moment] == pytest.approx(
            [-internal[:, 0].sum(), -internal[:, 1].sum(), -moment], abs=1e-12)


def test_moment_origin_translation_identity_and_reported_u_independence():
    result = fixture_result(angle=37)
    before, = contact_resultants(result)
    result.last.u[:] = np.nan  # display displacement cannot determine stored force or arm
    after, = contact_resultants(result, origin=(3.0, -2.0))
    assert after.face2.moment == pytest.approx(
        before.face2.moment - 3*before.face2.fy - 2*before.face2.fx)
    assert after.face2.fx == before.face2.fx
    assert after.face2.fy == before.face2.fy


@pytest.fixture(scope="module", params=["IFACE4", "IFACE6"])
def native(request):
    model, _ = _BUILD(element_type=request.param)
    return api.run(model)


def test_native_actions_balance_independent_layer_boundary_reactions(native):
    for stage in native.stages:
        row, = contact_resultants(native, stage)
        base = native.model.mesh.nodes("base")
        top = native.model.mesh.nodes("top")
        assert row.face1.fy == pytest.approx(-stage.reactions[base, 1].sum(), abs=1e-8)
        assert row.face2.fy == pytest.approx(-stage.reactions[top, 1].sum(), abs=1e-8)
    for stage in native.stages[:2]:
        row, = contact_resultants(native, stage)
        assert row.pressure_integral == 0.0
        assert row.face2.fy == 0.0


def test_snapshot_roundtrip_keeps_resultants(native, tmp_path):
    path = tmp_path / "summary.ssproj"
    api.save_project(native.model, path, native)
    restored = api.load_project(path).results
    assert contact_resultants(restored) == contact_resultants(native)


@pytest.mark.parametrize("missing", ["contact_gap", "contact_status", "interfaces"])
def test_missing_active_map_is_not_zero_or_partial_result(missing):
    result = fixture_result()
    getattr(result.last, missing).clear()
    row, = contact_resultants(result)
    assert row.availability == "unavailable"
    assert row.unavailable_points == 2
    assert row.face1 is row.face2 is row.pressure_integral is None
    assert row.active_length_m == 4.0


def test_wholly_inactive_totals_are_explicit_and_blank():
    result = fixture_result()
    st = result.last
    st.active["contact"][:] = False
    st.interfaces["contact"][:] = np.nan
    st.contact_gap["contact"][:] = np.nan
    st.contact_status["contact"][:] = 255
    row, = contact_resultants(result)
    assert row.availability == "inactive"
    assert row.face1 is row.face2 is row.pressure_integral is None
    assert row.active_elements == 0 and row.inactive_points == 2
    assert row.active_length_m == 0.0


def test_active_subset_is_explicit_not_entire_interface_force():
    result = fixture_result()
    old = result.model.mesh
    blocks = (api.ElementBlock(api.ElemType.IFACE4, np.array([[0, 1, 2, 3], [4, 5, 6, 7]]),
                               np.array([0, 0]), "contact"),)
    result.model.mesh = api.Mesh(np.vstack([old.coords, old.coords+[4, 0]]), blocks)
    st = result.last
    st.active["contact"] = np.array([True, False])
    st.contact_gap["contact"] = np.array([[-0.0025, -0.0025], [np.nan, np.nan]])
    st.contact_status["contact"] = np.array([[2, 2], [255, 255]], dtype=np.uint8)
    st.interfaces["contact"] = np.array([[[0, -5], [0, -5]], [[np.nan, np.nan], [np.nan, np.nan]]])
    row, = contact_resultants(result)
    assert row.availability == "active_subset"
    assert row.active_elements == 1 and row.element_count == 2
    assert row.active_length_m == 4 and row.total_length_m == 8
    assert row.face2.fy == 20


def test_different_tags_are_never_summed_away():
    result = fixture_result()
    old = result.model.mesh
    other = api.ElementBlock(api.ElemType.IFACE4, np.array([[1, 0, 3, 2]]), np.array([0]), "other")
    result.model.mesh = api.Mesh(old.coords, (*old.blocks, other))
    result.model.interfaces["other"] = result.model.interfaces["contact"]
    for field in ("contact_gap", "contact_status", "interfaces", "active"):
        getattr(result.last, field)["other"] = getattr(result.last, field)["contact"].copy()
    one, two = contact_resultants(result)
    assert one.tag == "contact" and two.tag == "other"
    assert one.face2.fy == 20 and two.face2.fy == -20
    assert one.pressure_integral == two.pressure_integral == 20


@pytest.mark.parametrize("bad", ["curved", "offset_face", "degenerate", "nan", "axisym"])
def test_incompatible_geometry_is_not_integrated(bad):
    result = fixture_result("IFACE6")
    if bad == "curved":
        result.model.mesh.coords[[2, 5], 1] += 1
    elif bad == "offset_face":
        result.model.mesh.coords[3:, 1] += 0.01
    elif bad == "degenerate":
        result.model.mesh.coords[:] = 0
    elif bad == "nan":
        result.model.mesh.coords[4, 0] = np.nan
    else:
        result.model.analysis = api.Analysis.AXISYMMETRIC
    with pytest.raises(ValueError):
        contact_resultants(result)


@pytest.mark.parametrize("origin", [None, (), (0,), (0, 1, 2), (True, 0), ("1", 0),
                                    (np.bool_(False), 0), (np.nan, 0), (0, np.inf)])
def test_invalid_origin_rejected(origin):
    with pytest.raises(ValueError, match="origin"):
        contact_resultants(fixture_result(), origin=origin)


def test_finite_input_overflow_is_not_a_successful_result():
    result = fixture_result(length=1e100, pressures=[1e250, 1e250])
    with pytest.raises(ValueError, match="overflow"):
        contact_resultants(result)


def test_goodman_is_not_given_contact_totals():
    result = fixture_result()
    result.model.interfaces["contact"] = api.InterfaceSpec("goodman", 2000, 0)
    assert contact_resultants(result) == ()
    with pytest.raises(ValueError, match="not a declared"):
        contact_resultants(result, tag="contact")


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_export_order_origin_both_signs_and_snapshot_identity(native, tmp_path):
    result = copy.deepcopy(native)
    for st in [result.initial, *result.stages]:
        st.name = "repeat"
        st.lam = 0.5
    path = tmp_path / "totals.csv"
    export_contact_resultants_csv(result, path, origin=(3, -1))
    rows = read_csv(path)
    assert [int(row["stage_index"]) for row in rows] == list(range(8))
    assert all(row["stage"] == "repeat" and row["load_factor"] == "0.5" for row in rows)
    assert all(row["origin_x_m"] == "3" and row["origin_y_m"] == "-1" for row in rows)
    last = rows[-1]
    assert float(last["face2_action_Fy_kN_per_m"]) > 0
    assert float(last["face2_internal_Fy_kN_per_m"]) < 0
    assert float(last["face2_action_Mz_kNm_per_m"]) < 0
    export_contact_resultants_csv(result, path, stage_index=2)
    assert len(read_csv(path)) == 1 and read_csv(path)[0]["stage_index"] == "2"


def test_missing_export_totals_are_blank(tmp_path):
    result = fixture_result()
    result.last.contact_gap.clear()
    path = tmp_path / "missing.csv"
    export_contact_resultants_csv(result, path)
    row, = read_csv(path)
    assert row["availability"] == "unavailable"
    assert row["pressure_integral_kN_per_m"] == row["face2_action_Fy_kN_per_m"] == ""


@pytest.mark.parametrize("bad", ["nan_force", "invalid_code", "lambda", "stage_name", "geometry"])
def test_bad_late_snapshot_or_geometry_preserves_existing_file(native, tmp_path, bad):
    result = copy.deepcopy(native)
    if bad == "nan_force":
        result.last.interfaces["contact"][:] = np.nan
    elif bad == "invalid_code":
        result.last.contact_status["contact"][:] = 42
    elif bad == "lambda":
        result.last.lam = float("inf")
    elif bad == "stage_name":
        result.last.name = None
    else:
        n = result.model.mesh.block("contact").conn[0, -1]
        result.model.mesh.coords[n, 1] += 0.01
    path = tmp_path / "keep.csv"
    path.write_bytes(b"keep original")
    with pytest.raises(ValueError):
        export_contact_resultants_csv(result, path)
    assert path.read_bytes() == b"keep original"


@pytest.mark.parametrize("index", [True, -1, 1, "0", 0.5])
def test_export_invalid_snapshot_index(tmp_path, index):
    with pytest.raises(ValueError, match="index"):
        export_contact_resultants_csv(fixture_result(), tmp_path / "bad.csv", stage_index=index)

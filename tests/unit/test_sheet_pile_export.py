"""The S4 hand-off retains end-force jumps, units, and physical-case identity."""

from __future__ import annotations

import importlib.util
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.io import model_from_dict, model_to_dict


@pytest.fixture
def exporter(monkeypatch):
    examples = Path(__file__).parents[2] / "examples"
    monkeypatch.syspath_prepend(str(examples))
    spec = importlib.util.spec_from_file_location("s4_export", examples / "verify_sheet_pile.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _wall():
    # First beam runs upward, second downward; one shared node, no end averaging.
    mesh = api.Mesh(
        np.array([[0.0, 0.0], [0.0, -1.0], [0.0, -2.0]]),
        [api.ElementBlock(api.ElemType.BEAM2, np.array([[1, 0], [1, 2]]), [0, 0], "pile")],
        {},
        {},
    )
    stage = SimpleNamespace(
        active={"pile": np.array([True, True])},
        beams={
            "pile": np.array(
                [[[1.0, 2.0, 7.0], [3.0, 4.0, -2.0]], [[5.0, 6.0, 11.0], [7.0, 8.0, -3.0]]]
            )
        },
        u=np.array([[0.1, 0.01], [0.05, 0.02], [-0.02, 0.03]]),
        rotation=np.array([0.01, 0.02, 0.03]),
    )
    return SimpleNamespace(mesh=mesh), stage


def test_export_keeps_signed_end_forces_jumps_and_distinct_wall_nodes(exporter):
    m, stage = _wall()
    ends, nodes = exporter.wall_tables(m, stage)
    assert [r["depth_m"] for r in ends] == [0, 1, 1, 2]
    assert [r["M_kNm_per_m"] for r in ends] == [-2, 7, 11, -3]
    assert [r["M_up_kNm_per_m"] for r in ends] == [-2, 7, -11, 3]
    assert [r["local_s"] for r in ends] == [1, 1, -1, -1]
    assert [r["depth_m"] for r in nodes] == [0, 1, 2]
    assert nodes[0]["ux_m"] == 0.1
    assert nodes[-1]["ux_m"] == -0.02


def test_export_drops_inactive_members_and_rejects_nonfinite_active_output(exporter):
    m, stage = _wall()
    stage.active["pile"][1] = False
    stage.beams["pile"][1] = np.nan
    ends, nodes = exporter.wall_tables(m, stage)
    assert len(ends) == len(nodes) == 2
    stage.beams["pile"][0, 0, 2] = np.nan
    with pytest.raises(ValueError, match="finite"):
        exporter.wall_tables(m, stage)


def test_case_identity_tracks_physics_but_not_mesh_steps_or_split_release(exporter):
    m = exporter.model(1.5, mixed=True, gauss_order="high", rankine_at_apex=True)
    identity = exporter.case_hash(exporter.physical_case(m))
    assert exporter.physical_case(m)["wall_soil_shared_points_m"] == [[0.0, -10.5]]
    assert exporter.physical_case(m)["closed_interface_points_m"] == {
        "pile_left": [[0.0, -10.5]],
        "pile_right": [],
    }
    restored = model_from_dict(model_to_dict(m))
    assert exporter.case_hash(exporter.physical_case(restored)) == identity
    numerical = replace(
        m,
        settings=replace(m.settings, dlam0=0.05),
        stages=[
            m.stages[0],
            replace(m.stages[1], name="half", load_split=0.5),
            m.stages[1],
        ],
    )
    assert exporter.case_hash(exporter.physical_case(numerical)) == identity
    loaded = replace(
        m,
        stages=[
            m.stages[0],
            replace(
                m.stages[1],
                loads=(api.PointLoad(0, fx=10),),
            ),
        ],
    )
    assert exporter.case_hash(exporter.physical_case(loaded)) != identity
    softer = replace(m, liners={"pile": replace(m.liners["pile"], E=1e8)})
    assert exporter.case_hash(exporter.physical_case(softer)) != identity


def test_sensitivity_uses_signed_fields_and_rejects_mismatched_sampling(exporter):
    m, stage = _wall()
    ends, nodes = exporter.wall_tables(m, stage)
    ref = (
        {"case_sha256": "same", "max_abs_moment_kNm_per_m": 11, "max_abs_wall_ux_m": 0.1},
        ends,
        nodes,
    )
    changed = (
        {**ref[0], "max_abs_moment_kNm_per_m": 22},
        [{**r, "M_kNm_per_m": 2 * r["M_kNm_per_m"]} for r in ends],
        [{**r, "ux_m": -r["ux_m"]} for r in nodes],
    )
    differences = exporter.compare_runs(ref, changed)
    assert differences["relative_peak_moment_change"] == 1
    assert differences["relative_moment_field_change"] == 1
    assert differences["relative_wall_ux_field_change"] == 2
    changed[1][0]["local_s"] = -1
    with pytest.raises(ValueError, match="sampling"):
        exporter.compare_runs(ref, changed)
    with pytest.raises(ValueError, match="physical"):
        exporter.compare_runs(ref, ({**ref[0], "case_sha256": "different"}, ends, nodes))


def test_failed_run_cannot_leave_a_success_summary(exporter, monkeypatch, tmp_path):
    m = exporter.model(1.5, rankine_at_apex=True)

    class FailingSolver:
        def __init__(self, model):
            pass

        def run(self):
            raise RuntimeError("deliberate solve failure")

    monkeypatch.setattr(exporter, "StaticSolver", FailingSolver)
    output = tmp_path / "failed"
    with pytest.raises(RuntimeError, match="solve failure"):
        exporter.export_run(m, output)
    assert (output / "model.json").is_file()
    assert not (output / "summary.json").exists()
    with pytest.raises(FileExistsError):
        exporter.export_run(m, output)

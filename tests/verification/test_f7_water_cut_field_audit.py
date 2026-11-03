"""F7: local pore/stress and global reaction errors are independent gates."""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.post.water_cut_field_audit import compare_water_cut_fields


def sample(h, global_error=0., local_error=0., *, head=-2.37, ref=385.78):
    return {
        "h_m": h,
        "head_m": head,
        "global": {
            "expected_ry_kn_per_m": ref,
            "relative_residual": global_error,
            "water_table_cut_elements": 2,
            "reference_method": "exact_polygon_clip",
        },
        "local": {
            "head_m": head,
            "gauss_points": 12,
            "relative_residual": local_error,
            "max_abs_pore_error_kpa": 0.,
            "max_abs_effective_stress_error_kpa": 1.,
            "rms_pore_error_kpa": 0.,
            "rms_effective_stress_error_kpa": 0.4,
        },
    }


def test_global_success_does_not_certify_failed_local_effective_stress():
    report = compare_water_cut_fields([
        sample(2., global_error=0., local_error=.01),
        sample(1., global_error=0., local_error=.001),
    ])
    assert report["finest_global_passed"]
    assert not report["finest_local_passed"]
    assert not report["finest_mesh_passed"]
    assert not report["all_meshes_passed"]
    assert report["meshes"][-1]["local"]["status"] == "failed"


def test_refuses_different_physical_reference_or_mixed_modes():
    with pytest.raises(ValueError, match="same physical reference"):
        compare_water_cut_fields([sample(2.), sample(1., ref=390.)])
    with pytest.raises(ValueError, match="same physical reference"):
        compare_water_cut_fields([sample(2.), sample(1., head=-3.)])
    unsupported = sample(1.)
    unsupported["global"]["reference_method"] = "aligned_mesh"
    with pytest.raises(ValueError, match="exact polygon clipping"):
        compare_water_cut_fields([sample(2.), unsupported])
    not_cut = sample(1.)
    not_cut["global"]["water_table_cut_elements"] = 0
    with pytest.raises(ValueError, match="cut elements"):
        compare_water_cut_fields([sample(2.), not_cut])


def test_rejects_reversed_mesh_order_and_corrupt_local_measurement():
    with pytest.raises(ValueError, match="coarse to fine"):
        compare_water_cut_fields([sample(1.), sample(2.)])
    bad = sample(1.)
    bad["local"]["max_abs_effective_stress_error_kpa"] = float("nan")
    with pytest.raises(ValueError, match="Invalid local error"):
        compare_water_cut_fields([sample(2.), bad])


def test_actual_two_mesh_t3_run_preserves_independent_references():
    script = Path(__file__).resolve().parents[2] / "examples"
    main = runpy.run_path(str(script / "f7_water_cut_field_audit.py"))
    report = main["run_study"]((2, 4), element=ElemType.T3)
    assert len(report["meshes"]) == 2
    assert report["reference_ry_kn_per_m"] == pytest.approx(385.78, rel=1e-10)
    assert report["meshes"][0]["h_m"] == 2.0
    assert report["meshes"][1]["h_m"] == 1.0
    for row in report["meshes"]:
        assert row["global"]["water_table_cut_elements"] > 0
        assert row["local"]["gauss_points"] > 0
        assert row["global"]["reference_method"] == "exact_polygon_clip"
        assert row["global"]["status"] in {"passed", "failed"}
        assert row["local"]["status"] in {"passed", "failed"}

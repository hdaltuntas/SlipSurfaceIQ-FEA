"""F7 relative/absolute structural mesh review diagnostics."""

from slipsurface.fe2d.post.structural_field_review import structural_field_review


def entry(stage, relative, coarse_peak, fine_peak, mode="signed_local"):
    return {
        "stage": stage, "tag": "pile", "kind": "beam", "mode": mode,
        "from_h_m": 1.8, "to_h_m": 1.2, "status": "compared",
        "components": {
            "M": {
                "rms_difference": 0.05, "relative_rms_difference": relative,
                "maximum_absolute_difference": 0.10,
                "station_of_maximum_difference": 0.86,
                "coarse_peak_absolute": coarse_peak,
                "fine_peak_absolute": fine_peak,
            }
        },
    }


def test_small_field_large_ratio_keeps_absolute_context():
    result = structural_field_review({"comparisons": [
        entry("installation", 1.23, 0.05, 0.10),
        entry("final", 0.03, 18.0, 18.7),
    ]})
    assert result["status"] == "diagnostic_only"
    first = result["ranked"][0]
    assert first["stage"] == "installation"
    assert first["pair_peak_absolute"] == 0.10
    assert first["cross_stage_reference_peak"] == 18.7
    assert 0 < first["pair_peak_fraction_of_reference"] < 0.01
    assert "No convergence acceptance" in result["warning"]


def test_sign_mode_scales_are_not_mixed():
    result = structural_field_review({"comparisons": [
        entry("installation", 1.0, 0.1, 0.2, "signed_local"),
        entry("final", 0.1, 10.0, 11.0, "magnitude"),
    ]})
    a, b = result["ranked"]
    assert a["cross_stage_reference_peak"] == 0.2
    assert b["cross_stage_reference_peak"] == 11.0


def test_nan_metric_is_explicitly_incomplete():
    bad = entry("installation", float("nan"), 0.05, 0.1)
    result = structural_field_review({"comparisons": [bad]})
    assert result["status"] == "incomplete"
    assert result["ranked"] == []
    assert result["problems"]


def test_missing_comparisons_do_not_pass():
    assert structural_field_review({})["status"] == "incomplete"
    assert structural_field_review({"comparisons": []})["status"] == "incomplete"


def test_negative_peak_or_outside_station_is_rejected():
    bad = entry("installation", 0.5, -1.0, 2.0)
    assert structural_field_review({"comparisons": [bad]})["status"] == "incomplete"
    bad = entry("installation", 0.5, 1.0, 2.0)
    bad["components"]["M"]["station_of_maximum_difference"] = 1.2
    assert structural_field_review({"comparisons": [bad]})["status"] == "incomplete"

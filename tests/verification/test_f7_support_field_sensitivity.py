"""F7 structural field sensitivity remains descriptive and fail-visible."""

from types import SimpleNamespace

import pytest

from slipsurface.fe2d.post.support_field_sensitivity import support_field_sensitivity

SIZES = (2.5, 1.8, 1.2)
STAGES = (
    SimpleNamespace(name="before", active_structures=frozenset()),
    SimpleNamespace(name="installed", active_structures=frozenset({"pile", "anchor"})),
)


def profile(tag, kind, mode, h):
    n = 3 if kind == "beam" else 1
    return {
        "tag": tag, "kind": kind, "mode": mode,
        "s": [0.0, 0.5, 1.0],
        "components": [[float(i + j + h) for j in range(n)] for i in range(3)],
    }


def rows():
    result = []
    for h in SIZES:
        result.append({"h_m": h, "stage": "before", "profiles": {},
                       "signed_profiles": {}})
        result.append({
            "h_m": h, "stage": "installed",
            "profiles": {
                "pile": profile("pile", "beam", "magnitude", h),
                "anchor": profile("anchor", "bar", "magnitude", h),
            },
            "signed_profiles": {
                "pile": profile("pile", "beam", "signed_local", h),
                "anchor": profile("anchor", "bar", "signed_local", h),
            },
        })
    return result


def check(data):
    return support_field_sensitivity(data, SIZES, STAGES, ("pile",), ("anchor",))


def test_all_three_mesh_profiles_compared():
    result = check(rows())
    assert result["status"] == "diagnostic_only"
    assert result["comparison_count"] == 8
    beam = next(x for x in result["comparisons"]
                if x["tag"] == "pile" and x["mode"] == "signed_local")
    assert set(beam["components"]) == {"N", "V", "M"}
    assert beam["components"]["M"]["relative_rms_difference"] > 0
    assert "acceptance" in result["warning"]


def test_missing_active_profile_is_not_silently_skipped():
    data = rows()
    del data[3]["profiles"]["pile"]
    result = check(data)
    assert result["status"] == "incomplete"
    assert result["incomplete_count"] >= 1


def test_signed_orientation_errors_are_reported_separately():
    data = rows()
    del data[3]["signed_profiles"]["pile"]
    data[3]["signed_profile_errors"] = {"pile": "reversed beam orientation"}
    result = check(data)
    assert any("reversed beam" in x.get("reason", "")
               for x in result["comparisons"])


def test_mismatched_stations_cannot_pass():
    data = rows()
    data[3]["profiles"]["pile"]["s"] = [0.0, 0.4, 1.0]
    assert check(data)["status"] == "incomplete"


def test_nan_moment_does_not_pass():
    data = rows()
    data[3]["profiles"]["pile"]["components"][0][2] = float("nan")
    assert check(data)["status"] == "incomplete"


def test_duplicate_mesh_stage_is_incomplete():
    data = rows()
    data.append(dict(data[3]))
    assert check(data)["status"] == "incomplete"


def test_identical_fields_have_zero_difference():
    data = rows()
    for row in data:
        if row["stage"] == "installed":
            row["profiles"]["pile"] = profile("pile", "beam", "magnitude", 1.0)
            row["signed_profiles"]["pile"] = profile("pile", "beam", "signed_local", 1.0)
    result = check(data)
    values = [x["components"] for x in result["comparisons"] if x["tag"] == "pile"]
    assert all(components["M"]["rms_difference"] == pytest.approx(0.0)
               for components in values)


def test_wrong_mesh_order_rejected():
    with pytest.raises(ValueError, match="coarse-to-fine"):
        support_field_sensitivity(rows(), tuple(reversed(SIZES)), STAGES,
                                  ("pile",), ("anchor",))

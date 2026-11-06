"""F7 CAD-aligned structural N/V/M profile integrity regression tests."""

from types import SimpleNamespace

from slipsurface.fe2d.post.support_profile_integrity import support_profile_integrity

SIZES = (2.5, 1.8, 1.2)
STAGES = (
    SimpleNamespace(name="initial", active_structures=frozenset()),
    SimpleNamespace(name="installed", active_structures=frozenset({"pile", "anchor"})),
)


def profile(tag, kind):
    columns = 3 if kind == "beam" else 1
    return {"tag": tag, "kind": kind, "mode": "magnitude",
            "s": [0.0, 0.5, 1.0],
            "components": [[1.0] * columns for _ in range(3)]}


def rows():
    result = []
    for h in SIZES:
        result.append({"h_m": h, "stage": "initial", "profiles": {}})
        result.append({"h_m": h, "stage": "installed",
                       "profiles": {"pile": profile("pile", "beam"),
                                    "anchor": profile("anchor", "bar")}})
    return result


def check(data):
    return support_profile_integrity(data, SIZES, STAGES, ("pile",), ("anchor",))


def test_complete_profile_coverage():
    result = check(rows())
    assert result["status"] == "diagnostic_complete"
    assert result["passed_profiles"] == 6
    assert result["failed_profiles"] == 0


def test_missing_active_profile_fails():
    data = rows()
    del data[1]["profiles"]["pile"]
    assert check(data)["status"] == "incomplete"


def test_inactive_support_profile_fails():
    data = rows()
    data[0]["profiles"]["pile"] = profile("pile", "beam")
    assert check(data)["failed_profiles"] == 1


def test_duplicate_stage_row_fails():
    data = rows()
    data.append(dict(data[1]))
    assert check(data)["status"] == "incomplete"


def test_nonfinite_nvm_fails():
    data = rows()
    data[1]["profiles"]["pile"]["components"][1][2] = float("nan")
    assert check(data)["status"] == "incomplete"


def test_mismatched_axis_fails():
    data = rows()
    data[3]["profiles"]["pile"]["s"] = [0.0, 0.6, 1.0]
    assert check(data)["status"] == "incomplete"


def test_malformed_profile_fails():
    data = rows()
    data[1]["profiles"]["pile"] = None
    assert check(data)["status"] == "incomplete"


def test_extra_support_tag_fails():
    data = rows()
    data[1]["profiles"]["ghost"] = profile("ghost", "beam")
    assert check(data)["status"] == "incomplete"

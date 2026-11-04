"""F7 interface-moment acceptance distinguishes inactive from missing results."""

from __future__ import annotations

from types import SimpleNamespace

from slipsurface.fe2d.post.interface_moment_acceptance import interface_moment_acceptance

SIZES = (2.5, 1.8, 1.2)
STAGES = (
    SimpleNamespace(name="install", active_structures=frozenset({"left", "right"})),
    SimpleNamespace(name="lift1", active_structures=frozenset({"left", "right"})),
    SimpleNamespace(name="lift2", active_structures=frozenset({"left", "right"})),
)


def make_row(h, stage, *, active=True):
    status = "passed" if active else "unsupported"
    fields = {
        "status": status,
        "active_elements": 2 if active else 0,
    }
    if active:
        fields.update(relative_residual=1e-12, acceptance_tolerance=1e-8)
    return {
        "h_m": h,
        "stage": stage,
        "interface_moment_transfer": {
            "left": dict(fields),
            "right": dict(fields),
        },
    }


def all_rows():
    return [make_row(h, stage.name) for h in SIZES for stage in STAGES]


def test_active_interface_moment_checks_pass_across_all_stages():
    result = interface_moment_acceptance(all_rows(), SIZES, STAGES, {"left", "right"})
    assert result["status"] == "passed"
    assert result["expected_active_checks"] == 18
    assert result["passed"] == 18
    assert result["failed"] == result["missing"] == 0


def test_expected_active_unsupported_interface_fails():
    values = all_rows()
    values[0]["interface_moment_transfer"]["left"] = {
        "status": "unsupported", "active_elements": 0,
    }
    result = interface_moment_acceptance(values, SIZES, STAGES, {"left", "right"})
    assert result["status"] == "failed"
    assert result["failed"] == 1


def test_expected_inactive_interface_must_remain_unsupported():
    stages = (
        SimpleNamespace(name="install", active_structures=frozenset({"left"})),
        SimpleNamespace(name="lift1", active_structures=frozenset({"left", "right"})),
    )
    values = []
    for h in SIZES:
        start = make_row(h, "install")
        start["interface_moment_transfer"]["right"] = {
            "status": "unsupported", "active_elements": 0,
        }
        values.extend((start, make_row(h, "lift1")))
    result = interface_moment_acceptance(values, SIZES, stages, {"left", "right"})
    assert result["status"] == "passed"
    assert result["not_applicable"] == 3
    values[0]["interface_moment_transfer"]["right"] = {
        "status": "passed", "active_elements": 2,
        "relative_residual": 0., "acceptance_tolerance": 1e-8,
    }
    result = interface_moment_acceptance(values, SIZES, stages, {"left", "right"})
    assert result["status"] == "failed"


def test_missing_report_or_mesh_stage_row_fails_closed():
    values = all_rows()
    values[0].pop("interface_moment_transfer")
    values.pop()
    result = interface_moment_acceptance(values, SIZES, STAGES, {"left", "right"})
    assert result["status"] == "failed"
    assert result["missing"] == 2


def test_invalid_moment_error_not_accepted_and_extra_tag_fails():
    values = all_rows()
    values[0]["interface_moment_transfer"]["left"]["relative_residual"] = float("nan")
    values[0]["interface_moment_transfer"]["ghost"] = {
        "status": "passed", "active_elements": 1,
    }
    result = interface_moment_acceptance(values, SIZES, STAGES, {"left", "right"})
    assert result["status"] == "failed"
    assert result["failed"] == 2


def test_missing_interface_tag_fails_even_when_other_interfaces_pass():
    values = all_rows()
    del values[0]["interface_moment_transfer"]["left"]
    result = interface_moment_acceptance(values, SIZES, STAGES, {"left", "right"})
    assert result["status"] == "failed"
    assert result["missing"] == 1

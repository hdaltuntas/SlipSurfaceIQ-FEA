"""Check aggregate interface transfer without claiming external equilibrium."""

from __future__ import annotations

import pytest

from slipsurface.fe2d.post.interface_transfer_ledger import interface_transfer_ledger


def sample(fx=10.0, *, second=-10.0, residual=0.0):
    return {
        "h_m": 2.5, "stage": "installation",
        "interface_nodal_transfer": {
            "left": {
                "active_elements": 2,
                "face1_fx": fx, "face1_fy": 4.0,
                "face2_fx": second, "face2_fy": -4.0,
                "global_residual_fx": residual, "global_residual_fy": 0.0,
                "reference_error_fx": 0.0, "reference_error_fy": 0.0,
            }
        },
    }


def ledger(rows):
    return interface_transfer_ledger(
        rows, (2.5,), ("installation",), ("left",)
    )


def test_reciprocal_interfaces_pass_transfer_only():
    result = ledger([sample()])
    assert result["status"] == "passed"
    assert result["checks"][0]["relative_transfer_residual"] == 0.0
    assert "does not validate" in result["warning"]


def test_imbalanced_face_resultants_fail():
    result = ledger([sample(second=-8.0)])
    assert result["status"] == "failed"


def test_nonzero_nodal_force_residual_fails():
    result = ledger([sample(residual=1.0)])
    assert result["status"] == "failed"


def test_missing_interface_tag_fails_closed():
    item = sample()
    item["interface_nodal_transfer"].clear()
    assert ledger([item])["status"] == "failed"


def test_missing_stage_and_duplicate_rows_fail():
    assert ledger([])["status"] == "failed"
    assert ledger([sample(), sample()])["status"] == "failed"


def test_nonfinite_reference_residual_fails():
    item = sample()
    item["interface_nodal_transfer"]["left"]["reference_error_fx"] = float("nan")
    assert ledger([item])["status"] == "failed"


def test_inactive_only_is_not_physical_validation():
    item = sample()
    item["interface_nodal_transfer"]["left"]["active_elements"] = 0
    result = ledger([item])
    assert result["status"] == "failed"
    assert result["checks"][0]["status"] == "not_applicable"


@pytest.mark.parametrize("field", ["global_residual_fx", "face2_fx"])
def test_opposing_interface_errors_cannot_cancel(field):
    row = sample()
    left = row["interface_nodal_transfer"]["left"]
    right = dict(left)
    left[field] += 1.0
    right[field] -= 1.0
    row["interface_nodal_transfer"]["right"] = right
    result = interface_transfer_ledger(
        [row], (2.5,), ("installation",), ("left", "right")
    )
    assert result["status"] == "failed"
    check = result["checks"][0]
    assert check["relative_transfer_residual"] == 0.0
    assert all(item["status"] == "failed" for item in check["interfaces"].values())


def test_large_neighbor_cannot_hide_small_interface_reference_error():
    row = sample(fx=1e12, second=-1e12)
    small = sample()["interface_nodal_transfer"]["left"]
    small["reference_error_fx"] = 0.01
    row["interface_nodal_transfer"]["small"] = small
    result = interface_transfer_ledger(
        [row], (2.5,), ("installation",), ("left", "small")
    )
    assert result["status"] == "failed"
    assert result["checks"][0]["interfaces"]["small"]["status"] == "failed"

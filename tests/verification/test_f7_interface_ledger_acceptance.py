"""Stage-aware interface transfer acceptance remains fail-closed."""

from __future__ import annotations

from types import SimpleNamespace

from slipsurface.fe2d.post.interface_ledger_acceptance import interface_ledger_acceptance

SIZES = (2.5, 1.8, 1.2)
STAGES = (
    SimpleNamespace(name="initial", active_structures=frozenset()),
    SimpleNamespace(name="excavation", active_structures=frozenset({"skin"})),
)


def example():
    checks = []
    for h in SIZES:
        checks.extend([
            {"h_m": h, "stage": "initial", "status": "not_applicable"},
            {"h_m": h, "stage": "excavation", "status": "passed",
             "active_interface_elements": 3, "relative_transfer_residual": 0.0},
        ])
    return {"status": "passed", "tolerance": 1e-9, "checks": checks}


def validate(ledger):
    return interface_ledger_acceptance(ledger, SIZES, STAGES, ("skin",))


def test_expected_active_and_inactive_stages_pass():
    assert validate(example())["status"] == "passed"


def test_expected_active_cannot_be_marked_not_applicable():
    ledger = example()
    ledger["checks"][1]["status"] = "not_applicable"
    assert validate(ledger)["status"] == "failed"


def test_inactive_stage_cannot_claim_active_transfer_pass():
    ledger = example()
    ledger["checks"][0]["status"] = "passed"
    assert validate(ledger)["status"] == "failed"


def test_missing_and_duplicate_rows_fail_closed():
    ledger = example()
    ledger["checks"].pop()
    assert validate(ledger)["status"] == "failed"
    ledger = example()
    ledger["checks"].append(dict(ledger["checks"][0]))
    assert validate(ledger)["status"] == "failed"


def test_nonfinite_and_outside_tolerance_fail():
    ledger = example()
    ledger["checks"][1]["relative_transfer_residual"] = float("nan")
    assert validate(ledger)["status"] == "failed"
    ledger = example()
    ledger["checks"][1]["relative_transfer_residual"] = 0.01
    assert validate(ledger)["status"] == "failed"


def test_zero_active_elements_cannot_pass():
    ledger = example()
    ledger["checks"][1]["active_interface_elements"] = 0
    assert validate(ledger)["status"] == "failed"


def test_global_failed_ledger_cannot_pass():
    ledger = example()
    ledger["status"] = "failed"
    assert validate(ledger)["status"] == "failed"

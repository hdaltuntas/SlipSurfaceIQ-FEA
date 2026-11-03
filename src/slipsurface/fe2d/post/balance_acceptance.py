"""Shared acceptance classifier for the bounded F7 global equilibrium audits.

A completed numerical calculation is not automatically a passing force
balance. Keep unsupported, numerical failure and accepted separate.
"""

from __future__ import annotations

import math


def classify_balance(row: dict, metric: str, *, tolerance: float = 1e-6) -> dict:
    """Return an annotated copy; never silently certify nonfinite residuals."""
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("Balance tolerance must be finite and positive")
    value = float(row[metric])
    result = dict(row)
    result["acceptance_tolerance"] = tolerance
    if not math.isfinite(value) or value < 0:
        result["status"] = "failed"
        result["reason"] = f"Invalid relative force imbalance: {value}"
    elif value <= tolerance:
        result["status"] = "passed"
    else:
        result["status"] = "failed"
        result["reason"] = (
            f"Relative force imbalance {value:.6g} exceeds {tolerance:.6g}"
        )
    return result


def summarize_balances(rows: list[dict]) -> dict:
    """Count audited stages without interpreting unsupported as passing."""
    statuses = ("passed", "failed", "unsupported")
    counts = {state: sum(row.get("status") == state for row in rows)
              for state in statuses}
    unknown = len(rows) - sum(counts.values())
    if unknown:
        raise ValueError("Unknown balance status in report")
    return {
        **counts,
        "total": len(rows),
        "all_supported_passed": counts["failed"] == 0 and counts["passed"] > 0,
        "fully_verified": counts["failed"] == 0
        and counts["unsupported"] == 0
        and counts["passed"] == len(rows)
        and bool(rows),
    }

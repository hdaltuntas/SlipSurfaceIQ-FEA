"""Summarize real F7 evidence without mistaking diagnostics for validation.

Run: python scripts/f7_evidence_review.py f7_audit/excavation_mesh_audit.json
Produces a human-readable review beside the input JSON; the FEM job's
existing acceptance exit status remains authoritative.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def summarize(report):
    """Return a conservative, structured review of an actual F7 audit."""
    rows = report.get("results", [])
    failures = report.get("failures", [])
    coverage = report.get("mesh_stage_coverage", {})
    sizes = report.get("mesh_sizes_m", [])
    balances = report.get("force_balance_acceptance", {})
    reasons = Counter()
    for field in ("gravity_balance", "dry_load_balance", "excavation_balance"):
        for item in report.get(field, []):
            if item.get("status") == "unsupported":
                reasons[(field, item.get("reason", "unspecified"))] += 1

    sensitivity = report.get("mesh_sensitivity_diagnostics", {})
    alerts = []
    for item in sensitivity.get("metrics", []):
        if item.get("status") != "compared":
            alerts.append({
                "type": "incomplete_metric", "stage": item.get("stage"),
                "kind": item.get("kind"), "tag": item.get("tag"),
            })
            continue
        if item.get("kind") != "beam_moments":
            continue
        pair = _number(item.get("finest_pair_relative_change"))
        if pair is None:
            continue
        # This is a *review priority*, never a physical acceptance criterion.
        if pair >= 0.25:
            values = item.get("values", [])
            peaks = [_number(v.get("value")) for v in values if isinstance(v, dict)]
            absolute = [abs(v) for v in peaks if v is not None]
            alerts.append({
                "type": "review_peak_mesh_change", "stage": item.get("stage"),
                "kind": item.get("kind"), "tag": item.get("tag"),
                "finest_pair_relative_change": pair,
                "maximum_reported_peak": max(absolute) if absolute else None,
                "interpretation": (
                    "Large relative change: inspect spatial profiles and absolute "
                    "magnitudes; no engineering tolerance assigned."
                ),
            })

    profiles = []
    for item in report.get("profile_comparisons", []):
        if item.get("status") != "compared":
            continue
        comps = item.get("relative_rms_components")
        if not isinstance(comps, list):
            continue
        finite = [_number(x) for x in comps]
        profiles.append({
            "stage": item.get("stage"), "h_m": item.get("h_m"),
            "tag": item.get("tag"),
            "component_relative_rms": finite,
        })

    return {
        "mesh_sizes_m": sizes,
        "completed_rows": len(rows),
        "expected_rows": coverage.get("expected_rows"),
        "coverage_complete": coverage.get("complete") is True,
        "solver_failures": len(failures),
        "balance_status": {
            key: {
                "passed": value.get("passed", 0),
                "failed": value.get("failed", 0),
                "unsupported": value.get("unsupported", 0),
            }
            for key, value in balances.items() if isinstance(value, dict)
        },
        "unsupported_reasons": [
            {"check": check, "reason": reason, "count": count}
            for (check, reason), count in sorted(reasons.items())
        ],
        "review_priorities": alerts,
        "profile_comparisons": profiles,
        "physical_validation": "not_established",
        "warning": (
            "Green workflow results establish bounded execution/integrity only. "
            "Unsupported force budgets and mesh sensitivities are not passed "
            "physical checks or independent RS2/PLAXIS benchmarks."
        ),
    }


def markdown(summary):
    lines = [
        "# F7 actual FEM evidence review", "",
        f"- Mesh targets (m): {summary['mesh_sizes_m']}",
        f"- Completed stage rows: {summary['completed_rows']} / {summary['expected_rows']}",
        f"- Coverage complete: {summary['coverage_complete']}",
        f"- Solver failures: {summary['solver_failures']}",
        "- Independent physical validation: **not established**", "",
        "## Force balance classification", "",
        "| Check | Passed | Failed | Unsupported |",
        "|---|---:|---:|---:|",
    ]
    for key, value in summary["balance_status"].items():
        lines.append(
            f"| {key} | {value['passed']} | {value['failed']} | "
            f"{value['unsupported']} |"
        )
    lines.extend(["", "## Why checks remain unsupported", ""])
    if not summary["unsupported_reasons"]:
        lines.append("No unsupported classifications reported.")
    for entry in summary["unsupported_reasons"]:
        lines.append(
            f"- {entry['check']} ({entry['count']}): {entry['reason']}"
        )
    lines.extend(["", "## Peak sensitivity review priorities (not pass/fail)", ""])
    if not summary["review_priorities"]:
        lines.append("No flagged peak changes or incomplete metrics.")
    for item in summary["review_priorities"]:
        change = item.get("finest_pair_relative_change")
        detail = f" ({100 * change:.2f}% finest-pair change)" if change is not None else ""
        lines.append(
            f"- {item.get('stage')}: {item.get('kind')}/{item.get('tag')}{detail}"
        )
    lines.extend(["", "## Spatial structural profile comparison", "",
                  "Component relative RMS values are diagnostics only."])
    for item in summary["profile_comparisons"]:
        values = ", ".join(
            "missing" if value is None else f"{value:.4g}"
            for value in item["component_relative_rms"]
        )
        lines.append(f"- {item['stage']} at h={item['h_m']} m, {item['tag']}: {values}")
    lines.extend(["", summary["warning"], ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    result = summarize(data)
    parent = args.input.parent
    (parent / "f7_evidence_review.json").write_text(
        json.dumps(result, indent=2, allow_nan=False), encoding="utf-8"
    )
    (parent / "f7_evidence_review.md").write_text(
        markdown(result), encoding="utf-8"
    )
    print(markdown(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

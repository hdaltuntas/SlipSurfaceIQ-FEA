"""Descriptive F7 mesh sensitivity metrics; never an engineering acceptance gate.

Peak quantities can shift spatial location between meshes; relative peak changes
are diagnostics only and cannot establish convergence or independent validation.
"""

from __future__ import annotations

import math


def _scalar(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _relative_change(first, second):
    return abs(second - first) / max(abs(first), abs(second), 1e-12)


def mesh_sensitivity_diagnostics(rows, sizes, stages):
    """Compare per-stage displacement and tagged structural peaks across meshes.

    Missing, duplicate and nonfinite values are reported, not substituted with
    zeros. The finest-pair change is exposed without an invented tolerance.
    """
    sizes = tuple(float(h) for h in sizes)
    stages = tuple(stages)
    if (len(sizes) < 3 or len(set(sizes)) != len(sizes)
            or any(not math.isfinite(h) or h <= 0 for h in sizes)
            or any(a <= b for a, b in zip(sizes, sizes[1:]))):
        raise ValueError("Require at least three distinct coarse-to-fine mesh sizes")
    if not stages or len(set(stages)) != len(stages):
        raise ValueError("Stage names must be nonempty and unique")
    results = []
    for stage in stages:
        samples = []
        problems = []
        for h in sizes:
            matched = [row for row in rows
                       if row.get("h_m") == h and row.get("stage") == stage]
            if len(matched) != 1:
                problems.append({"h_m": h, "reason": "expected exactly one stage row",
                                 "found": len(matched)})
            samples.append(matched[0] if len(matched) == 1 else None)

        identities = {("displacement", "maximum")}
        for sample in samples:
            if sample is None:
                continue
            supports = sample.get("supports", {})
            if not isinstance(supports, dict):
                problems.append({"reason": "malformed support metrics"})
                continue
            for kind in ("beam_moments", "bar_axial_forces"):
                values = supports.get(kind, {})
                if not isinstance(values, dict):
                    problems.append({"reason": "malformed support category", "kind": kind})
                    continue
                identities.update((kind, tag) for tag in values)
        for kind, tag in sorted(identities):
            values = []
            for h, sample in zip(sizes, samples):
                raw = None
                if sample is not None:
                    if kind == "displacement":
                        raw = sample.get("max_displacement_m")
                    else:
                        support = sample.get("supports", {})
                        data = support.get(kind, {}) if isinstance(support, dict) else {}
                        raw = data.get(tag) if isinstance(data, dict) else None
                value = _scalar(raw)
                if value is None:
                    problems.append({"h_m": h, "kind": kind, "tag": tag,
                                     "reason": "missing or nonfinite metric"})
                values.append(value)
            comparisons = []
            for i in range(1, len(sizes)):
                a, b = values[i - 1:i + 1]
                comparisons.append({
                    "from_h_m": sizes[i - 1], "to_h_m": sizes[i],
                    "relative_change": (_relative_change(a, b)
                                        if a is not None and b is not None else None),
                })
            results.append({
                "stage": stage, "kind": kind, "tag": tag,
                "values": [{"h_m": h, "value": value}
                           for h, value in zip(sizes, values)],
                "pair_changes": comparisons,
                "finest_pair_relative_change": comparisons[-1]["relative_change"],
                "status": "compared" if all(v is not None for v in values) else "incomplete",
            })
        if problems:
            results.append({"stage": stage, "kind": "data_quality",
                            "tag": "missing_or_invalid", "status": "incomplete",
                            "problems": problems})
    return {
        "status": "diagnostic_only" if all(x["status"] == "compared" for x in results)
                  else "incomplete",
        "mesh_sizes_m": list(sizes),
        "metrics": results,
        "warning": (
            "Peak changes are not a convergence certification. Inspect field profiles, "
            "stage equilibrium, refinement trends and independent benchmarks. "
            "No pass/fail tolerance has been assigned."
        ),
    }

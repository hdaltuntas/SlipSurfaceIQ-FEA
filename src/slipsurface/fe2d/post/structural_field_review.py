"""Interpret F7 mesh sensitivity with relative and absolute scales together.

This is a descriptive review. It does not set a physical acceptance limit:
low-amplitude fields can have large relative RMS differences.
"""

from __future__ import annotations

import math


def _finite(value):
    return (isinstance(value, (int, float))
            and not isinstance(value, bool) and math.isfinite(value))


def structural_field_review(sensitivity):
    """Rank finest-pair component differences with cross-stage peak context."""
    comparisons = sensitivity.get("comparisons") if isinstance(sensitivity, dict) else None
    if not isinstance(comparisons, list):
        return {"status": "incomplete", "ranked": [], "problems": ["Missing comparisons"]}
    scales = {}
    problems = []
    evaluated = []
    for i, entry in enumerate(comparisons):
        if not isinstance(entry, dict) or entry.get("status") != "compared":
            problems.append(f"Comparison {i} is missing or incomplete")
            continue
        stage, tag, mode, kind = (entry.get(k) for k in ("stage", "tag", "mode", "kind"))
        if not all(isinstance(x, str) and x for x in (stage, tag, mode, kind)):
            problems.append(f"Comparison {i}: invalid identity")
            continue
        components = entry.get("components")
        if not isinstance(components, dict) or not components:
            problems.append(f"Comparison {i}: no components")
            continue
        for name, values in components.items():
            if not isinstance(values, dict):
                problems.append(f"Comparison {i}/{name}: malformed data")
                continue
            keys = (
                "rms_difference", "relative_rms_difference",
                "maximum_absolute_difference", "station_of_maximum_difference",
                "coarse_peak_absolute", "fine_peak_absolute",
            )
            if any(not _finite(values.get(k)) for k in keys):
                problems.append(f"Comparison {i}/{name}: nonfinite data")
                continue
            if (values["rms_difference"] < 0 or values["relative_rms_difference"] < 0
                    or values["maximum_absolute_difference"] < 0
                    or values["coarse_peak_absolute"] < 0 or values["fine_peak_absolute"] < 0
                    or not 0 <= values["station_of_maximum_difference"] <= 1):
                problems.append(f"Comparison {i}/{name}: invalid magnitudes/station")
                continue
            peak = max(values["coarse_peak_absolute"], values["fine_peak_absolute"])
            key = (tag, mode, name)
            scales[key] = max(scales.get(key, 0.0), peak)
            evaluated.append({
                "stage": stage, "tag": tag, "kind": kind, "mode": mode,
                "component": name,
                "from_h_m": entry.get("from_h_m"),
                "to_h_m": entry.get("to_h_m"),
                "relative_rms_difference": values["relative_rms_difference"],
                "rms_difference": values["rms_difference"],
                "maximum_absolute_difference": values["maximum_absolute_difference"],
                "station_of_maximum_difference": values["station_of_maximum_difference"],
                "pair_peak_absolute": peak,
                "_key": key,
            })
    for item in evaluated:
        largest = scales[item.pop("_key")]
        item["cross_stage_reference_peak"] = largest
        item["pair_peak_fraction_of_reference"] = (
            item["pair_peak_absolute"] / largest if largest > 0 else None
        )
    ranked = sorted(evaluated, key=lambda x: x["relative_rms_difference"], reverse=True)
    return {
        "status": "diagnostic_only" if ranked and not problems else "incomplete",
        "ranked": ranked,
        "problems": problems,
        "warning": (
            "Relative RMS and absolute differences must be read together. "
            "The reference peak is the largest observed peak for the same "
            "support, component and sign mode across the sampled stages; "
            "it is not capacity or an independent physical reference. "
            "No convergence acceptance tolerance is implied."
        ),
    }

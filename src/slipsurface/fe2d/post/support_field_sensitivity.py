"""Station-aligned F7 N/V/M field sensitivity diagnostics.

Compare full sampled support fields, not only peak forces. Results are
descriptive: neither a mesh-convergence acceptance threshold nor an
independent physical benchmark is implied.
"""

from __future__ import annotations

import math

import numpy as np


def _profile(profile, *, tag, kind, mode):
    if not isinstance(profile, dict):
        raise ValueError("Missing profile")
    if (profile.get("tag") != tag or profile.get("kind") != kind
            or profile.get("mode") != mode):
        raise ValueError("Profile identity, kind or mode mismatch")
    stations = np.asarray(profile.get("s"), dtype=float)
    fields = np.asarray(profile.get("components"), dtype=float)
    ncol = 3 if kind == "beam" else 1
    if (stations.ndim != 1 or len(stations) < 2
            or fields.shape != (len(stations), ncol)):
        raise ValueError("Invalid station or component dimensions")
    if (not np.isfinite(stations).all() or not np.isfinite(fields).all()
            or not np.isclose(stations[0], 0.0)
            or not np.isclose(stations[-1], 1.0)
            or np.any(np.diff(stations) <= 0)):
        raise ValueError("Nonfinite or invalid CAD stations/forces")
    if mode == "magnitude" and np.any(fields < 0):
        raise ValueError("Negative force in magnitude profile")
    return stations, fields


def _compare(before, after, *, tag, kind, mode):
    x0, a = _profile(before, tag=tag, kind=kind, mode=mode)
    x1, b = _profile(after, tag=tag, kind=kind, mode=mode)
    if not np.array_equal(x0, x1):
        raise ValueError("Mesh profiles use different normalized CAD stations")
    delta = b - a
    rms_delta = np.sqrt(np.mean(delta * delta, axis=0))
    rms_a = np.sqrt(np.mean(a * a, axis=0))
    rms_b = np.sqrt(np.mean(b * b, axis=0))
    scale = np.maximum(np.maximum(rms_a, rms_b), 1e-12)
    peak_delta_index = np.argmax(np.abs(delta), axis=0)
    cols = ("N", "V", "M") if kind == "beam" else ("axial",)
    return {
        component: {
            "rms_difference": float(rms_delta[j]),
            "relative_rms_difference": float(rms_delta[j] / scale[j]),
            "maximum_absolute_difference": float(np.abs(delta[:, j]).max()),
            "station_of_maximum_difference": float(x0[peak_delta_index[j]]),
            "coarse_peak_absolute": float(np.abs(a[:, j]).max()),
            "fine_peak_absolute": float(np.abs(b[:, j]).max()),
        }
        for j, component in enumerate(cols)
    }


def support_field_sensitivity(rows, sizes, stages, beams, bars):
    """Compare successive meshes for every stage-active support profile.

    Magnitude and signed local fields are reported separately. A signed
    orientation error is recorded as an unsupported comparison, never
    silently replaced by a magnitude comparison.
    """
    sizes = tuple(float(h) for h in sizes)
    steps = tuple(stages)
    if (len(sizes) < 3 or len(set(sizes)) != len(sizes)
            or any(not math.isfinite(h) or h <= 0 for h in sizes)
            or any(a <= b for a, b in zip(sizes, sizes[1:]))):
        raise ValueError("Require three or more distinct coarse-to-fine meshes")
    names = [step.name for step in steps]
    if not names or len(set(names)) != len(names):
        raise ValueError("Stage names must be unique")
    tags = {**{tag: "beam" for tag in beams}, **{tag: "bar" for tag in bars}}
    if not tags or len(tags) != len(set(beams)) + len(set(bars)):
        raise ValueError("Support tag identities must be disjoint and nonempty")

    findings = []
    for step in steps:
        for tag, kind in sorted(tags.items()):
            if tag not in step.active_structures:
                continue
            for mode, key in (("magnitude", "profiles"),
                              ("signed_local", "signed_profiles")):
                for i in range(1, len(sizes)):
                    h0, h1 = sizes[i - 1:i + 1]
                    pair = []
                    reason = None
                    for h in (h0, h1):
                        matches = [r for r in rows
                                   if r.get("h_m") == h and r.get("stage") == step.name]
                        if len(matches) != 1:
                            reason = "Missing or duplicate mesh-stage record"
                            break
                        row = matches[0]
                        profiles = row.get(key)
                        if not isinstance(profiles, dict) or tag not in profiles:
                            errors = row.get("signed_profile_errors", {})
                            if mode == "signed_local" and isinstance(errors, dict):
                                reason = errors.get(tag, "Missing signed profile")
                            else:
                                reason = "Active support profile missing"
                            break
                        pair.append(profiles[tag])
                    components = None
                    if reason is None:
                        try:
                            components = _compare(
                                pair[0], pair[1], tag=tag, kind=kind, mode=mode
                            )
                        except (ValueError, TypeError) as exc:
                            reason = str(exc)
                    findings.append({
                        "stage": step.name, "tag": tag, "kind": kind,
                        "mode": mode, "from_h_m": h0, "to_h_m": h1,
                        "status": "compared" if reason is None else "incomplete",
                        "components": components,
                        **({"reason": reason} if reason is not None else {}),
                    })
    complete = bool(findings) and all(x["status"] == "compared" for x in findings)
    return {
        "status": "diagnostic_only" if complete else "incomplete",
        "comparisons": findings,
        "comparison_count": sum(x["status"] == "compared" for x in findings),
        "incomplete_count": sum(x["status"] == "incomplete" for x in findings),
        "warning": (
            "Full CAD-aligned N/V/M field differences are mesh sensitivity "
            "diagnostics, not convergence acceptance, support design capacity "
            "checks, or independent RS2/PLAXIS validation."
        ),
    }

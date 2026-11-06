"""Branch-labelled closed-form dilatant interface verification (not a general return solver).

The reference uses scalar consistency equations for explicitly selected elastic,
single-shear, tension, shear/tension corner and apex cases. It never calls the
native return mapper or uses its assembled matrices to generate expected values.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from slipsurface.fe2d.core.enums import Analysis, ElemType, PlasticFlag
from slipsurface.fe2d.fem.structural import InterfaceGroup
from slipsurface.fe2d.model.materials import InterfaceSpec
from slipsurface.fe2d.model.mesh import ElementBlock

ANALYTICAL_TOLERANCE = 1e-9
FINITE_DIFFERENCE_TOLERANCE = 1e-6


def closed_form(trial, *, ks, kn, cohesion, phi, psi, tensile_cap, branch, sign=1):
    """Return a preselected branch's exact traction and jump derivative.

    Positive sigma denotes tension. Multipliers must be strictly positive and
    inactive planes strictly admissible: branch-switching points are excluded
    from this differentiable benchmark, rather than assigned an arbitrary tangent.
    """
    raw = (*trial, ks, kn, cohesion, phi, psi, tensile_cap)
    if len(trial) != 2 or any(isinstance(x, (bool, np.bool_)) for x in raw):
        raise ValueError("Expected two real trial tractions and numeric properties")
    if not all(math.isfinite(x) for x in raw):
        raise ValueError("Trial tractions and properties must be finite")
    if ks <= 0 or kn <= 0 or cohesion < 0 or tensile_cap < 0 or not 0 <= psi <= phi < 90:
        raise ValueError("Invalid interface stiffness or strengths/angles")
    if isinstance(sign, bool) or sign not in (-1, 1):
        raise ValueError("Shear sign must be -1 or +1")
    ts, tn = trial
    f, g = math.tan(math.radians(phi)), math.tan(math.radians(psi))
    cap = min(tensile_cap, cohesion / f) if f > 0 else tensile_cap
    active, multipliers = [], {}
    tangent = np.diag([float(ks), float(kn)])
    tau, normal, flag = ts, tn, PlasticFlag.ELASTIC
    shear_plane = 0 if sign == 1 else 1
    if branch == "shear":
        denom = ks + kn * f * g
        lam = (sign * ts + f * tn - cohesion) / denom
        tau, normal = ts - sign * ks * lam, tn - kn * g * lam
        tangent = np.array([
            [ks * kn * f * g, -sign * ks * kn * f],
            [-sign * ks * kn * g, ks * kn],
        ]) / denom
        active, multipliers, flag = [shear_plane], {"shear": lam}, PlasticFlag.SHEAR
    elif branch == "tension":
        normal = cap
        tangent = np.diag([float(ks), 0.0])
        active, multipliers = [2], {"tension": (tn - cap) / kn}
        flag = PlasticFlag.TENSION
    elif branch == "corner":
        if f > 0 and cap >= cohesion / f:
            raise ValueError("Use the apex branch when the cap reaches the apex")
        tau, normal = sign * (cohesion - f * cap), cap
        lam_s = sign * (ts - tau) / ks
        multipliers = {"shear": lam_s, "tension": (tn - cap) / kn - g * lam_s}
        tangent, active, flag = np.zeros((2, 2)), [shear_plane, 2], PlasticFlag.TENSION
    elif branch == "apex":
        if f <= 0 or g <= 0 or tensile_cap < cohesion / f:
            raise ValueError("Apex reference requires positive friction/dilation and a high cap")
        tau, normal = 0.0, cohesion / f
        total = (tn - normal) / (kn * g)
        difference = ts / ks
        multipliers = {"positive_shear": (total + difference) / 2,
                       "negative_shear": (total - difference) / 2}
        tangent, active, flag = np.zeros((2, 2)), [0, 1, 2], PlasticFlag.APEX
    elif branch != "elastic":
        raise ValueError("Unknown analytical branch")
    planes = np.array([tau + f * normal - cohesion, -tau + f * normal - cohesion,
                       normal - cap])
    tol = 1e-10 * max(1.0, abs(ts), abs(tn), cohesion, abs(cap))
    if any(value <= 1e-12 for value in multipliers.values()):
        raise ValueError("Selected branch has a nonpositive multiplier or lies at a switch")
    for i, value in enumerate(planes):
        if (i in active and abs(value) > tol) or (i not in active and value >= -tol):
            raise ValueError("Selected branch is inadmissible or lies at a branch switch")
    return {"traction": [float(tau), float(normal)], "tangent": tangent.tolist(),
            "flag": int(flag), "multipliers": multipliers, "effective_tensile_cap": cap}


def benchmark_cases():
    """Fixed trial values deliberately inside branch regions, not on switches."""
    cases = [
        ("elastic", (1.0, -20.0), "elastic", 1, 10.0, 1.0),
        ("positive_dilatant_shear", (40.0, -20.0), "shear", 1, 10.0, 1.0),
        ("negative_dilatant_shear", (-40.0, -20.0), "shear", -1, 10.0, 1.0),
        ("tensile_trial_returns_to_compression", (30.0, 3.0), "shear", 1, 10.0, 1.0),
        ("tensile_cap_only", (1.0, 8.0), "tension", 1, 10.0, 1.0),
        ("positive_shear_tension_corner", (30.0, 25.0), "corner", 1, 10.0, 1.0),
        ("negative_shear_tension_corner", (-30.0, 25.0), "corner", -1, 10.0, 1.0),
        ("two_shear_plane_apex", (2.0, 30.0), "apex", 1, 10.0, 50.0),
        ("associated_shear", (40.0, -20.0), "shear", 1, 30.0, 1.0),
        ("associated_corner", (30.0, 50.0), "corner", 1, 30.0, 1.0),
        ("nondilatant_limit", (40.0, -20.0), "shear", 1, 0.0, 1.0),
    ]
    return [dict(name=name, trial=trial, branch=branch, sign=sign, psi=psi,
                 tensile_cap=cap, ks=1000.0, kn=2000.0, cohesion=5.0, phi=30.0)
            for name, trial, branch, sign, psi, cap in cases]


def _error(actual, expected, tolerance):
    a, b = np.asarray(actual, dtype=float), np.asarray(expected, dtype=float)
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        return {"status": "failed", "absolute_error": None, "normalized_error": None,
                "tolerance": tolerance, "reason": "Nonfinite numerical/reference result"}
    absolute = float(np.max(np.abs(a - b)))
    normalized = absolute / max(1.0, float(np.max(np.abs(b))))
    return {"status": "passed" if normalized <= tolerance else "failed",
            "absolute_error": absolute, "normalized_error": normalized, "tolerance": tolerance}


def run_case(case, *, length=4.0, angle_deg=0.0, element_type="IFACE4"):
    """Compare native tractions and the full assembled tangent to the closed form."""
    if not math.isfinite(length) or length <= 0 or not math.isfinite(angle_deg):
        raise ValueError("Length must be positive and geometry finite")
    if element_type not in ("IFACE4", "IFACE6"):
        raise ValueError("Only straight IFACE4/IFACE6 plane-strain cases are supported")
    args = {k: case[k] for k in ("ks", "kn", "cohesion", "phi", "psi",
                                "tensile_cap", "branch", "sign")}
    expected = closed_form(case["trial"], **args)
    angle = math.radians(angle_deg)
    rotation = np.array([[math.cos(angle), -math.sin(angle)],
                         [math.sin(angle), math.cos(angle)]])
    # These analytical shape-function integrals do not use group.w or group._assemble.
    locations = np.array([0.0, 1.0] if element_type == "IFACE4" else [0.0, 1.0, 0.5])
    weights = length * np.array([0.5, 0.5] if element_type == "IFACE4"
                                else [1 / 6, 1 / 6, 2 / 3])
    n = len(locations)
    face = np.array([1.25, -2.5]) + length * locations[:, None] * rotation[:, 0]
    block = ElementBlock(ElemType[element_type], np.arange(2 * n)[None, :],
                         np.array([0]), "joint")
    spec = InterfaceSpec("joint", kn=case["kn"], ks=case["ks"], c=case["cohesion"],
                         phi=case["phi"], psi=case["psi"], sig_t=case["tensile_cap"])
    group = InterfaceGroup(block, np.vstack([face, face]), spec, Analysis.PLANE_STRAIN)
    ids, state = np.array([0]), group.zero_state()
    group.activate(state, ids)
    original = state["t"].copy()
    local_jump = np.asarray(case["trial"]) / [case["ks"], case["kn"]]
    du = np.zeros((1, 4 * n))
    du[0, 2 * n:] = np.tile(rotation @ local_jump, n)
    updated, forces, tangent, flags = group.integrate(state, ids, du, None)
    traction = np.asarray(expected["traction"])
    point_forces = weights[:, None] * (rotation @ traction)
    reference_force = np.vstack([-point_forces, point_forces]).ravel()
    local_tangent = np.asarray(expected["tangent"])
    reference_tangent = np.zeros((4 * n, 4 * n))
    for j, weight in enumerate(weights):
        one, two = slice(2 * j, 2 * j + 2), slice(2 * (n + j), 2 * (n + j) + 2)
        stiffness = weight * rotation @ local_tangent @ rotation.T
        reference_tangent[one, one] += stiffness
        reference_tangent[two, two] += stiffness
        reference_tangent[one, two] -= stiffness
        reference_tangent[two, one] -= stiffness
    numerical_derivative = np.empty_like(reference_tangent)
    epsilon = 1e-7  # metres; fixed fixtures stay far from branch switching.
    for j in range(4 * n):
        increment = np.zeros_like(du)
        increment[0, j] = epsilon
        plus = group.integrate(state, ids, du + increment, None)[1][0]
        minus = group.integrate(state, ids, du - increment, None)[1][0]
        numerical_derivative[:, j] = (plus - minus) / (2 * epsilon)
    checks = {
        "traction_kpa": _error(updated["t"][0], traction, ANALYTICAL_TOLERANCE),
        "nodal_force_kn_per_m": _error(forces[0], reference_force, ANALYTICAL_TOLERANCE),
        "tangent_kn_per_m2": _error(tangent[0], reference_tangent, ANALYTICAL_TOLERANCE),
        "finite_difference_kn_per_m2": _error(numerical_derivative, tangent[0],
                                              FINITE_DIFFERENCE_TOLERANCE),
        "force_reciprocity_kn_per_m": _error(forces[0].reshape(-1, 2).sum(axis=0),
                                              np.zeros(2), ANALYTICAL_TOLERANCE),
    }
    flags_match = bool(np.all(flags == expected["flag"]))
    state_unchanged = bool(np.array_equal(state["t"], original))
    passed = flags_match and state_unchanged and all(x["status"] == "passed"
                                                   for x in checks.values())
    return {"name": case["name"], "status": "passed" if passed else "failed",
            "element_type": element_type, "length_m": length, "angle_deg": angle_deg,
            "input": case, "reference": expected, "checks": checks,
            "observed_traction": updated["t"][0].tolist(),
            "observed_flags": flags[0].tolist(), "flags_match": flags_match,
            "committed_state_unchanged": state_unchanged}


def run_benchmark(*, length=4.0, angle_deg=0.0, element_type="IFACE4"):
    rows = [run_case(case, length=length, angle_deg=angle_deg, element_type=element_type)
            for case in benchmark_cases()]
    return {"status": "passed" if all(row["status"] == "passed" for row in rows)
            else "failed", "case_count": len(rows), "results": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    runs = [run_benchmark(element_type=etype, angle_deg=angle)
            for etype in ("IFACE4", "IFACE6") for angle in (0.0, 37.0, -63.0)]
    report = {
        "status": "passed" if all(run["status"] == "passed" for run in runs) else "failed",
        "case_count": sum(run["case_count"] for run in runs), "runs": runs,
        "analytical_tolerance": ANALYTICAL_TOLERANCE,
        "finite_difference_tolerance": FINITE_DIFFERENCE_TOLERANCE,
        "scope": "Isolated straight dry interfaces; labelled smooth branch regions only. "
                 "No arbitrary load-history, hydraulic, soil-coupling or excavation validation.",
    }
    payload = json.dumps(report, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

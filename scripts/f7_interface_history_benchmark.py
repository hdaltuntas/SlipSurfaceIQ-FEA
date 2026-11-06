"""Verify committed interface histories; do not equate a tensile cap with contact.

Expected stresses advance from independent plastic jumps and the PR #74 scalar
branch reference, never from the native returned stresses. Trials are discarded
until explicitly committed. No production constitutive code is changed.
"""

from __future__ import annotations

import argparse
import json
import math
import runpy
from pathlib import Path

import numpy as np

from slipsurface.fe2d.core.enums import Analysis, ElemType
from slipsurface.fe2d.fem.structural import InterfaceGroup
from slipsurface.fe2d.model.materials import InterfaceSpec
from slipsurface.fe2d.model.mesh import ElementBlock

_REFERENCE = runpy.run_path(str(Path(__file__).with_name("f7_dilatant_interface_benchmark.py")))[
    "closed_form"
]
ANALYTICAL_TOLERANCE = 1e-9
FINITE_DIFFERENCE_TOLERANCE = 1e-6


def history_cases():
    """Total local jumps (metres), with branches strictly away from switches."""
    phi, psi = math.degrees(math.atan(0.5)), math.degrees(math.atan(0.25))
    shear = [
        (0.0, -0.01, "elastic", 1), (0.002, -0.01, "elastic", 1),
        (0.04, -0.01, "shear", 1), (0.035, -0.01, "elastic", 1),
        (0.02, -0.01, "elastic", 1), (0.0, -0.01, "shear", -1),
        (-0.03, -0.01, "shear", -1), (-0.024, -0.01, "elastic", -1),
        (0.006, -0.01, "shear", 1), (0.04, -0.01, "shear", 1),
    ]
    dilatant = [
        (0.0, -0.01, "elastic", 1), (0.002, -0.01, "elastic", 1),
        (0.04, -0.01, "shear", 1), (0.035, -0.01, "elastic", 1),
        (0.02, -0.01, "elastic", 1), (-0.02, -0.01, "shear", -1),
        (-0.05, -0.01, "shear", -1), (-0.045, -0.01, "elastic", -1),
        (-0.02, -0.01, "elastic", 1), (0.04, -0.01, "shear", 1),
    ]
    opening = [
        (0.0, -0.002, "elastic", 1), (0.0, 0.004, "tension", 1),
        (0.0, 0.006, "tension", 1), (0.0, 0.005, "elastic", 1),
        (0.0, 0.001, "elastic", 1), (0.0, -0.003, "elastic", 1),
        (0.0, 0.002, "elastic", 1), (0.0, 0.009, "tension", 1),
        (0.0, 0.008, "elastic", 1), (0.0, -0.001, "elastic", 1),
    ]
    corner = [
        (0.0, -0.002, "elastic", 1), (0.03, 0.02, "corner", 1),
        (0.028, 0.019, "elastic", 1), (-0.012, 0.019, "shear", -1),
        (0.038, 0.059, "corner", 1), (0.037, 0.063, "tension", 1),
        (0.034, 0.061, "elastic", 1), (-0.016, 0.10, "corner", -1),
    ]
    return [
        {"name": name, "ks": 1000.0, "kn": 2000.0, "cohesion": 5.0,
         "phi": f, "psi": g, "tensile_cap": cap, "steps": steps}
        for name, f, g, cap, steps in (
            ("cyclic_frictional_shear", phi, 0.0, 1.0, shear),
            ("cyclic_dilatant_shear", phi, psi, 1.0, dilatant),
            ("tensile_cap_opening_reversal", 0.0, 0.0, 0.0, opening),
            ("corner_unloading_reversal", phi, psi, 1.0, corner),
        )
    ]


def reference_step(case, total_jump, plastic_jump, branch, sign):
    """Advance an independent inelastic-jump memory, not the native traction state."""
    total = np.asarray(total_jump, dtype=float)
    plastic = np.asarray(plastic_jump, dtype=float)
    if total.shape != (2,) or plastic.shape != (2,):
        raise ValueError("Jump and plastic memory must each have two components")
    if not np.isfinite(total).all() or not np.isfinite(plastic).all():
        raise ValueError("Jump and plastic memory must be finite")
    stiffness = np.array([case["ks"], case["kn"]])
    predicted = _REFERENCE(
        stiffness * (total - plastic), branch=branch, sign=sign,
        **{key: case[key] for key in ("ks", "kn", "cohesion", "phi", "psi", "tensile_cap")},
    )
    return predicted, total - np.asarray(predicted["traction"]) / stiffness


def _check(actual, expected, tolerance=ANALYTICAL_TOLERANCE):
    a, b = np.asarray(actual, dtype=float), np.asarray(expected, dtype=float)
    if a.shape != b.shape or not np.isfinite(a).all() or not np.isfinite(b).all():
        return {"status": "failed", "normalized_error": None,
                "reason": "Invalid dimensions or nonfinite result", "tolerance": tolerance}
    error = float(np.max(np.abs(a - b)))
    ratio = error / max(1.0, float(np.max(np.abs(b))))
    return {"status": "passed" if ratio <= tolerance else "failed",
            "absolute_error": error, "normalized_error": ratio, "tolerance": tolerance}


def _assembly(traction, tangent, rotation, weights):
    """Analytical nodal integration, independent of native weights and matrices."""
    n = len(weights)
    points = weights[:, None] * (rotation @ np.asarray(traction))
    forces = np.vstack([-points, points]).ravel()
    stiffness = np.zeros((4 * n, 4 * n))
    for j, weight in enumerate(weights):
        first = slice(2 * j, 2 * j + 2)
        second = slice(2 * (n + j), 2 * (n + j) + 2)
        value = weight * rotation @ np.asarray(tangent) @ rotation.T
        stiffness[first, first] += value
        stiffness[second, second] += value
        stiffness[first, second] -= value
        stiffness[second, first] -= value
    return forces, stiffness


def run_history(case, *, element_type="IFACE4", angle_deg=0.0, length=4.0):
    """Discard trial evaluations, then commit native updates step by step."""
    if not math.isfinite(length) or length <= 0 or not math.isfinite(angle_deg):
        raise ValueError("Positive length and finite orientation required")
    if element_type not in ("IFACE4", "IFACE6") or not case["steps"]:
        raise ValueError("Nonempty straight IFACE4/IFACE6 history required")
    theta = math.radians(angle_deg)
    rotation = np.array([[math.cos(theta), -math.sin(theta)],
                         [math.sin(theta), math.cos(theta)]])
    stations = np.array([0.0, 1.0] if element_type == "IFACE4" else [0.0, 1.0, 0.5])
    weights = length * np.array([0.5, 0.5] if element_type == "IFACE4"
                                else [1 / 6, 1 / 6, 2 / 3])
    n = len(stations)
    face = length * stations[:, None] * rotation[:, 0]
    block = ElementBlock(ElemType[element_type], np.arange(2 * n)[None],
                         np.array([0]), "joint")
    spec = InterfaceSpec("joint", kn=case["kn"], ks=case["ks"], c=case["cohesion"],
                         phi=case["phi"], psi=case["psi"], sig_t=case["tensile_cap"])
    group = InterfaceGroup(block, np.vstack([face, face]), spec, Analysis.PLANE_STRAIN)
    ids, state = np.array([0]), group.zero_state()
    group.activate(state, ids)
    previous, plastic = np.zeros(2), np.zeros(2)
    results = []
    for index, (ds, dn, branch, sign) in enumerate(case["steps"]):
        total = np.array([ds, dn])
        predicted, plastic_next = reference_step(case, total, plastic, branch, sign)
        du = np.zeros((1, 4 * n))
        du[0, 2 * n:] = np.tile(rotation @ (total - previous), n)
        snapshot = state["t"].copy()
        rejected = du.copy()
        rejected[0, 2 * n:] += np.tile(rotation @ np.array([0.025, -0.003]), n)
        group.integrate(state, ids, rejected, None)  # intentionally NOT committed
        unchanged = bool(np.array_equal(state["t"], snapshot))
        updated, force, tangent, flags = group.integrate(state, ids, du, None)
        repeat = group.integrate(state, ids, du, None)
        finite_difference = np.zeros((4 * n, 4 * n))
        for j in range(4 * n):
            perturb = np.zeros_like(du)
            perturb[0, j] = 1e-7
            plus = group.integrate(state, ids, du + perturb, None)[1][0]
            minus = group.integrate(state, ids, du - perturb, None)[1][0]
            finite_difference[:, j] = (plus - minus) / 2e-7
            unchanged &= bool(np.array_equal(state["t"], snapshot))
        expected_force, expected_tangent = _assembly(
            predicted["traction"], predicted["tangent"], rotation, weights,
        )
        checks = {
            "traction_kpa": _check(updated["t"][0], np.tile(predicted["traction"], (n, 1))),
            "nodal_force_kn_per_m": _check(force[0], expected_force),
            "tangent_kn_per_m2": _check(tangent[0], expected_tangent),
            "finite_difference_kn_per_m2": _check(finite_difference, tangent[0],
                                                  FINITE_DIFFERENCE_TOLERANCE),
            "reciprocity_kn_per_m": _check(force[0].reshape(-1, 2).sum(axis=0), np.zeros(2)),
            "retry_traction_kpa": _check(repeat[0]["t"], updated["t"]),
        }
        flags_match = flags.shape == (1, n) and bool(np.all(flags == predicted["flag"]))
        passed = unchanged and flags_match and all(v["status"] == "passed"
                                                   for v in checks.values())
        results.append({
            "step": index, "total_jump_m": total.tolist(), "branch": branch,
            "reference": predicted, "reference_plastic_jump_m": plastic_next.tolist(),
            "observed_traction_kpa": (updated["t"][0].tolist()
                                     if np.isfinite(updated["t"]).all() else None),
            "observed_flags": flags[0].tolist(), "flags_match": flags_match,
            "uncommitted_trials_leave_state_unchanged": unchanged,
            "checks": checks, "status": "passed" if passed else "failed",
        })
        state["t"][ids] = updated["t"]  # commit only the selected increment
        previous, plastic = total, plastic_next  # independent reference state
    return {"name": case["name"], "element_type": element_type, "angle_deg": angle_deg,
            "length_m": length, "normal_stiffness_kpa_per_m": case["kn"],
            "step_count": len(results), "results": results,
            "status": "passed" if all(r["status"] == "passed" for r in results) else "failed"}


def contact_gap_comparison(history):
    """Separate diagnostic: zero-reference-gap, unbonded normal penalty contact."""
    if history.get("name") != "tensile_cap_opening_reversal":
        raise ValueError("Gap comparison is only defined for the zero-tension normal history")
    points = []
    for row in history["results"]:
        gap = row["total_jump_m"][1]
        contact = min(history["normal_stiffness_kpa_per_m"] * gap, 0.0)
        observed = np.asarray(row["observed_traction_kpa"], dtype=float)
        valid = observed.ndim == 2 and observed.shape[1] == 2 and len(observed) > 0
        normals = observed[:, 1] if valid else np.array([np.nan])
        valid = valid and bool(np.isfinite(normals).all())
        difference = float(np.max(np.abs(normals - contact))) if valid else None
        points.append({"step": row["step"], "geometric_gap_m": gap,
                       "unbonded_contact_normal_kpa": contact,
                       "native_normal_kpa": normals.tolist() if valid else None,
                       "maximum_difference_kpa": difference})
    known = bool(points) and all(x["maximum_difference_kpa"] is not None for x in points)
    mismatch = known and any(x["maximum_difference_kpa"] > 1e-9 for x in points)
    return {"status": "incomplete" if not known else
            "not_equivalent" if mismatch else "equivalent_at_sampled_points", "points": points,
            "warning": "A tensile-capped elastoplastic spring is not a unilateral contact-gap law. "
                       "This diagnostic is not a passed physical opening/closure validation."}


def run_benchmark():
    runs = []
    for case in history_cases():
        for element in ("IFACE4", "IFACE6"):
            for angle in (0.0, 37.0, -63.0):
                try:
                    runs.append(run_history(case, element_type=element, angle_deg=angle))
                except (ValueError, KeyError, IndexError, FloatingPointError) as exc:
                    runs.append({"name": case["name"], "element_type": element,
                                 "angle_deg": angle, "status": "failed", "step_count": 0,
                                 "error": f"{type(exc).__name__}: {exc}"})
    gap_case = next((r for r in runs if r["name"] == "tensile_cap_opening_reversal"
                     and r["element_type"] == "IFACE4" and r["angle_deg"] == 0.0
                     and "results" in r), None)
    gap = contact_gap_comparison(gap_case) if gap_case else {"status": "incomplete"}
    return {
        "status": "passed" if all(r["status"] == "passed" for r in runs) else "failed",
        "history_count": len(runs), "committed_step_count": sum(r["step_count"] for r in runs),
        "runs": runs, "unilateral_contact_gap_comparison": gap,
        "physical_validation": "not_established",
        "scope": "Selected dry straight-interface constitutive histories and trial/commit "
                 "semantics only; no unilateral contact, fatigue, hydraulic or "
                 "excavation validation.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-unilateral-contact", action="store_true",
                        help="Additionally require equivalence to the independent gap comparator")
    args = parser.parse_args()
    report = run_benchmark()
    contact_ok = (report["unilateral_contact_gap_comparison"]["status"]
                  == "equivalent_at_sampled_points")
    report["unilateral_contact_required"] = args.require_unilateral_contact
    report["requested_contract_passed"] = (
        report["status"] == "passed" and (contact_ok or not args.require_unilateral_contact)
    )
    payload = json.dumps(report, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload)
    return 0 if report["requested_contract_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Verify the new standalone normal-contact kernel, not the legacy Goodman law.

Prescribed opening/reversal/reclosure paths and a force-controlled rigid-face
spring/contact system use independently derived gap, traction, force and tangent
references. Neither fixture is the application's coupled excavation solver.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.fem.unilateral_contact import UnilateralNormalContactGroup
from slipsurface.fe2d.model.mesh import ElementBlock

TOLERANCE = 1e-9
FD_TOLERANCE = 1e-6


def fixture(element_type="IFACE4", angle_deg=0.0, *, initial_gap=0.0, kn=2000.0):
    if element_type not in ("IFACE4", "IFACE6") or not math.isfinite(angle_deg):
        raise ValueError("Invalid contact fixture")
    theta = math.radians(angle_deg)
    direction = np.array([math.cos(theta), math.sin(theta)])
    normal = np.array([-direction[1], direction[0]])
    stations = np.array([0.0, 1.0] if element_type == "IFACE4" else [0.0, 1.0, 0.5])
    face = 4.0 * stations[:, None] * direction + [1.0, -2.0]
    npe = len(stations)
    block = ElementBlock(ElemType[element_type], np.arange(2*npe)[None, :],
                         np.array([0]), "contact")
    group = UnilateralNormalContactGroup(
        block, np.vstack([face, face]), kn=kn, initial_gap=initial_gap,
    )
    # Analytic straight-face integrals; do not use group.weights/B/normal.
    weights = 4.0 * np.array([0.5, 0.5] if npe == 2 else [1/6, 1/6, 2/3])
    return group, direction, normal, weights


def error(actual, expected, tolerance=TOLERANCE):
    a, b = np.asarray(actual, dtype=float), np.asarray(expected, dtype=float)
    if a.shape != b.shape or not np.isfinite(a).all() or not np.isfinite(b).all():
        return {"status": "failed", "normalized_error": None,
                "reason": "Invalid shape or nonfinite result"}
    difference = float(np.max(np.abs(a - b)))
    ratio = difference / max(1.0, float(np.max(np.abs(b))))
    return {"status": "passed" if ratio <= tolerance else "failed",
            "absolute_error": difference, "normalized_error": ratio,
            "tolerance": tolerance}


def force_and_tangent(gaps, normal, weights, kn):
    """Closed-form independent traction integration at the paired stations."""
    n = len(weights)
    values = np.array([kn*g if g < 0.0 else 0.0 for g in gaps])
    point = (weights * values)[:, None] * normal
    force = np.vstack([-point, point]).ravel()
    matrix = np.zeros((4*n, 4*n))
    for j, g in enumerate(gaps):
        if g <= 0.0:
            pair = (slice(2*j, 2*j+2), slice(2*(n+j), 2*(n+j)+2))
            block = weights[j] * kn * np.outer(normal, normal)
            for a in range(2):
                for b in range(2):
                    matrix[pair[a], pair[b]] += block * (1 if a == b else -1)
    energy = sum(0.5 * w * kn * min(g, 0.0)**2 for w, g in zip(weights, gaps))
    return force, matrix, energy


def run_history(element_type="IFACE4", angle_deg=0.0, initial_gap=0.0):
    group, direction, normal, weights = fixture(
        element_type, angle_deg, initial_gap=initial_gap,
    )
    kn, npe = 2000.0, len(weights)
    # Total signed gaps, not stress-driven increments. No switching point in FD cases.
    targets = (0.006, 0.005, 0.002, -0.001, -0.003, -0.0005, 0.004, 0.001, -0.002)
    state, ids = group.zero_state(), np.array([0])
    previous = np.zeros((1, 4*npe))
    records = []
    for i, target in enumerate(targets):
        total = np.zeros_like(previous)
        # Tangential displacement is physically free and must never produce shear.
        total[0, 2*npe:] = np.tile((target-initial_gap)*normal + 0.0002*i*direction, npe)
        delta = total - previous
        snapshot = state["gap"].copy()
        # A discarded very compressive trial must not leave residual memory.
        discarded = delta.copy()
        discarded[0, 2*npe:] -= np.tile(0.05*normal, npe)
        group.integrate(state, ids, discarded)
        updated, force, tangent, status = group.integrate(state, ids, delta)
        repeated = group.integrate(state, ids, delta)
        expected_gap = np.full((1, npe), target)
        ref_force, ref_tangent, ref_energy = force_and_tangent(
            expected_gap[0], normal, weights, kn,
        )
        derivative = np.empty((4*npe, 4*npe))
        for dof in range(4*npe):
            shift = np.zeros_like(delta)
            shift[0, dof] = 1e-7
            plus = group.integrate(state, ids, delta + shift)[1][0]
            minus = group.integrate(state, ids, delta - shift)[1][0]
            derivative[:, dof] = (plus - minus) / 2e-7
        checks = {
            "gap_m": error(updated["gap"], expected_gap),
            "nodal_force_kn_per_m": error(force[0], ref_force),
            "tangent_kpa": error(tangent[0], ref_tangent),
            "finite_difference_kpa": error(derivative, tangent[0], FD_TOLERANCE),
            "energy_knm_per_m": error(group.stored_energy(updated), np.array([ref_energy])),
            "reciprocity_kn_per_m": error(force[0].reshape(-1, 2).sum(axis=0), np.zeros(2)),
            "repeat_gap": error(repeated[0]["gap"], updated["gap"]),
            "repeat_force": error(repeated[1], force),
            "repeat_tangent": error(repeated[2], tangent),
        }
        status_matches = bool(np.all(status == (0 if target > 0 else 2)))
        immutable = bool(np.array_equal(state["gap"], snapshot))
        passed = immutable and status_matches and all(c["status"] == "passed"
                                                      for c in checks.values())
        records.append({"step": i+1, "total_gap_m": target,
                        "status": "passed" if passed else "failed", "checks": checks,
                        "contact_status_matches": status_matches,
                        "committed_state_unchanged": immutable})
        if not passed:
            break
        state["gap"][ids] = updated["gap"]  # Only explicitly accepted values are committed.
        previous = total
    return {"status": "passed" if len(records) == len(targets)
            and all(r["status"] == "passed" for r in records) else "failed",
            "element_type": element_type, "angle_deg": angle_deg, "initial_gap_m": initial_gap,
            "step_count": len(records), "steps": records}


def run_force_controlled(element_type="IFACE4", angle_deg=0.0, initial_gap=0.002):
    """Rigid moving face with a parallel spring; stable even while contact is open.

    Solve k_s*u + L*kn*min(g0+u, 0) = P with the actual assembled normal
    force and tangent. Reference is the closed-form two-branch equilibrium.
    This small reduced assembly is not StaticSolver/api.run.
    """
    group, _, normal, weights = fixture(element_type, angle_deg, initial_gap=initial_gap)
    n, kn, length, support_k = len(weights), 2000.0, 4.0, 1000.0
    state, ids = group.zero_state(), np.array([0])
    selector = np.zeros(4*n)
    selector[2*n:] = np.tile(normal, n)
    committed_u = 0.0
    rows = []
    for load in (6.0, 5.0, -1.0, -3.0, -20.0, 4.0, -5.0):
        expected = (load/support_k if load >= -support_k*initial_gap else
                    (load - kn*length*initial_gap)/(support_k + kn*length))
        u, converged = committed_u, False
        snapshot = state["gap"].copy()
        for iteration in range(12):
            trial, forces, tangent, _ = group.integrate(
                state, ids, ((u-committed_u)*selector)[None, :],
            )
            residual = support_k*u + float(selector @ forces[0]) - load
            if abs(residual) <= 1e-11 * max(1.0, abs(load)):
                converged = True
                break
            jacobian = support_k + float(selector @ tangent[0] @ selector)
            u -= residual/jacobian
        checks = {
            "displacement_m": error(np.array([u]), np.array([expected])),
            "equilibrium_kn_per_m": error(np.array([residual]), np.array([0.0])),
            "gap_m": error(trial["gap"], np.full((1, n), initial_gap+expected)),
        }
        immutable = bool(np.array_equal(snapshot, state["gap"]))
        passed = converged and immutable and all(c["status"] == "passed" for c in checks.values())
        rows.append({"status": "passed" if passed else "failed", "load_kn_per_m": load,
                     "analytical_displacement_m": expected, "observed_displacement_m": u,
                     "iterations": iteration+1, "checks": checks,
                     "committed_state_unchanged": immutable})
        if not passed:
            break
        state["gap"][ids] = trial["gap"]
        committed_u = u
    return {"status": "passed" if len(rows) == 7 and all(r["status"] == "passed" for r in rows)
            else "failed", "element_type": element_type, "angle_deg": angle_deg,
            "initial_gap_m": initial_gap, "steps": rows}


def run_benchmark():
    runs = [run_history(etype, angle, gap)
            for etype in ("IFACE4", "IFACE6") for angle in (0.0, 37.0, -63.0)
            for gap in (0.0, 0.002)]
    assemblies = [run_force_controlled(etype, angle, gap)
                  for etype in ("IFACE4", "IFACE6") for angle in (0.0, 37.0, -63.0)
                  for gap in (0.0, 0.002)]
    return {
        "status": "passed" if all(r["status"] == "passed" for r in runs+assemblies)
        else "failed", "history_count": len(runs),
        "history_step_count": sum(r["step_count"] for r in runs),
        "force_controlled_count": len(assemblies),
        "force_controlled_step_count": sum(len(r["steps"]) for r in assemblies),
        "histories": runs, "force_controlled": assemblies,
        "scope": "Standalone normal-only penalty contact and reduced spring/contact assembly. "
                 "Not registered in the general model/GUI; legacy Goodman law is unchanged. "
                 "No friction, hydraulics, moving normals, hard-contact or excavation validation.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_benchmark()
    payload = json.dumps(report, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

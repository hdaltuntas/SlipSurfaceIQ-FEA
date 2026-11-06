"""Analytical displacement-controlled BAR2 axial force benchmark."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from slipsurface.fe2d.core.enums import Analysis, ElemType
from slipsurface.fe2d.fem.structural import BarGroup
from slipsurface.fe2d.model.materials import BoltSpec
from slipsurface.fe2d.model.mesh import ElementBlock


def analytical_force(length, spec, displacement):
    """Elastic trial force clamped to the tensile/compressive yield force."""
    if not math.isfinite(length) or length <= 0 or not math.isfinite(displacement):
        raise ValueError("Length/displacement must be finite; length positive")
    trial = (spec.pretension / spec.spacing_out_of_plane
             + spec.EA * displacement / (spec.spacing_out_of_plane * length))
    cap = spec.T_yield / spec.spacing_out_of_plane
    return max(-cap, min(cap, trial))


def run_benchmark(*, length=5.0, ea=100_000.0, yield_force=120.0,
                  spacing=2.0, pretension=40.0,
                  displacements=(-0.01, 0.0, 0.001, 0.005, 0.03)):
    """Compare actual BarGroup update and end forces with independent formula."""
    spec = BoltSpec("anchor", EA=ea, T_yield=yield_force,
                    pretension=pretension, spacing_out_of_plane=spacing)
    if not displacements:
        raise ValueError("At least one displacement is required")
    block = ElementBlock(ElemType.BAR2, np.array([[0, 1]], dtype=int),
                         np.array([0], dtype=int), "anchor")
    group = BarGroup(block, np.array([[0.0, 0.0], [length, 0.0]]),
                     spec, Analysis.PLANE_STRAIN)
    ids = np.array([0], dtype=int)
    rows = []
    for delta in displacements:
        if not math.isfinite(delta):
            raise ValueError("Displacement must be finite")
        state = group.zero_state()
        group.activate(state, ids)
        increment = np.array([[0.0, 0.0, delta, 0.0]])
        updated, forces, tangent, yielded = group.integrate(
            state, ids, increment, None
        )
        reference = analytical_force(length, spec, delta)
        observed = float(updated["N"][0])
        ends = forces[0]
        cap = spec.T_yield / spacing
        trial = spec.pretension / spacing + spec.EA * delta / (spacing * length)
        expected_yield = abs(trial) > cap
        error = max(abs(observed - reference),
                    abs(float(ends[0]) + reference),
                    abs(float(ends[2]) - reference),
                    abs(float(ends[1])), abs(float(ends[3])))
        rows.append({
            "displacement_m": delta,
            "analytical_force_kn_per_m": reference,
            "observed_force_kn_per_m": observed,
            "root_reaction_kn_per_m": float(ends[0]),
            "end_internal_force_kn_per_m": float(ends[2]),
            "expected_yielded": expected_yield,
            "observed_yielded": bool(yielded[0, 0]),
            "observed_axial_tangent": float(tangent[0, 2, 2]),
            "absolute_force_error": error,
            "relative_force_error": error / max(abs(reference), cap, 1.0),
        })
    return {
        "case": "isolated_displacement_controlled_bar2",
        "observations": rows,
        "maximum_relative_error": max(row["relative_force_error"] for row in rows),
        "yield_flags_match": all(row["expected_yielded"] == row["observed_yielded"]
                                 for row in rows),
        "warning": (
            "Checks isolated axial element law, prestress and end forces only; "
            "does not validate soil, interface or complete excavation coupling."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_benchmark()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["yield_flags_match"] and report["maximum_relative_error"] <= 1e-9 else 1


if __name__ == "__main__":
    raise SystemExit(main())

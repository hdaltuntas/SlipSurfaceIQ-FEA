"""Independent closed-form cantilever benchmark for the F7 structural beam.

A horizontal, clamped, two-node elastic Timoshenko beam is loaded at its
free tip with axial N and transverse V. Compare its direct FEM stiffness
solution with independent closed-form kinematics and root reactions.
This isolates beam mechanics; no soil, interfaces or staged excavation.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from slipsurface.fe2d.core.enums import Analysis, ElemType
from slipsurface.fe2d.fem.structural import BeamGroup
from slipsurface.fe2d.model.materials import LinerSpec
from slipsurface.fe2d.model.mesh import ElementBlock


def cantilever_reference(length, spec, axial, transverse):
    """Analytical Timoshenko cantilever tip response and clamp reactions."""
    if not math.isfinite(length) or length <= 0:
        raise ValueError("Length must be finite and positive")
    if not all(math.isfinite(x) for x in (axial, transverse)):
        raise ValueError("Forces must be finite")
    ep = spec.E / (1.0 - spec.nu**2)
    ea = ep * spec.A
    ei = ep * spec.I
    ga = spec.E / (2.0 * (1.0 + spec.nu)) * spec.As
    displacement = transverse * length**3 / (3.0 * ei)
    if ga > 0:
        displacement += transverse * length / ga
    return {
        "tip_ux_m": axial * length / ea,
        "tip_uy_m": displacement,
        "tip_rotation_rad": transverse * length**2 / (2.0 * ei),
        "root_rx_kn_per_m": -axial,
        "root_ry_kn_per_m": -transverse,
        "root_moment_knm_per_m": -transverse * length,
    }


def run_benchmark(
    *, length=6.0, young=30_000_000.0, nu=0.2,
    area=0.30, inertia=0.00225, shear_area=0.25,
    axial=20.0, transverse=-35.0,
):
    """Solve beam's free 3 DOFs and compare all six analytical observables."""
    spec = LinerSpec(
        "cantilever", E=young, nu=nu, A=area, I=inertia,
        As=shear_area, unit_weight=0.0,
    )
    mesh_coords = np.array([[0.0, 0.0], [length, 0.0]], dtype=float)
    block = ElementBlock(
        ElemType.BEAM2, np.array([[0, 1]], dtype=int),
        np.array([0], dtype=int), "cantilever",
    )
    group = BeamGroup(block, mesh_coords, spec, Analysis.PLANE_STRAIN)
    stiffness = group.elastic_K(np.array([0], dtype=int))[0]
    loads = np.array([axial, transverse, 0.0], dtype=float)
    full = np.zeros(6)
    full[3:] = np.linalg.solve(stiffness[3:, 3:], loads)
    reactions = stiffness[:3, :] @ full
    observed = dict(zip(
        ("tip_ux_m", "tip_uy_m", "tip_rotation_rad",
         "root_rx_kn_per_m", "root_ry_kn_per_m", "root_moment_knm_per_m"),
        (float(full[3]), float(full[4]), float(full[5]),
         float(reactions[0]), float(reactions[1]), float(reactions[2])),
    ))
    reference = cantilever_reference(length, spec, axial, transverse)
    diagnostics = {}
    for key, expected in reference.items():
        actual = observed[key]
        absolute = abs(actual - expected)
        relative = absolute / max(abs(expected), 1e-12)
        diagnostics[key] = {
            "observed": actual, "analytical": expected,
            "absolute_error": absolute, "relative_error": relative,
        }
    return {
        "case": "standalone_linear_timoshenko_cantilever",
        "length_m": length,
        "load_axial_kn_per_m": axial,
        "load_transverse_kn_per_m": transverse,
        "element_count": 1,
        "checks": diagnostics,
        "maximum_relative_error": max(
            item["relative_error"] for item in diagnostics.values()
        ),
        "scope": (
            "Independent closed-form elastic single-beam reference only. "
            "Does not validate soil response, pile interface traction, "
            "anchor interaction or excavation sequencing."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_benchmark()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["maximum_relative_error"] <= 1e-9 else 1


if __name__ == "__main__":
    raise SystemExit(main())

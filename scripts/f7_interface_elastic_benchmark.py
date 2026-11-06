"""Independent uniform-jump interface spring and force-transfer benchmark.

For a straight IFACE4 of length L with a constant tangential/normal jump,
analytical traction is (ks*ds, kn*dn). Each face receives the opposite
integrated resultant (+/- L*traction); each endpoint receives half.
This isolates elastic interface mechanics from the coupled excavation solver.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from slipsurface.fe2d.core.enums import Analysis, ElemType
from slipsurface.fe2d.fem.structural import InterfaceGroup
from slipsurface.fe2d.model.materials import InterfaceSpec
from slipsurface.fe2d.model.mesh import ElementBlock


def analytical_uniform_jump(length, ks, kn, tangential_jump, normal_jump):
    """Closed-form interface tractions and per-endpoint action/reaction."""
    if not all(math.isfinite(x) for x in (
        length, ks, kn, tangential_jump, normal_jump
    )) or length <= 0 or ks < 0 or kn <= 0:
        raise ValueError("Invalid length, stiffness or displacement jump")
    traction = np.array([ks * tangential_jump, kn * normal_jump])
    half = length * traction / 2.0
    return traction, np.array([-half, -half, half, half])


def run_benchmark(*, length=4.0, ks=1_000.0, kn=2_000.0,
                  tangential_jump=0.002, normal_jump=-0.001):
    """Exercise the actual IFACE4 integration and compare against closed form."""
    expected_traction, expected_forces = analytical_uniform_jump(
        length, ks, kn, tangential_jump, normal_jump
    )
    coords = np.array([
        [0.0, 0.0], [length, 0.0],
        [0.0, 0.0], [length, 0.0],
    ])
    block = ElementBlock(
        ElemType.IFACE4, np.array([[0, 1, 2, 3]], dtype=int),
        np.array([0], dtype=int), "skin",
    )
    spec = InterfaceSpec("elastic-skin", kn=kn, ks=ks, c=1_000_000.0,
                         phi=0.0, psi=0.0, sig_t=1_000_000.0)
    group = InterfaceGroup(block, coords, spec, Analysis.PLANE_STRAIN)
    ids = np.array([0], dtype=int)
    displacement = np.array([[
        0.0, 0.0, 0.0, 0.0,
        tangential_jump, normal_jump, tangential_jump, normal_jump,
    ]])
    state = group.zero_state()
    group.activate(state, ids)
    updated, nodal, tangent, flags = group.integrate(state, ids, displacement, None)
    actual_traction = updated["t"][0]
    actual_forces = nodal[0].reshape(4, 2)
    expected = expected_forces
    force_error = float(np.max(np.abs(actual_forces - expected)))
    traction_error = float(np.max(np.abs(actual_traction - expected_traction)))
    face1 = actual_forces[:2].sum(axis=0)
    face2 = actual_forces[2:].sum(axis=0)
    reciprocity_error = float(np.max(np.abs(face1 + face2)))
    stiffness_error = float(np.max(np.abs(
        tangent[0] @ displacement[0] - nodal[0]
    )))
    scale = max(float(np.max(np.abs(expected))), 1.0)
    result = {
        "case": "isolated_elastic_IFACE4_uniform_jump",
        "length_m": length,
        "analytical_local_traction": expected_traction.tolist(),
        "observed_local_traction": actual_traction.tolist(),
        "analytical_nodal_forces": expected.tolist(),
        "observed_nodal_forces": actual_forces.tolist(),
        "maximum_traction_error": traction_error,
        "maximum_force_error": force_error,
        "face_reciprocity_error": reciprocity_error,
        "elastic_tangent_residual": stiffness_error,
        "plastic_flags": flags[0].tolist(),
        "maximum_normalized_error": max(
            traction_error, force_error, reciprocity_error, stiffness_error
        ) / scale,
        "scope": (
            "Linear elastic uniform interface jump and reciprocal nodal forces "
            "only; does not validate nonlinear slip/gap, groundwater, "
            "coupled soil-pile behaviour or staged excavation."
        ),
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_benchmark()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if (
        result["maximum_normalized_error"] <= 1e-9
        and not any(result["plastic_flags"])
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Closed-form frictionless IFACE4 slip and tensile cap benchmark.

For phi=psi=0, the independent Goodman law is separable:
tau=clip(ks*ds,-c,c), sigma=min(kn*dn,sig_t).
These uniform-jump benchmarks include shear yield, gap/tensile cut-off,
and simultaneous activation. They do not verify frictional/dilatant slip.
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


def reference(ks, kn, cohesion, tensile_cap, ds, dn):
    """Independent scalar projection onto the frictionless admissible box."""
    values = (ks, kn, cohesion, tensile_cap, ds, dn)
    if not all(math.isfinite(x) for x in values) or ks <= 0 or kn <= 0:
        raise ValueError("Properties and jumps must be finite; stiffness positive")
    if cohesion < 0 or tensile_cap < 0:
        raise ValueError("Strength and tensile cap cannot be negative")
    trial_s, trial_n = ks * ds, kn * dn
    shear_yield = abs(trial_s) > cohesion
    tensile_yield = trial_n > tensile_cap
    tau = max(-cohesion, min(cohesion, trial_s))
    normal = min(tensile_cap, trial_n)
    flag = (
        PlasticFlag.TENSION if tensile_yield else
        PlasticFlag.SHEAR if shear_yield else PlasticFlag.ELASTIC
    )
    return {
        "traction": (tau, normal),
        "tangent": (0.0 if shear_yield else ks,
                    0.0 if tensile_yield else kn),
        "flag": int(flag),
    }


def run_benchmark(*, length=4.0, ks=1000.0, kn=2000.0,
                  cohesion=5.0, tensile_cap=1.0):
    """Integrate actual IFACE4 under constant jump and compare 2-face forces."""
    cases = (
        ("elastic", 0.002, -0.002),
        ("positive_shear_yield", 0.012, -0.002),
        ("negative_shear_yield", -0.012, -0.002),
        ("opening_tensile_cap", 0.0, 0.002),
        ("simultaneous_shear_opening", 0.012, 0.002),
        ("compression_after_opening_reference", 0.0, -0.004),
    )
    if not math.isfinite(length) or length <= 0:
        raise ValueError("Invalid interface length")
    nodes = np.array([
        [0.0, 0.0], [length, 0.0],
        [0.0, 0.0], [length, 0.0],
    ])
    block = ElementBlock(
        ElemType.IFACE4, np.array([[0, 1, 2, 3]], dtype=int),
        np.array([0], dtype=int), "joint",
    )
    spec = InterfaceSpec("joint", kn=kn, ks=ks, c=cohesion,
                         phi=0.0, psi=0.0, sig_t=tensile_cap)
    group = InterfaceGroup(block, nodes, spec, Analysis.PLANE_STRAIN)
    ids = np.array([0], dtype=int)
    rows = []
    for label, ds, dn in cases:
        state = group.zero_state()
        group.activate(state, ids)
        u = np.array([[0.0, 0.0, 0.0, 0.0, ds, dn, ds, dn]])
        updated, nodal, tangent, flags = group.integrate(state, ids, u, None)
        analytical = reference(ks, kn, cohesion, tensile_cap, ds, dn)
        traction = np.array(analytical["traction"])
        expected_forces = np.array([-traction, -traction, traction, traction])
        observed_forces = nodal[0].reshape(4, 2)
        force_error = float(np.max(np.abs(observed_forces
                                          - expected_forces * length / 2)))
        traction_error = float(np.max(np.abs(updated["t"][0] - traction)))
        reciprocity_error = float(np.max(np.abs(observed_forces.sum(axis=0))))
        # Use independent analytic diagonal tangent in the local frame.
        # Constant jump: face-2 endpoint x/y tangent block is L/2*D.
        numerical_tangent = tangent[0][4:6, 4:6]
        target_tangent = np.diag(analytical["tangent"]) * length / 2
        tangent_error = float(np.max(np.abs(numerical_tangent - target_tangent)))
        flags_match = all(int(x) == analytical["flag"] for x in flags[0])
        scale = max(1.0, float(np.max(np.abs(expected_forces * length / 2))),
                    float(np.max(np.abs(target_tangent))))
        rows.append({
            "case": label, "jump": [ds, dn],
            "analytical_traction": list(analytical["traction"]),
            "observed_traction": updated["t"][0].tolist(),
            "analytical_flag": analytical["flag"],
            "observed_flags": [int(x) for x in flags[0]],
            "flags_match": flags_match,
            "maximum_traction_error": traction_error,
            "maximum_nodal_force_error": force_error,
            "force_reciprocity_error": reciprocity_error,
            "tangent_error": tangent_error,
            "relative_error": max(traction_error, force_error,
                                  reciprocity_error, tangent_error) / scale,
        })
    return {
        "case": "independent_frictionless_Goodman_IFACE4_return",
        "results": rows,
        "all_flags_match": all(r["flags_match"] for r in rows),
        "maximum_relative_error": max(r["relative_error"] for r in rows),
        "scope": (
            "Closed-form separable zero-friction, zero-dilatancy interface "
            "shear yielding and tensile cap. Does not certify frictional "
            "Mohr-Coulomb return, coupled soil or excavation behaviour."
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
    return 0 if result["all_flags_match"] and result["maximum_relative_error"] <= 1e-9 else 1


if __name__ == "__main__":
    raise SystemExit(main())

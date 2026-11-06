"""Independent drained, nondilatant Mohr-Coulomb interface shear reference.

A uniform compressive normal displacement establishes sigma_n = kn*dn < 0.
For psi=0 and fixed normal displacement, the exact single-plane solution is
tau = clip(ks*ds, -(c-sigma_n*tan(phi)), +(c-sigma_n*tan(phi))).
The post-yield local consistent tangent follows by differentiating that
closed form: d tau / d dn = -sign(tau)*tan(phi)*kn.
No general return-map function is used to derive this reference.
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


def analytical_direct_shear(ks, kn, cohesion, friction_deg, ds, dn):
    """Frictional shear envelope at prescribed compressive normal displacement."""
    inputs = (ks, kn, cohesion, friction_deg, ds, dn)
    if (not all(math.isfinite(value) for value in inputs)
            or ks <= 0 or kn <= 0 or cohesion < 0
            or not 0 <= friction_deg < 90 or dn >= 0):
        raise ValueError("Need finite strengths, positive stiffness and compression")
    tf = math.tan(math.radians(friction_deg))
    normal = kn * dn
    cap = cohesion - normal * tf
    trial = ks * ds
    yielded = abs(trial) > cap
    shear = max(-cap, min(cap, trial))
    if yielded:
        direction = 1.0 if trial > 0 else -1.0
        tangent = [[0.0, -direction * tf * kn], [0.0, kn]]
    else:
        tangent = [[ks, 0.0], [0.0, kn]]
    return {
        "traction": [shear, normal],
        "tangent": tangent,
        "yielded": yielded,
        "flag": int(PlasticFlag.SHEAR if yielded else PlasticFlag.ELASTIC),
        "shear_strength": cap,
    }


def run_benchmark(*, length=4.0, ks=1000.0, kn=2000.0,
                  cohesion=5.0, friction_deg=30.0,
                  compressive_jump=-0.01):
    """Verify native IFACE4 shear, normal reaction and nonassociated tangent."""
    if not math.isfinite(length) or length <= 0:
        raise ValueError("Interface length must be positive and finite")
    cases = (
        ("elastic", 0.002),
        ("positive_shear", 0.04),
        ("negative_shear", -0.04),
    )
    coordinates = np.array([
        [0.0, 0.0], [length, 0.0], [0.0, 0.0], [length, 0.0]
    ])
    block = ElementBlock(
        ElemType.IFACE4, np.array([[0, 1, 2, 3]], dtype=int),
        np.array([0], dtype=int), "joint",
    )
    spec = InterfaceSpec(
        "joint", kn=kn, ks=ks, c=cohesion,
        phi=friction_deg, psi=0.0, sig_t=0.0,
    )
    group = InterfaceGroup(block, coordinates, spec, Analysis.PLANE_STRAIN)
    ids = np.array([0], dtype=int)
    results = []
    for label, ds in cases:
        predicted = analytical_direct_shear(
            ks, kn, cohesion, friction_deg, ds, compressive_jump
        )
        displacement = np.array([[
            0.0, 0.0, 0.0, 0.0,
            ds, compressive_jump, ds, compressive_jump,
        ]])
        state = group.zero_state()
        group.activate(state, ids)
        updated, forces, tangent, flags = group.integrate(
            state, ids, displacement, None
        )
        tractions = updated["t"][0]
        expected_traction = np.array(predicted["traction"])
        expected_force = np.array([
            -expected_traction, -expected_traction,
            expected_traction, expected_traction,
        ]) * (length / 2.0)
        observed_force = forces[0].reshape(4, 2)
        # At an endpoint on face 2, the local 2x2 tangent receives L/2 times
        # the local constitutive derivative (Newton-Cotes IFACE4).
        expected_tangent = length / 2.0 * np.array(predicted["tangent"])
        observed_tangent = tangent[0, 4:6, 4:6]
        errors = {
            "traction": float(np.max(np.abs(tractions - expected_traction))),
            "nodal_force": float(np.max(np.abs(observed_force - expected_force))),
            "reciprocity": float(np.max(np.abs(observed_force.sum(axis=0)))),
            "consistent_tangent": float(np.max(
                np.abs(observed_tangent - expected_tangent)
            )),
        }
        force_scale = max(1.0, float(np.max(np.abs(expected_force))))
        tangent_scale = max(1.0, float(np.max(np.abs(expected_tangent))))
        relative = max(
            errors["traction"] / max(1.0, float(np.max(np.abs(expected_traction)))),
            errors["nodal_force"] / force_scale,
            errors["reciprocity"] / force_scale,
            errors["consistent_tangent"] / tangent_scale,
        )
        results.append({
            "case": label, "shear_jump_m": ds,
            "normal_jump_m": compressive_jump,
            "analytical": predicted,
            "observed_traction": tractions.tolist(),
            "observed_flags": [int(flag) for flag in flags[0]],
            "flag_matches": all(int(flag) == predicted["flag"] for flag in flags[0]),
            "errors": errors,
            "maximum_normalized_error": relative,
        })
    return {
        "case": "independent_compressive_nondilatant_direct_shear_IFACE4",
        "results": results,
        "all_flags_match": all(x["flag_matches"] for x in results),
        "maximum_normalized_error": max(x["maximum_normalized_error"] for x in results),
        "warning": (
            "Independent prescribed-compression, zero-dilatancy single-shear-plane "
            "benchmark; not an independent validation of dilatant multisurface "
            "return, pore pressure or coupled staged excavation."
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
    return 0 if (report["all_flags_match"]
                 and report["maximum_normalized_error"] <= 1e-9) else 1


if __name__ == "__main__":
    raise SystemExit(main())

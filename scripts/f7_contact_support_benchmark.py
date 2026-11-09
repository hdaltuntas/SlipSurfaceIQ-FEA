"""Native staged temporary-restraint release, independently checked with two layers.

Uniform cases solve scalar equations, not a matrix extracted from the native FE
implementation. Eccentric partial-face restraints check equilibrium only, not a
closed-form contact patch. Every call uses api.run / StaticSolver.
"""

from __future__ import annotations

import argparse
import json
import runpy
from dataclasses import replace
from pathlib import Path

import numpy as np

from slipsurface.fe2d import api
from slipsurface.fe2d.post.contact_support_equilibrium import contact_support_equilibrium_by_stage

_BASE = runpy.run_path(str(Path(__file__).with_name("f7_contact_activation_benchmark.py")))
WIDTH, K, KN = (_BASE[key] for key in ("WIDTH", "K", "KN"))
FRACTIONS = (1.0, 0.25, 0.5, 1.0, 0.6, 0.5, 1.0, 0.35, 1.0)
CLAMPED = (True, False, False, False, True, False, False, True, False)
CLAMP_TARGETS = (-0.006, 0.0, 0.0, 0.0, 0.006, 0.0, 0.0, -0.008, 0.0)
VARIANTS = ("support_only", "support_and_contact", "eccentric_support")


def build_model(*, element_type="IFACE4", initial_gap=0.0, quarter_turn=False,
                variant="support_only"):
    if variant not in VARIANTS:
        raise ValueError("Unknown temporary-support fixture variant")
    model, fixture = _BASE["build_model"](
        element_type=element_type, initial_gap=initial_gap, quarter_turn=quarter_turn,
        mode="mixed", eccentric=variant == "eccentric_support",
    )
    temporary = model.mesh.nodes("upper_contact")
    if variant == "eccentric_support":
        temporary = temporary[:1]  # partial-face clamp: not a uniform solution
    model.mesh.node_sets["temporary"] = temporary.copy()
    active = tuple(True if variant == "support_only" else value for value in _BASE["ACTIVE"])
    stages = []
    for i, previous in enumerate(model.stages):
        displacement = (api.Displacement("temporary", ux=-CLAMP_TARGETS[i]) if quarter_turn
                        else api.Displacement("temporary", uy=CLAMP_TARGETS[i]))
        stages.append(replace(
            previous, active_structures={"contact"} if active[i] else set(),
            load_split=FRACTIONS[i],
            displacements=(*previous.displacements, displacement) if CLAMPED[i]
            else previous.displacements,
            reset_displacements=i in (1, 4, 7),
        ))
    model.stages = stages
    return model, {**fixture, "active": active, "variant": variant}


def uniform_reference(gap, force_targets, top_targets, active):
    """Scalar free-face equilibrium, with an explicitly prescribed/removed clamp.

    Free lower: k*a-t=q1. Free upper: k*(b-v)+t=q2.
    If clamped, prescribe b instead; its reaction is k*(b-v)+t-physical.
    Previous native stresses/reactions are NEVER inputs to these equations.
    """
    a = b = v = physical = 0.0
    rows = []
    for i, fraction in enumerate(FRACTIONS):
        start_t = KN*min(gap+b-a, 0.0) if active[i] else 0.0
        h1 = (1-fraction)*(K*a-start_t)
        h2 = 0.0 if CLAMPED[i] else (1-fraction)*(K*(b-v)+start_t-physical)
        physical = (1-fraction)*physical+fraction*force_targets[i]/WIDTH
        v = (1-fraction)*v+fraction*top_targets[i]
        if CLAMPED[i]:
            b = (1-fraction)*b+fraction*CLAMP_TARGETS[i]
            t = min(0.0, KN*(gap+b-h1/K)/(1+KN/K)) if active[i] else 0.0
            a = (h1+t)/K
        else:
            t = (min(0.0, KN*(gap+v+(physical+h2-h1)/K)/(1+2*KN/K))
                 if active[i] else 0.0)
            a, b = (h1+t)/K, v+(physical+h2-t)/K
        rows.append(dict(
            lower_u=a, upper_u=b, top_u=v, gap=gap+b-a, traction=t,
            base_reaction=-WIDTH*K*a, top_reaction=WIDTH*K*(v-b),
            temporary_reaction=WIDTH*(K*(b-v)+t-physical) if CLAMPED[i] else 0.0,
            lower_release=WIDTH*h1, upper_release=WIDTH*h2, applied=WIDTH*physical,
        ))
    return rows


def error(actual, expected, tolerance):
    array = np.asarray(actual)
    finite = bool(np.isfinite(array).all() and np.isfinite(expected).all())
    difference = float(np.max(np.abs(array-expected), initial=0)) if finite else None
    return {"status": "passed" if finite and difference <= tolerance else "failed",
            "maximum_absolute_error": difference, "tolerance": tolerance}


def run_case(**kwargs):
    model, fixture = build_model(**kwargs)
    result = api.run(model)
    origin = (1.25, -0.75)
    audit = contact_support_equilibrium_by_stage(result, origin=origin)
    exact = uniform_reference(model.interfaces["contact"].initial_gap,
                              fixture["force_targets"], fixture["top_targets"], fixture["active"])
    normal = fixture["normal"]
    checks = []
    prior_u = np.zeros_like(result.initial.u)
    datum = prior_u.copy()
    for i, (stage, definition, row, target) in enumerate(zip(
        result.stages, model.stages, audit["stages"], exact,
    )):
        values = {}
        # Direct sum of products: independent of the audit's recurrence implementation.
        total = sum(np.asarray(fixture["analytical_targets"][j])*FRACTIONS[j]
                    *np.prod([1-f for f in FRACTIONS[j+1:i+1]]) for j in range(i+1))
        total[2] += -origin[0]*total[1]+origin[1]*total[0]
        values["physical_applied_resultant"] = error(
            row.get("physical_external_resultant", [np.nan]*3), total, 1e-8,
        )
        if definition.reset_displacements:
            datum = prior_u.copy()
        total_u = stage.u+datum
        if fixture["variant"] != "eccentric_support":
            for key in ("lower", "upper"):
                values[key+"_displacement_m"] = error(
                    total_u[model.mesh.nodes(key+"_contact")] @ normal, target[key+"_u"], 1e-10,
                )
            for nodes, key in (("bottom", "base"), ("top", "top"), ("temporary", "temporary")):
                values[key+"_reaction_kn_per_m"] = error(
                    stage.reactions[model.mesh.nodes(nodes), :2].sum(axis=0) @ normal,
                    target[key+"_reaction"], 1e-8,
                )
            retained = np.asarray(row.get("history", {}).get(
                "retained_release_nodal", np.full_like(stage.u, np.nan),
            ))
            for key in ("lower", "upper"):
                values[key+"_release_kn_per_m"] = error(
                    retained[model.mesh.nodes(key+"_contact")].sum(axis=0) @ normal,
                    target[key+"_release"], 1e-8,
                )
            if fixture["active"][i]:
                values["gap_m"] = error(stage.contact_gap["contact"], target["gap"], 1e-10)
                values["traction_kpa"] = error(
                    stage.interfaces["contact"][..., 1], target["traction"], 1e-8,
                )
        changes = row.get("support_changes", {})
        should_release = i > 0 and CLAMPED[i-1] and not CLAMPED[i]
        values["released_dof_membership"] = {"status": "passed" if (
            bool(changes.get("released_dofs")) == should_release) else "failed"}
        if not CLAMPED[i]:
            values["released_reactions_zero"] = error(
                stage.reactions[model.mesh.nodes("temporary"), :2] @ normal, 0.0, 1e-8,
            )
        if FRACTIONS[i] == 1.0:
            values["full_stage_physical_equilibrium"] = {
                "status": row.get("physical_equilibrium", {}).get("status", "failed"),
            }
        checks.append({"stage_index": i, "checks": values, "status": "passed" if all(
            value["status"] == "passed" for value in values.values()) else "failed"})
        prior_u = total_u
    return {**audit, "fixture": kwargs, "independent_reference_checks": checks,
            "status": "passed" if audit["status"] == "passed" and len(checks) == len(FRACTIONS)
            and all(check["status"] == "passed" for check in checks) else "failed"}


def run_benchmark():
    cases = [run_case(element_type=etype, initial_gap=gap, quarter_turn=rotation, variant=variant)
             for etype in ("IFACE4", "IFACE6") for gap in (0.0, 0.002)
             for rotation in (False, True) for variant in VARIANTS]
    return {"status": "passed" if all(case["status"] == "passed" for case in cases) else "failed",
            "native_solver": "api.run / StaticSolver", "case_count": len(cases),
            "stage_count": sum(case["stage_count"] for case in cases), "cases": cases,
            "scope": "Temporary displacement restraints with independently stable continuum. "
                     "Uniform cases have scalar targets; eccentric cases check equilibrium only. "
                     "Not excavation, gravity, friction or physical capacity validation."}


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

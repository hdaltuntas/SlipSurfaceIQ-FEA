"""Native api.run contact/continuum benchmark; no standalone Newton substitute.

A laterally constrained elastic layer has C=E*(1-nu)/((1+nu)*(1-2nu)).
Its bottom contacts a fixed base through kn*min(initial_gap+u_bottom,0).
The top is displacement controlled or fixed with bottom-face applied load.
Both yield independent scalar force balances for a uniform exact solution.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from slipsurface.fe2d import api
from slipsurface.fe2d.mesh import rectangle

WIDTH = 2.0
HEIGHT = 1.0
E = 2000.0
NU = 0.25
KN = 2000.0
CONSTRAINED_MODULUS = E * (1 - NU) / ((1 + NU) * (1 - 2 * NU))


def build_model(*, element_type="IFACE4", initial_gap=0.0, mode="displacement"):
    """Use actual continuum/interface blocks with an independent stable support."""
    if element_type not in ("IFACE4", "IFACE6") or mode not in ("displacement", "force"):
        raise ValueError("Unsupported element type or loading mode")
    etype = api.ElemType.Q4 if element_type == "IFACE4" else api.ElemType.Q8
    source = rectangle(WIDTH, HEIGHT, 1, 1, etype=etype)
    ids = source.nodes("bottom")
    ids = ids[np.argsort(source.coords[ids, 0])]
    face = ids if len(ids) == 2 else ids[[0, 2, 1]]
    base = np.arange(source.nn, source.nn + len(face))
    contact = api.ElementBlock(api.ElemType[element_type], np.r_[base, face][None, :],
                               np.array([0]), "contact")
    nodes = {**source.node_sets, "base": base, "solid": np.arange(source.nn)}
    mesh = api.Mesh(np.vstack([source.coords, source.coords[face]]),
                   (*source.blocks, contact), nodes, source.edge_sets)
    weights = [0.5, 0.5] if len(face) == 2 else [1 / 6, 1 / 6, 2 / 3]
    targets = ((0.006, 0.005, 0.001, -0.001, -0.003, 0.004, -0.004)
               if mode == "displacement" else (6.0, 5.0, -1.0, -12.0, -24.0, 4.0, -20.0))
    stages = []
    for i, target in enumerate(targets):
        stages.append(api.Stage(
            f"{mode}_{i}", active_structures={"contact"},
            displacements=((api.Displacement("top", uy=target),)
                           if mode == "displacement" else ()),
            loads=(tuple(api.PointLoad(int(node), fy=target * weight)
                         for node, weight in zip(face, weights)) if mode == "force" else ()),
            reset_displacements=i == 3,
        ))
    fixities = (api.Fixity("solid", True, False), api.Fixity("base", True, True),
                api.Fixity("top", False, True))
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN, mesh=mesh,
        materials={"solid": api.MaterialSpec.elastic("solid", E, NU)},
        region_material={1: "solid"}, fixities=fixities, initial=api.InitialStress("none"),
        stages=stages,
        interfaces={"contact": api.InterfaceSpec.unilateral_normal(
            "contact", KN, initial_gap=initial_gap)},
        settings=api.SolverSettings(dlam0=1.0, dlam_max=1.0, tol_force=1e-9,
                                    tol_energy=1e-9, max_iter=30, linear_solver="splu"),
    )
    return model, targets


def reference(target, initial_gap, mode):
    """Uniform continuum/contact equilibrium, independent of assembled matrices."""
    stiffness = CONSTRAINED_MODULUS / HEIGHT
    if mode == "displacement":
        bottom = (target if target >= -initial_gap else
                  (stiffness * target - KN * initial_gap) / (stiffness + KN))
        stress = stiffness * (target - bottom)
        top_reaction = WIDTH * stress
    elif mode == "force":
        q = target / WIDTH
        bottom = (q / stiffness if q >= -stiffness * initial_gap else
                  (q - KN * initial_gap) / (stiffness + KN))
        stress = -stiffness * bottom
        top_reaction = WIDTH * stress
    else:
        raise ValueError("Unknown loading mode")
    gap = initial_gap + bottom
    pressure = KN * min(gap, 0.0)
    return dict(gap=gap, pressure=pressure, top_reaction=top_reaction,
                base_reaction=-WIDTH * pressure, bottom=bottom)


def run_case(*, element_type="IFACE4", initial_gap=0.0, mode="displacement"):
    model, targets = build_model(element_type=element_type, initial_gap=initial_gap, mode=mode)
    result = api.run(model)
    rows = []
    for stage, target in zip(result.stages, targets):
        expected = reference(target, initial_gap, mode)
        values = {
            "gap_m": (stage.contact_gap["contact"], expected["gap"], 1e-10),
            "normal_traction_kpa": (stage.interfaces["contact"][..., 1],
                                    expected["pressure"], 1e-8),
            "shear_traction_kpa": (stage.interfaces["contact"][..., 0], 0.0, 1e-8),
            "top_reaction_kn_per_m": (stage.reactions[model.mesh.nodes("top"), 1].sum(),
                                      expected["top_reaction"], 1e-8),
            "base_reaction_kn_per_m": (stage.reactions[model.mesh.nodes("base"), 1].sum(),
                                       expected["base_reaction"], 1e-8),
            "global_equilibrium_kn_per_m": (stage.reactions[:, 1].sum(),
                                            -target if mode == "force" else 0.0, 1e-8),
        }
        checks = {}
        for key, (actual, expected_value, tolerance) in values.items():
            actual = np.asarray(actual)
            finite = bool(np.isfinite(actual).all())
            error = float(np.max(np.abs(actual - expected_value))) if finite else None
            checks[key] = {"status": "passed" if finite and error <= tolerance else "failed",
                           "maximum_absolute_error": error, "tolerance": tolerance}
        desired_status = 2 if expected["gap"] < 0 else 0
        statuses_match = bool(np.all(stage.contact_status["contact"] == desired_status))
        passed = statuses_match and all(c["status"] == "passed" for c in checks.values())
        rows.append({"stage": stage.name, "target": target,
                     "status": "passed" if passed else "failed", "checks": checks,
                     "reference": expected, "contact_status_matches": statuses_match,
                     "completed_load_factor": stage.lam})
    return {"status": "passed" if len(rows) == len(targets) and all(
        r["status"] == "passed" for r in rows) else "failed", "element_type": element_type,
        "initial_gap_m": initial_gap, "mode": mode, "stage_count": len(rows), "stages": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    cases = [run_case(element_type=etype, initial_gap=gap, mode=mode)
             for etype in ("IFACE4", "IFACE6") for gap in (0.0, 0.002)
             for mode in ("displacement", "force")]
    report = {"status": "passed" if all(x["status"] == "passed" for x in cases) else "failed",
              "native_solver": "api.run / StaticSolver", "case_count": len(cases),
              "stage_count": sum(x["stage_count"] for x in cases), "cases": cases,
              "scope": "Dry frictionless small-displacement contact with elastic continuum; "
                       "not hydraulic, arbitrary excavation or independent software validation."}
    payload = json.dumps(report, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

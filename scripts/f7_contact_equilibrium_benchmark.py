"""Native contact equilibrium: full node, component and external force/moment budgets.

Existing closed-form layer histories plus multi-element, eccentric point/edge loading,
contact deactivation/re-activation, two clearances and axis-aligned frame rotations.
The new multi-element cases test equilibrium, not an independent displacement solution.
"""

from __future__ import annotations

import argparse
import json
import runpy
from pathlib import Path

import numpy as np

from slipsurface.fe2d import api
from slipsurface.fe2d.mesh import rectangle
from slipsurface.fe2d.post.contact_equilibrium import contact_equilibrium_by_stage


def build_loaded_model(*, element_type="IFACE4", initial_gap=0.0, quarter_turn=False):
    """Stable constrained layer with nonuniform contact; no artificial stiffness."""
    if element_type not in ("IFACE4", "IFACE6"):
        raise ValueError("Require IFACE4 or IFACE6")
    etype = api.ElemType.Q4 if element_type == "IFACE4" else api.ElemType.Q8
    source = rectangle(2.0, 1.0, 2, 2, etype=etype)
    edges = source.edges("bottom").copy()
    # Contact face-1 tangent points from left to right, independently of edge-set ordering.
    for edge in edges:
        if source.coords[edge[1], 0] < source.coords[edge[0], 0]:
            edge[:2] = edge[:2][::-1]
    bottom = source.nodes("bottom")
    base = np.arange(source.nn, source.nn + len(bottom))
    pairs = dict(zip(bottom, base))
    contact = api.ElementBlock(
        api.ElemType[element_type],
        np.array([[*[pairs[n] for n in edge], *edge] for edge in edges]),
        np.zeros(len(edges), dtype=int),
        "contact",
    )
    rotation = np.array([[0.0, -1.0], [1.0, 0.0]]) if quarter_turn else np.eye(2)
    shift = np.array([3.25, -2.5])
    coords = np.vstack([source.coords, source.coords[bottom]]) @ rotation.T + shift
    mesh = api.Mesh(
        coords,
        (*source.blocks, contact),
        {**source.node_sets, "base": base, "solid": np.arange(source.nn)},
        source.edge_sets,
    )
    left = int(bottom[np.argmin(source.coords[bottom, 0])])
    right = int(bottom[np.argmax(source.coords[bottom, 0])])
    # qn>0 acts upward in the local layer frame; qt>0 acts rightward at its bottom.
    cases = (
        ("open", 3.0, 1.5, (0.0, 0.0), (0.0, 0.0), True),
        ("eccentric_close", -6.0, 2.0, (1.0, -4.0), (0.0, 0.0), True),
        ("reverse_eccentric", -3.0, -1.0, (-2.0, 0.0), (3.0, -12.0), True),
        ("contact_off", -4.0, 0.0, (0.0, -4.0), (0.0, 0.0), False),
        ("contact_on", -4.0, 0.0, (0.0, -4.0), (0.0, 0.0), True),
        ("reopen", 5.0, -2.0, (0.0, 0.0), (0.0, 0.0), True),
    )
    stages, references = [], []
    for name, qn, qt, left_force, right_force, active in cases:
        fleft, fright = rotation @ left_force, rotation @ right_force
        stages.append(
            api.Stage(
                name,
                active_structures={"contact"} if active else set(),
                loads=(
                    api.EdgeLoad("bottom", qn=qn, qt=qt),
                    api.PointLoad(left, fx=float(fleft[0]), fy=float(fleft[1])),
                    api.PointLoad(right, fx=float(fright[0]), fy=float(fright[1])),
                ),
                reset_displacements=name == "reverse_eccentric",
            )
        )
        fedge = rotation @ np.array([2 * qt, 2 * qn])
        points = [shift + rotation @ p for p in ([1.0, 0.0], [0.0, 0.0], [2.0, 0.0])]
        forces = [fedge, fleft, fright]
        total = sum(forces)
        moment = sum(x[0] * f[1] - x[1] * f[0] for x, f in zip(points, forces))
        references.append([float(total[0]), float(total[1]), float(moment)])
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"solid": api.MaterialSpec.elastic("solid", 2000.0, 0.25)},
        region_material={1: "solid"},
        initial=api.InitialStress("none"),
        stages=stages,
        fixities=(
            api.Fixity("solid", not quarter_turn, quarter_turn),
            api.Fixity("base", True, True),
            api.Fixity("top", quarter_turn, not quarter_turn),
        ),
        interfaces={
            "contact": api.InterfaceSpec.unilateral_normal(
                "contact", 2000.0, initial_gap=initial_gap
            )
        },
        settings=api.SolverSettings(
            dlam0=1.0,
            dlam_max=1.0,
            tol_force=1e-10,
            tol_energy=1e-10,
            max_iter=40,
            linear_solver="splu",
        ),
    )
    return model, references


def run_benchmark():
    legacy = runpy.run_path(str(Path(__file__).with_name("f7_contact_static_benchmark.py")))
    runs = []
    for etype in ("IFACE4", "IFACE6"):
        for clearance in (0.0, 0.002):
            for mode in ("displacement", "force"):
                model, _ = legacy["build_model"](
                    element_type=etype, initial_gap=clearance, mode=mode
                )
                solved = api.run(model)
                report = contact_equilibrium_by_stage(solved)
                runs.append({"case": f"layer_{etype}_{clearance}_{mode}", **report})
            for turned in (False, True):
                model, reference = build_loaded_model(
                    element_type=etype, initial_gap=clearance, quarter_turn=turned
                )
                solved = api.run(model)
                report = contact_equilibrium_by_stage(solved, origin=(1.25, -0.75))
                for row, expected in zip(report["stages"], reference):
                    expected[2] += -1.25 * expected[1] - 0.75 * expected[0]
                    actual = np.asarray(row.get("external_resultant", [np.nan] * 3))
                    valid = bool(
                        np.isfinite(actual).all() and np.max(np.abs(actual - expected)) < 1e-8
                    )
                    row["hand_derived_applied_resultant"] = expected
                    row["applied_reference_passed"] = valid
                    if not valid:
                        row["status"] = "failed"
                if any(row["status"] != "passed" for row in report["stages"]):
                    report["status"] = "failed"
                runs.append({"case": f"eccentric_{etype}_{clearance}_{turned}", **report})
    return {
        "status": "passed" if all(r["status"] == "passed" for r in runs) else "failed",
        "native_solver": "api.run / StaticSolver",
        "case_count": len(runs),
        "stage_count": sum(r["stage_count"] for r in runs),
        "cases": runs,
        "scope": "Numerical equilibrium of dry continuum/normal-contact histories only. "
        "Native continuum quadrature is shared; no independent full FE solver, "
        "general excavation, capacity or RS2/PLAXIS validation is claimed.",
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

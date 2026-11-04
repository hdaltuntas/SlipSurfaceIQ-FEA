"""Execute three-mesh dry pile/anchor excavation with surcharge, shear and head force."""

from __future__ import annotations

import argparse
import json
import math
import runpy
from dataclasses import replace
from pathlib import Path

import numpy as np

from slipsurface.fe2d import api
from slipsurface.fe2d.post.coupled_dry_budget import coupled_dry_budget_by_stage


def loaded_case(model):
    """Load the retained 15 m right-hand top surface and original pile head."""
    top = model.mesh.edges("Soil:3")
    midpoint = model.mesh.coords[top[:, :2]].mean(axis=1)
    retained = top[midpoint[:, 0] > 0.]
    mesh = replace(model.mesh, edge_sets={**model.mesh.edge_sets, "loaded_top": retained})
    pile_nodes = np.unique(mesh.block("cad_Pile").conn)
    head = int(pile_nodes[np.argmax(mesh.coords[pile_nodes, 1])])
    if not np.allclose(mesh.coords[head], [0., 0.]):
        raise ValueError("Expected original pile head at the global origin")
    loads = (api.EdgeLoad("loaded_top", qn=20., qt=3.), api.PointLoad(head, fx=10., fy=-5.))
    return replace(model, mesh=mesh, stages=[replace(step, loads=loads) for step in model.stages])


def run(sizes):
    helpers = runpy.run_path(str(
        Path(__file__).resolve().parents[1] / "examples/f7_excavation_mesh_audit.py"
    ))
    base = helpers["excavation_model"]()
    rows, failures = [], []
    for h in sizes:
        try:
            model = loaded_case(helpers["build_case"](base, h))
            result = api.run(model)
            for stage, budget in zip(result.stages, coupled_dry_budget_by_stage(model, result)):
                matches = bool(np.allclose(
                    budget.get("applied_load_resultant", [np.nan] * 3),
                    [-35., -305., -2250.], rtol=0., atol=1e-8,
                ))
                rows.append({"h_m": h, "stage": stage.name, "budget": budget,
                             "analytical_applied_reference_passed": matches})
        except Exception as exc:
            failures.append({"h_m": h, "type": type(exc).__name__, "detail": str(exc)})
    complete = len(rows) == len(sizes) * len(base.stages) and not failures
    return {
        "case": "Canonical dry excavation with right-top pressure/shear and pile-head force",
        "mesh_sizes_m": list(sizes), "results": rows, "failures": failures,
        "status": "passed" if complete and all(
            row["budget"]["status"] == "passed" and row["analytical_applied_reference_passed"]
            for row in rows
        ) else "failed",
        "analytical_applied_resultant": [-35., -305., -2250.],
        "warning": "Bounded dry numerical equilibrium only; no independent physical validation.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=float, nargs="+", default=[2.5, 1.8, 1.2])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (len(args.sizes) < 3 or len(set(args.sizes)) != len(args.sizes)
            or any(not math.isfinite(h) or h <= 0 for h in args.sizes)):
        parser.error("Require at least three distinct finite positive mesh sizes")
    report = run(tuple(args.sizes))
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

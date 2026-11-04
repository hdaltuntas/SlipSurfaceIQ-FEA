"""Three-mesh loaded excavation with top infiltration and an atmospheric right face."""

from __future__ import annotations

import argparse
import json
import math
import runpy
from dataclasses import replace
from pathlib import Path

import numpy as np

from slipsurface.fe2d import api
from slipsurface.fe2d.post.coupled_seepage_budget import coupled_seepage_budget_by_stage


def boundary_case(model):
    water = api.WaterCondition.seepage({"Soil:4": 1.}, fluxes={"Soil:3": 1e-8},
                                      seepage_faces=("Soil:2",))
    return replace(model,
        materials={tag: replace(spec, gamma_sat=20.) for tag, spec in model.materials.items()},
        initial=replace(model.initial, water=water),
        stages=[replace(step, water=water) for step in model.stages],
    )


def run(sizes):
    root = Path(__file__).resolve().parents[1]
    helper = runpy.run_path(str(root / "examples/f7_excavation_mesh_audit.py"))
    loaded = runpy.run_path(str(root / "scripts/f7_loaded_excavation_audit.py"))["loaded_case"]
    base = helper["excavation_model"]()
    rows, failures = [], []
    for h in sizes:
        try:
            model = boundary_case(loaded(helper["build_case"](base, h)))
            solved = api.run(model)
            for index, budget in enumerate(coupled_seepage_budget_by_stage(model, solved)):
                stage = solved.stages[index]
                expected_flux = (30. if index == 0 else 15.) * 1e-8
                matches = bool(np.isclose(budget.get("prescribed_flux_inflow_m2_per_s", np.nan),
                                          expected_flux, rtol=0., atol=1e-15))
                rows.append({
                    "h_m": h, "stage": stage.name, "budget": budget,
                    "analytical_flux_inflow_m2_per_s": expected_flux,
                    "analytical_flux_reference_passed": matches,
                    "reported_boundary_flows_m2_per_s": stage.flow,
                    "nodal_head_m": [float(x) if np.isfinite(x) else None for x in stage.head],
                    "seepage_nodal_flux_m2_per_s": stage.seepage_nodal_flux.tolist(),
                    "active_seepage_node_ids": stage.seepage_nodes.tolist(),
                    "solver_diagnostics": stage.seepage_diagnostics,
                })
        except Exception as exc:
            failures.append({"h_m": h, "type": type(exc).__name__, "detail": str(exc)})
    complete = len(rows) == len(sizes)*3 and not failures
    return {
        "case": "Loaded excavation with prescribed infiltration and atmospheric seepage face",
        "mesh_sizes_m": list(sizes), "results": rows, "failures": failures,
        "status": "passed" if complete and all(
            row["budget"]["status"] == "passed" and row["analytical_flux_reference_passed"]
            for row in rows
        ) else "failed",
        "warning": "Boundary evidence and coupled transfer only; no independent Darcy residual.",
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

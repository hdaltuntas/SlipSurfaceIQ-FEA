"""Actual three-mesh loaded excavation with prescribed-head seepage around the pile."""

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


def seepage_case(model):
    water = api.WaterCondition.seepage({"Soil:4": 1., "Soil:2": 0.})
    return replace(model,
        materials={tag: replace(spec, gamma_sat=20.) for tag, spec in model.materials.items()},
        initial=replace(model.initial, water=water),
        stages=[replace(step, water=water) for step in model.stages],
    )


def run(sizes):
    root = Path(__file__).resolve().parents[1]
    helpers = runpy.run_path(str(root / "examples/f7_excavation_mesh_audit.py"))
    loaded = runpy.run_path(str(root / "scripts/f7_loaded_excavation_audit.py"))["loaded_case"]
    base = helpers["excavation_model"]()
    rows, failures = [], []
    for h in sizes:
        try:
            model = seepage_case(loaded(helpers["build_case"](base, h)))
            solved = api.run(model)
            for index, budget in enumerate(coupled_seepage_budget_by_stage(model, solved)):
                stage = solved.stages[index]
                reference = {
                    "external_weight_resultant": [
                        0., -(420 - 30*index)*20 - np.pi*0.8**2/4/2*9*24, -4500.*index,
                    ],
                    "applied_load_resultant": [-35., -305., -2250.],
                }
                matches = all(np.allclose(budget.get(key, [np.nan]*3), value,
                                         rtol=0., atol=1e-7) for key, value in reference.items())
                rows.append({
                    "h_m": h, "stage": stage.name, "budget": budget,
                    "analytical_weight_and_load_reference": reference,
                    "analytical_weight_and_load_reference_passed": bool(matches),
                    "nodal_head_m": [float(x) if np.isfinite(x) else None for x in stage.head],
                    "reported_boundary_flows_m2_per_s": stage.flow,
                })
        except Exception as exc:
            failures.append({"h_m": h, "type": type(exc).__name__, "detail": str(exc)})
    complete = len(rows) == len(sizes)*3 and not failures
    return {
        "case": "Loaded full-stage seepage excavation with left/right heads 1/0 m",
        "mesh_sizes_m": list(sizes), "results": rows, "failures": failures,
        "status": "passed" if complete and all(
            row["budget"]["status"] == "passed"
            and row["analytical_weight_and_load_reference_passed"] for row in rows
        ) else "failed",
        "warning": (
            "Seepage field transfer and reported flow conservation; "
            "no independent Darcy validation."
        ),
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

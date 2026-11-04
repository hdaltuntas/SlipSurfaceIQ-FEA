"""Loaded three-mesh excavation with partial releases, drawdown and rewetting."""

from __future__ import annotations

import argparse
import json
import math
import runpy
from dataclasses import replace
from pathlib import Path

from slipsurface.fe2d import api
from slipsurface.fe2d.post.incremental_hydrostatic_budget import (
    incremental_hydrostatic_budget_by_stage,
)


def wet_partial_schedule(model):
    pile, dig, anchor = model.stages
    wet = api.WaterCondition.piezo([[0., 0.]])
    low = api.WaterCondition.piezo([[0., -2.]])
    installed = replace(anchor, active_regions=dig.active_regions)
    return replace(model,
        materials={tag: replace(spec, gamma_sat=20.) for tag, spec in model.materials.items()},
        initial=replace(model.initial, water=wet), stages=[
            replace(pile, water=wet),
            replace(dig, name="wet first lift 40 percent", water=wet, load_split=0.4),
            replace(dig, name="wet first lift 70 percent", water=wet, load_split=0.5),
            replace(installed, name="anchor and complete first lift", water=wet),
            replace(installed, name="drawdown 40 percent", water=low, load_split=0.4),
            replace(installed, name="complete drawdown", water=low),
            replace(anchor, name="lowered second lift 40 percent", water=low, load_split=0.4),
            replace(anchor, name="complete second lift", water=low),
            replace(anchor, name="rewet 50 percent", water=wet, load_split=0.5),
            replace(anchor, name="complete rewetting", water=wet),
        ],
    )


def run(sizes):
    root = Path(__file__).resolve().parents[1]
    helpers = runpy.run_path(str(root / "examples/f7_excavation_mesh_audit.py"))
    loaded = runpy.run_path(str(root / "scripts/f7_loaded_excavation_audit.py"))["loaded_case"]
    base = helpers["excavation_model"]()
    rows, failures = [], []
    for h in sizes:
        try:
            model = wet_partial_schedule(loaded(helpers["build_case"](base, h)))
            solved = api.run(model)
            for stage, budget in zip(solved.stages,
                                     incremental_hydrostatic_budget_by_stage(model, solved)):
                rows.append({"h_m": h, "stage": stage.name, "budget": budget})
        except Exception as exc:
            failures.append({"h_m": h, "type": type(exc).__name__, "detail": str(exc)})
    complete = len(rows) == len(sizes) * 10 and not failures
    return {
        "case": "Loaded partial wet excavation with drawdown and rewetting",
        "mesh_sizes_m": list(sizes), "results": rows, "failures": failures,
        "status": "passed" if complete and all(
            row["budget"]["status"] == "passed" for row in rows
        ) else "failed",
        "warning": "Elastic horizontal-head history accounting only; no physical validation.",
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

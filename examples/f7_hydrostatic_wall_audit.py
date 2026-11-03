"""F7 standalone closed-form hydrostatic wall force verification.

Run from repository root:

    python examples/f7_hydrostatic_wall_audit.py --output f7_hydrostatic_wall.json

This is a boundary integration benchmark, not an entire FEM excavation
or coupled pore-pressure/stress equilibrium analysis.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from slipsurface.fe2d.model.boundary import WaterCondition
from slipsurface.fe2d.post.balance_acceptance import classify_balance
from slipsurface.fe2d.post.hydrostatic_reference import compare_vertical_water_edge


def run_reference():
    # Wall at x=0, ground on right; water level at -2 m is an actual mesh node.
    mesh = SimpleNamespace(coords=np.array([
        [0.0, 0.0], [0.0, -2.0], [0.0, -4.0],
    ]))
    water = WaterCondition.piezo([(0.0, -2.0)])
    results = []
    for edge, center in [
        ([0, 1], (1.0, -1.0)),
        ([1, 2], (1.0, -3.0)),
    ]:
        result = compare_vertical_water_edge(mesh, edge, center, water)
        accepted = classify_balance(result, "relative_resultant_error", tolerance=1e-10)
        results.append({"edge_node_ids": edge, **accepted})
    return {
        "reference": "Vertical 4 m wall, ground to right, water head -2 m",
        "scope": "plane-strain hydrostatic exposed-boundary traction only",
        "results": results,
        "all_edges_passed": all(row["status"] == "passed" for row in results),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("f7_hydrostatic_wall.json"))
    args = parser.parse_args()
    report = run_reference()
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    return 0 if report["all_edges_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

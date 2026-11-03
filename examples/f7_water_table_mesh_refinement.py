"""F7 optional three-mesh groundwater reaction verification.

Run from repository root:

    python examples/f7_water_table_mesh_refinement.py --output f7_water_mesh.json

A horizontal water table deliberately cuts all three different meshes.
The independent reference uses exact straight-sided polygon clipping.
The tool records convergence *or lack of it* and returns nonzero if
the finest mesh has not met the specified equilibrium tolerance.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.mesh import layered_box
from slipsurface.fe2d.post.saturated_column_balance import saturated_column_budget
from slipsurface.fe2d.post.water_mesh_convergence import water_table_mesh_comparison


def make_column(n: int, etype: ElemType, head: float):
    """Same 2 x 10 m physical column, refined by number of vertical rows."""
    if n < 2:
        raise ValueError("At least two rows in the top layer are required")
    mesh = layered_box(
        2.0, [0.0, -4.0], -10.0,
        nx=2, ny_per_layer=[n, int(math.ceil(1.5 * n))], etype=etype,
    )
    spec = api.MaterialSpec.elastic(
        "soil", 20000.0, 0.3, gamma=17.0, gamma_sat=20.0
    )
    return api.Model(
        api.Analysis.PLANE_STRAIN,
        mesh,
        {"soil": spec},
        {1: "soil", 2: "soil"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        initial=api.InitialStress(
            "gravity", water=api.WaterCondition.piezo([(0.0, head)])
        ),
    )


def run_study(resolutions=(2, 4, 8), *, head=-2.37, etype=ElemType.T6,
              tolerance=1e-6):
    if not math.isfinite(head) or not -4.0 < head < 0:
        raise ValueError("Choose a finite water level strictly inside the top 4 m")
    if len(resolutions) < 3 or any(
        not isinstance(n, int) or n < 2 for n in resolutions
    ):
        raise ValueError("At least three positive integer mesh resolutions required")
    if any(right <= left for left, right in zip(resolutions, resolutions[1:])):
        raise ValueError("Resolutions must increase strictly")
    rows = []
    for n in resolutions:
        model = make_column(n, etype, head)
        solved = api.run(model)
        balance = saturated_column_budget(model, solved, exact_cut=True)
        rows.append({
            **balance,
            "h_m": 4.0 / n,
            "nodes": model.mesh.nn,
            "elements": sum(block.ne for block in model.mesh.continuum_blocks()),
        })
    result = water_table_mesh_comparison(rows, tolerance=tolerance)
    result.update({
        "case": "2 m x 10 m hydrostatic saturated column; no excavation or supports",
        "element_type": etype.name,
        "water_head_m": head,
        "top_layer_rows": list(resolutions),
        "acceptance_tolerance": tolerance,
    })
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("f7_water_mesh.json"))
    parser.add_argument("--head", type=float, default=-2.37)
    parser.add_argument("--rows", type=int, nargs="+", default=[2, 4, 8])
    parser.add_argument("--element", choices=["T3", "T6", "Q4", "Q8"], default="T6")
    parser.add_argument("--tolerance", type=float, default=1e-6)
    args = parser.parse_args()
    report = run_study(
        tuple(args.rows), head=args.head,
        etype=ElemType[args.element], tolerance=args.tolerance,
    )
    args.output.write_text(
        json.dumps(report, indent=2, allow_nan=False), encoding="utf-8"
    )
    return 0 if report["finest_mesh_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

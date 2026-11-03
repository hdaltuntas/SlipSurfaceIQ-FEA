"""F7 optional joint local/global water-table mesh verification.

Run from repo root:
    python examples/f7_water_cut_field_audit.py --rows 2 4 8 --output f7_water_cut.json

The water table at -2.37 m cuts elements on every mesh. Exact geometric
clipping supplies the independent global reference; the independent local
hydrostatic profile is evaluated at actual Gauss points. No tolerance is
relaxed to make constant-strain T3 meshes pass.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.mesh import layered_box
from slipsurface.fe2d.post.local_water_stress import local_column_errors
from slipsurface.fe2d.post.saturated_column_balance import saturated_column_budget
from slipsurface.fe2d.post.water_cut_field_audit import compare_water_cut_fields


def make_column(rows, element, head):
    if rows < 2:
        raise ValueError("At least two top-layer rows required")
    mesh = layered_box(
        2.0, [0.0, -4.0], -10.0,
        nx=2, ny_per_layer=[rows, math.ceil(1.5 * rows)], etype=element,
    )
    mat = api.MaterialSpec.elastic(
        "soil", 20000.0, 0.3, gamma=17.0, gamma_sat=20.0,
    )
    return api.Model(
        api.Analysis.PLANE_STRAIN, mesh,
        {"soil": mat}, {1: "soil", 2: "soil"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        initial=api.InitialStress(
            "gravity", water=api.WaterCondition.piezo([(0.0, head)])
        ),
    )


def run_study(resolutions=(2, 4, 8), *, head=-2.37, element=ElemType.T3,
              tolerance=1e-6):
    if not math.isfinite(head) or not -4.0 < head < 0.0:
        raise ValueError("Water level must lie inside the upper 4 m soil layer")
    if len(resolutions) < 2 or any(
        not isinstance(n, int) or n < 2 for n in resolutions
    ) or any(b <= a for a, b in zip(resolutions, resolutions[1:])):
        raise ValueError("Mesh row counts must increase strictly")
    rows = []
    for n in resolutions:
        model = make_column(n, element, head)
        result = api.run(model)
        rows.append({
            "h_m": 4.0 / n, "head_m": head,
            "nodes": model.mesh.nn,
            "elements": sum(b.ne for b in model.mesh.continuum_blocks()),
            "global": saturated_column_budget(model, result, exact_cut=True),
            "local": local_column_errors(model, result),
        })
    report = compare_water_cut_fields(rows, tolerance=tolerance)
    report.update({
        "case": "2 m x 10 m gravity column; horizontal water table cuts elements",
        "element_type": element.name,
        "vertical_rows": list(resolutions),
        "acceptance_tolerance": tolerance,
    })
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, nargs="+", default=[2, 4, 8])
    parser.add_argument("--head", type=float, default=-2.37)
    parser.add_argument("--element", choices=["T3", "T6", "Q4", "Q8"], default="T3")
    parser.add_argument("--tolerance", type=float, default=1e-6)
    parser.add_argument("--output", type=Path, default=Path("f7_water_cut.json"))
    args = parser.parse_args()
    report = run_study(
        tuple(args.rows), head=args.head,
        element=ElemType[args.element], tolerance=args.tolerance,
    )
    args.output.write_text(
        json.dumps(report, allow_nan=False, indent=2), encoding="utf-8"
    )
    return 0 if report["finest_mesh_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""F7 local hydrostatic pore/effective-stress mesh audit.

Run from repository root:

    python examples/f7_local_stress_refinement.py --output f7_local_stress.json

A horizontal water table is lowered in a two-layer rectangular column.
The reference is the closed-form one-dimensional vertical effective-stress
profile, evaluated at each mesh's actual Gauss points.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.mesh import layered_box
from slipsurface.fe2d.post.local_stress_refinement import compare_local_stress_meshes
from slipsurface.fe2d.post.local_water_stress import local_column_errors


def make_column(rows, etype):
    if rows < 2 or rows % 2:
        raise ValueError("Vertical rows per upper layer must be even and >= 2")
    mesh = layered_box(
        2., [0., -4.], -10., nx=2, ny_per_layer=[rows, 3 * rows // 2],
        etype=etype,
    )
    soil = api.MaterialSpec.elastic(
        "soil", 20000., 0.3, gamma=17., gamma_sat=20.,
    )
    return api.Model(
        api.Analysis.PLANE_STRAIN, mesh, {"soil": soil},
        {1: "soil", 2: "soil"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        initial=api.InitialStress(
            "gravity", water=api.WaterCondition.piezo([(0., 0.)])
        ),
        stages=[
            api.Stage(
                "lower water table",
                water=api.WaterCondition.piezo([(0., -4.)]),
            ),
        ],
    )


def run_study(resolutions=(2, 4, 8), *, etype=ElemType.T3, tolerance=1e-6):
    if len(resolutions) < 2 or any(
        not isinstance(n, int) or n < 2 or n % 2
        for n in resolutions
    ) or any(b <= a for a, b in zip(resolutions, resolutions[1:])):
        raise ValueError("At least two strictly increasing positive even row counts required")
    rows = []
    for n in resolutions:
        model = make_column(n, etype)
        solved = api.run(model)
        for index in (None, 0):
            metric = local_column_errors(model, solved, index)
            rows.append({
                **metric,
                "h_m": 4. / n,
                "nodes": model.mesh.nn,
                "elements": sum(block.ne for block in model.mesh.continuum_blocks()),
            })
    report = compare_local_stress_meshes(rows, tolerance=tolerance)
    report.update({
        "case": "2 m x 10 m drained elastic column with lowered water level",
        "element_type": etype.name,
        "vertical_rows": list(resolutions),
        "tolerance": tolerance,
    })
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("f7_local_stress.json"))
    parser.add_argument("--rows", type=int, nargs="+", default=[2, 4, 8])
    parser.add_argument("--element", choices=["T3", "T6"], default="T3")
    parser.add_argument("--tolerance", type=float, default=1e-6)
    args = parser.parse_args()
    result = run_study(
        tuple(args.rows), etype=ElemType[args.element], tolerance=args.tolerance,
    )
    args.output.write_text(
        json.dumps(result, indent=2, allow_nan=False), encoding="utf-8"
    )
    return 0 if result["all_rows_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

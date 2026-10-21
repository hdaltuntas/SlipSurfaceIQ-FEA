"""Compare the same staged excavation using pure T6 and conforming T6/Q8 meshes.

Both use the selected quadrature; high uses T6 six points and Q8 nine points.
The original example's
historical default-quadrature result is not an equivalent integration comparison.
Failed runs report the stage/load factor; no final moment/displacement is fabricated.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time

import numpy as np
from sheet_pile_staged_excavation import model

from slipsurface.fe2d import api
from slipsurface.fe2d.core.errors import NonConvergence, SingularSystemError
from slipsurface.fe2d.fem.static import StaticSolver


class TracedSolver(StaticSolver):
    current_stage = "initial"

    def solve_stage_ctx(self, state, ctx, lay, settings=None):
        self.current_stage = ctx.stage.name
        return super().solve_stage_ctx(state, ctx, lay, settings)


def compare(sizes, gauss_order="high", soil_tension=None):
    rows = []
    for h in sizes:
        for mixed in (False, True):
            start = time.perf_counter()
            m = model(h, mixed=mixed, gauss_order=gauss_order, soil_tension=soil_tension)
            mesh_time = time.perf_counter() - start
            solver = TracedSolver(m)
            row = {
                "size": h,
                "gauss_order": gauss_order,
                "soil_tension": soil_tension,
                "mesh": "T6+Q8" if mixed else "T6",
                "nodes": m.mesh.nn,
                "T6": sum(b.ne for b in m.mesh.blocks if b.etype is api.ElemType.T6),
                "Q8": sum(b.ne for b in m.mesh.blocks if b.etype is api.ElemType.Q8),
                "gauss_points": sum(g.ne * g.ngp for g in solver.geom.values()),
                "mesh_seconds": round(mesh_time, 3),
                "solve_seconds": None,
                "converged": False,
                "stage": None,
                "lambda": None,
                "max_moment": None,
                "max_displacement": None,
                "error": None,
            }
            start = time.perf_counter()
            try:
                result = solver.run()
                row.update(
                    converged=True,
                    stage=result.last.name,
                    **{"lambda": result.last.lam},
                    max_moment=float(np.nanmax(np.abs(result.last.beams["pile"][:, :, 2]))),
                    max_displacement=float(np.nanmax(np.linalg.norm(result.last.u, axis=1))),
                )
            except NonConvergence as e:
                row.update(stage=solver.current_stage, **{"lambda": e.lam}, error=str(e))
            except SingularSystemError as e:
                row.update(stage=solver.current_stage, error=str(e))
            row["solve_seconds"] = round(time.perf_counter() - start, 3)
            rows.append(row)
            print(row, flush=True)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=float, nargs="+", default=[0.5, 0.25])
    parser.add_argument("--csv", help="optional comparison CSV path")
    parser.add_argument("--gauss-order", choices=["default", "high"], default="high")
    parser.add_argument(
        "--soil-tension",
        type=float,
        default=None,
        help="explicit soil tensile strength [kPa]; omitted means no Rankine flow",
    )
    args = parser.parse_args()
    if any(not np.isfinite(h) or h <= 0 for h in args.sizes):
        parser.error("sizes must be positive")
    if args.soil_tension is not None and (
        not np.isfinite(args.soil_tension) or args.soil_tension < 0
    ):
        parser.error("--soil-tension must be finite and nonnegative")
    rows = compare(args.sizes, args.gauss_order, args.soil_tension)
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    return 0 if all(row["converged"] for row in rows) else 1


if __name__ == "__main__":
    sys.exit(main())

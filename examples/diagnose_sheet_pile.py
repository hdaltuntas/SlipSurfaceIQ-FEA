"""Record Newton failures without treating the last partial state as a completed stage.

Run from a checkout with PYTHONPATH=src. JSON contains accepted/rejected attempts,
force/energy residual histories and a force-balance check at the last committed state.
This diagnostic uses internal solver APIs; it is not a restart/export format.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
from sheet_pile_staged_excavation import model

from slipsurface.fe2d import api
from slipsurface.fe2d.core.errors import MaterialIntegrationError, NonConvergence
from slipsurface.fe2d.fem.static import StaticSolver


class DiagnosticSolver(StaticSolver):
    current_stage = "initial"
    failure = None

    def integrate(self, state, du, sysm, lay):
        try:
            return super().integrate(state, du, sysm, lay)
        except MaterialIntegrationError:
            self.material_return_failures = getattr(self, "material_return_failures", 0) + 1
            raise

    def solve_stage_ctx(self, state, ctx, lay, settings=None):
        self.current_stage = ctx.stage.name
        return super().solve_stage_ctx(state, ctx, lay, settings)

    def solve_increment(self, state, sysm, lay, f_ext, du_presc, settings=None, lam_end=1.0):
        _, f0 = self.integrate_committed(state, sysm, lay)
        try:
            return super().solve_increment(state, sysm, lay, f_ext, du_presc, settings, lam_end)
        except NonConvergence as exc:
            _, fint = self.integrate_committed(state, sysm, lay)
            residual = exc.lam * f_ext + (1 - exc.lam) * f0 - fint
            dm = sysm.dm
            free_residual = np.zeros(dm.ndof)
            free_residual[dm.free] = residual[dm.free]
            free_nodal = np.nan_to_num(dm.nodal(free_residual, comps=3))
            ids = np.argsort(np.linalg.norm(free_nodal, axis=1))[-10:][::-1]
            self.failure = {
                "last_committed_lambda": exc.lam,
                "free_residual_norm": float(np.linalg.norm(residual[dm.free])),
                "max_translation": float(
                    np.max(np.linalg.norm(state.reported_u()[dm.used_nodes, :2], axis=1))
                ),
                "largest_free_residual_nodes": [
                    {
                        "node": int(n),
                        "xy": self.mesh.coords[n].tolist(),
                        "residual": free_nodal[n].tolist(),
                    }
                    for n in ids
                ],
                "active_plastic_gp": {
                    tag: int(np.count_nonzero(flags[state.active[tag]]))
                    for tag, flags in state.plastic.items()
                },
                "active_continuum_flags": {
                    tag: dict(Counter(map(int, flags[state.active[tag]].ravel())))
                    for tag, flags in state.plastic.items()
                },
                "active_interface_flags": {
                    tag: dict(Counter(map(int, flags[state.active[tag]].ravel())))
                    for tag, flags in state.struct_flag.items()
                    if tag in self.model.interfaces
                },
            }
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=float, default=0.5)
    parser.add_argument("--mixed", action="store_true")
    parser.add_argument("--gauss-order", choices=["default", "high"], default="high")
    parser.add_argument(
        "--elastic-soil", action="store_true", help="isolate interface nonlinearity"
    )
    parser.add_argument("--no-line-search", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not np.isfinite(args.size) or args.size <= 0:
        parser.error("--size must be finite and positive")
    m = model(args.size, mixed=args.mixed, gauss_order=args.gauss_order)
    if args.elastic_soil:
        soil = m.materials["sand"]
        m = replace(
            m,
            materials={
                "sand": api.MaterialSpec.elastic(
                    "sand",
                    E=soil.params["E"],
                    nu=soil.params["nu"],
                    gamma=soil.gamma_unsat,
                    gamma_sat=soil.gamma_sat,
                )
            },
        )
    if args.no_line_search:
        m = replace(m, settings=replace(m.settings, line_search=False))
    solver = DiagnosticSolver(m)
    report = {
        "options": {k: v for k, v in vars(args).items() if k != "output"},
        "nodes": m.mesh.nn,
        "converged": False,
    }
    try:
        result = solver.run()
        report.update(
            converged=True,
            histories={
                st.name: asdict(st.history)
                for st in [result.initial, *result.stages]
                if st.history is not None
            },
        )
    except NonConvergence as exc:
        report.update(
            stage=solver.current_stage,
            error=str(exc),
            failure=solver.failure,
            history=asdict(exc.history) if exc.history is not None else None,
        )
    report.update(material_return_failures=getattr(solver, "material_return_failures", 0))
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(
        json.dumps({k: v for k, v in report.items() if k not in ("history", "histories")}, indent=2)
    )
    return 0 if report["converged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

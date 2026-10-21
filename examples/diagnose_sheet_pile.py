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
from slipsurface.fe2d.fem.diagnostics import (
    jacobian_report,
    spatial_stress_report,
    stiffness_report,
)
from slipsurface.fe2d.fem.static import StaticSolver
from slipsurface.fe2d.mesh import mesh_quality


class DiagnosticSolver(StaticSolver):
    current_stage = "initial"
    failure = None

    def __init__(self, *args, audit=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.audit_enabled = audit
        self.audits = []
        self.material_failure_first = None
        self.material_failure_last = None

    def audit_state(self, state, sysm, lam):
        if not self.audit_enabled:
            return
        free = sysm.dm.free
        D, K = self._elastic_DK(sysm)
        elastic = self._stiffness(sysm, D, K)[free][:, free]
        committed = None
        if self._D_committed_key == sysm.key and self._D_committed is not None:
            D, K = self._D_committed
            committed = stiffness_report(self._stiffness(sysm, D, K)[free][:, free])
        cont = [c for c in sysm.cont if c.ids.size]
        points = {
            "excavation_corner": [0.0, -5.0],
            "wall_tip": [0.0, -10.5],
            "wall_top": [0.0, 0.0],
        }
        spatial = spatial_stress_report(
            np.concatenate([c.geom.xg.reshape(-1, 2) for c in cont]),
            np.concatenate([state.sig[c.tag][c.ids].reshape(-1, 4) for c in cont]),
            np.concatenate([c.geom.wdet.ravel() for c in cont]),
            points,
        )
        self.audits.append(
            {
                "stage": self.current_stage,
                "lambda": lam,
                "elastic_stiffness": stiffness_report(elastic),
                "last_committed_tangent": committed,
                "stress_probes": spatial,
            }
        )

    def integrate(self, state, du, sysm, lay):
        try:
            return super().integrate(state, du, sysm, lay)
        except MaterialIntegrationError as exc:
            self.material_return_failures = getattr(self, "material_return_failures", 0) + 1
            record = {"stage": self.current_stage, "details": exc.details}
            if self.material_failure_first is None:
                self.material_failure_first = record
            self.material_failure_last = record
            raise

    def solve_stage_ctx(self, state, ctx, lay, settings=None):
        self.current_stage = ctx.stage.name
        return super().solve_stage_ctx(state, ctx, lay, settings)

    def solve_increment(self, state, sysm, lay, f_ext, du_presc, settings=None, lam_end=1.0):
        _, f0 = self.integrate_committed(state, sysm, lay)
        try:
            result = super().solve_increment(state, sysm, lay, f_ext, du_presc, settings, lam_end)
            self.audit_state(state, sysm, lam_end)
            return result
        except NonConvergence as exc:
            self.audit_state(state, sysm, exc.lam)
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
    parser.add_argument("--method", choices=["NR", "mNR", "hybrid", "initial"], default="NR")
    parser.add_argument("--max-iterations", type=int, default=30)
    parser.add_argument(
        "--elastic-interfaces",
        action="store_true",
        help="diagnostic reference only: suppress interface slip/opening",
    )
    parser.add_argument(
        "--audit", action="store_true", help="sample Jacobians, K_ff and stress probes"
    )
    parser.add_argument(
        "--excavation-factor",
        type=float,
        default=1.0,
        help="common excavation load factor for mesh comparisons (0 < value <= 1)",
    )
    parser.add_argument(
        "--soil-tension",
        type=float,
        default=None,
        help="explicit soil tensile strength [kPa]; omitted means no Rankine flow",
    )
    parser.add_argument("--rankine-at-apex", action="store_true")
    parser.add_argument(
        "--apex-stiffness-ratio",
        type=float,
        default=0.0,
        help="optional approximate apex iteration stiffness; 0 keeps exact tangent",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not np.isfinite(args.size) or args.size <= 0:
        parser.error("--size must be finite and positive")
    if not 0 < args.excavation_factor <= 1:
        parser.error("--excavation-factor must be in (0, 1]")
    if args.max_iterations < 1:
        parser.error("--max-iterations must be positive")
    if args.rankine_at_apex and args.soil_tension is not None:
        parser.error("choose either --rankine-at-apex or --soil-tension")
    if not 0 <= args.apex_stiffness_ratio <= 1:
        parser.error("--apex-stiffness-ratio must be in [0, 1]")
    if args.soil_tension is not None and (
        not np.isfinite(args.soil_tension) or args.soil_tension < 0
    ):
        parser.error("--soil-tension must be finite and nonnegative")
    m = model(
        args.size,
        mixed=args.mixed,
        gauss_order=args.gauss_order,
        soil_tension=args.soil_tension,
        rankine_at_apex=args.rankine_at_apex,
    )
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
    m = replace(
        m,
        settings=replace(
            m.settings,
            method=args.method,
            max_iter=args.max_iterations,
            apex_stiffness_ratio=args.apex_stiffness_ratio,
        ),
    )
    if args.elastic_interfaces:
        m = replace(
            m,
            interfaces={
                k: replace(v, c=1e20, phi=0.0, psi=0.0, sig_t=1e20) for k, v in m.interfaces.items()
            },
        )
    m = replace(
        m,
        stages=[
            replace(s, load_split=args.excavation_factor) if s.name == "excavate" else s
            for s in m.stages
        ],
    )
    solver = DiagnosticSolver(m, audit=args.audit)
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
    report.update(
        material_failure_first=solver.material_failure_first,
        material_failure_last=solver.material_failure_last,
    )
    if args.audit:
        quality = mesh_quality(m.mesh)
        report.update(
            audits=solver.audits,
            jacobians=jacobian_report(m.mesh, args.gauss_order),
            settings=asdict(m.settings),
            materials={k: {"model": v.model, "params": v.params} for k, v in m.materials.items()},
            point_load_count=sum(
                isinstance(load, api.PointLoad) for s in m.stages for load in s.loads
            ),
            fixities=[
                {
                    "node_set": f.node_set,
                    "nodes": len(m.mesh.nodes(f.node_set)),
                    "ux": f.ux,
                    "uy": f.uy,
                    "rz": f.rz,
                }
                for f in m.fixities
            ],
            geometry_quality={
                "min_angle": quality.min_angle,
                "max_aspect": quality.max_aspect,
                "triangles": quality.n_triangles,
                "quads": quality.n_quads,
            },
        )
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(
        json.dumps({k: v for k, v in report.items() if k not in ("history", "histories")}, indent=2)
    )
    return 0 if report["converged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

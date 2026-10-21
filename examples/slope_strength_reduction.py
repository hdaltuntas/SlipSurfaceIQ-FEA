"""P4 slope with an explicit, optional associated Rankine flow at the MC apex.

PYTHONPATH=src python examples/slope_strength_reduction.py --rankine-at-apex
Add --apex-stiffness-ratio 1e-6 to try the approximate Newton matrix separately.
The legacy model without Rankine flow may raise a local-return error. A solver
nonconvergence bracket is not by itself a validated physical collapse factor.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np

from slipsurface.fe2d import api
from slipsurface.fe2d.core.errors import MaterialIntegrationError
from slipsurface.fe2d.mesh import Domain, unstructured_mesh


def model(h=1.5, *, rankine_at_apex=False, apex_stiffness_ratio=0.0):
    domain = Domain().add_polygon(
        [(0, 0), (40, 0), (40, 10), (20, 10)],
        edge_names=["base", "right", "crest", "face"],
    )
    return api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=unstructured_mesh(domain, h=h),
        materials={
            "soil": api.MaterialSpec.mohr_coulomb(
                "soil", 1e5, 0.3, 10, 20, 0, gamma=20, rankine_at_apex=rankine_at_apex
            )
        },
        region_material={1: "soil"},
        fixities=(api.Fixity("base", True, True), api.Fixity("right", True, False)),
        initial=api.InitialStress("gravity"),
        settings=api.SolverSettings(apex_stiffness_ratio=apex_stiffness_ratio),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=float, default=1.5)
    parser.add_argument("--rankine-at-apex", action="store_true")
    parser.add_argument("--apex-stiffness-ratio", type=float, default=0.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not np.isfinite(args.size) or args.size <= 0:
        parser.error("--size must be positive and finite")
    if not 0 <= args.apex_stiffness_ratio <= 1:
        parser.error("--apex-stiffness-ratio must be in [0, 1]")
    m = model(
        args.size,
        rankine_at_apex=args.rankine_at_apex,
        apex_stiffness_ratio=args.apex_stiffness_ratio,
    )
    report = {
        "size": args.size,
        "nodes": m.mesh.nn,
        "params": m.materials["soil"].params,
        "settings": asdict(m.settings),
    }
    try:
        result = api.strength_reduction(m)
        report.update(
            factor=result.factor,
            F_failed=result.F_failed,
            trials=[asdict(t) for t in result.trials],
        )
    except MaterialIntegrationError as exc:
        report.update(error=str(exc), material_failure=exc.details)
    text = json.dumps(report, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 1 if "error" in report else 0


if __name__ == "__main__":
    raise SystemExit(main())

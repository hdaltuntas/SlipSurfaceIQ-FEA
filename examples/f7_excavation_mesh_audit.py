"""F7 staged excavation mesh-sensitivity audit (optional, not CI-gated).

Run from the repository root after installing the desktop requirements:

    python examples/f7_excavation_mesh_audit.py --output-dir f7_audit

Rebuilds the documented pile/anchor excavation at three mesh scales, using
the same stage and material definitions. Emits JSON and CSV with stage-wise
displacements, reaction resultants, plastic Gauss-point counts, and nonlinear
step histories. Failed solves are recorded, not silently discarded.

This is a *numerical sensitivity study*, not an independent RS2 result. Do not
interpret mesh-to-mesh agreement alone as proof of engineering correctness.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import replace
from pathlib import Path

import numpy as np

from slipsurface.fe2d import api
from slipsurface.fe2d.cad.geometry import Drawing
from slipsurface.fe2d.gui.demo import excavation_model
from slipsurface.fe2d.gui.mesh_quality import mesh_quality_report


def build_case(base, h: float):
    """Regenerate geometry and supports, then retain identical study parameters."""
    if not math.isfinite(h) or h <= 0:
        raise ValueError("Mesh target h must be finite and positive.")
    drawing = Drawing.from_dict(base.geometry)
    rebuilt = replace(drawing, h=h).build_model()
    model = replace(
        rebuilt,
        materials=base.materials,
        region_material=base.region_material,
        initial=base.initial,
        stages=base.stages,
        settings=base.settings,
    )
    model.validate()
    return model


def finite_max_displacement(stage) -> float:
    magnitude = np.linalg.norm(stage.u, axis=1)
    finite = magnitude[np.isfinite(magnitude)]
    return float(finite.max()) if finite.size else 0.0


def maximum_finite_magnitude(arrays) -> float:
    """Peak absolute finite structural result; ignores inactive NaN elements."""
    valid = [np.abs(a[np.isfinite(a)]) for a in arrays]
    return max((float(x.max()) for x in valid if x.size), default=0.0)


def stage_metrics(stage, h: float, nodes: int, elements: int) -> dict:
    plastic_gp = sum(int(np.count_nonzero(x)) for x in stage.plastic.values())
    beam_moments = maximum_finite_magnitude(
        [force[..., 2] for force in stage.beams.values()]
    )
    bar_forces = maximum_finite_magnitude(list(stage.bars.values()))
    history = stage.history
    accepted = [step for step in history.steps if step.converged] if history else []
    rejected = [step for step in history.steps if not step.converged] if history else []
    last_residual = (
        float(accepted[-1].residuals[-1])
        if accepted and accepted[-1].residuals else None
    )
    return {
        "h_m": h,
        "nodes": nodes,
        "elements": elements,
        "stage": stage.name,
        "max_displacement_m": finite_max_displacement(stage),
        "reaction_fx_kn_per_m": float(np.sum(stage.reactions[:, 0])),
        "reaction_fy_kn_per_m": float(np.sum(stage.reactions[:, 1])),
        "active_plastic_gauss_points": plastic_gp,
        "max_abs_beam_moment": beam_moments,
        "max_abs_bar_axial_force": bar_forces,
        "load_factor": float(stage.lam),
        "accepted_steps": len(accepted),
        "rejected_steps": len(rejected),
        "newton_iterations": history.n_iterations if history else 0,
        "last_accepted_residual": last_residual,
    }


def run_audit(sizes: tuple[float, ...]) -> tuple[list[dict], list[dict]]:
    base = excavation_model()
    rows: list[dict] = []
    failures: list[dict] = []
    for h in sizes:
        try:
            model = build_case(base, h)
            quality = mesh_quality_report(model.mesh)
            if quality.nonpositive_jacobian_elements:
                raise ValueError(
                    f"{quality.nonpositive_jacobian_elements} invalid Jacobian elements"
                )
            result = api.run(model)
            elements = sum(block.ne for block in model.mesh.continuum_blocks())
            rows.extend(
                stage_metrics(stage, h, model.mesh.nn, elements)
                for stage in result.stages
            )
        except Exception as exc:
            failures.append({"h_m": h, "type": type(exc).__name__, "detail": str(exc)})
    return rows, failures


def attach_mesh_differences(rows: list[dict]) -> list[dict]:
    """Consecutive relative changes are diagnostics, not acceptance tolerances."""
    previous: dict[str, float] = {}
    for row in rows:
        value = float(row["max_displacement_m"])
        prior = previous.get(row["stage"])
        row["relative_displacement_change"] = (
            abs(value - prior) / max(abs(value), abs(prior), 1e-12)
            if prior is not None else None
        )
        previous[row["stage"]] = value
    return rows


def write_audit(output: Path, sizes: tuple[float, ...]) -> int:
    output.mkdir(parents=True, exist_ok=True)
    rows, failures = run_audit(sizes)
    attach_mesh_differences(rows)
    with (output / "excavation_mesh_audit.csv").open("w", newline="", encoding="utf-8") as file:
        if rows:
            writer = csv.DictWriter(file, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    report = {
        "case": "RS2-inspired pile/anchor staged excavation (native demo)",
        "mesh_sizes_m": list(sizes),
        "results": rows,
        "failures": failures,
        "warning": (
            "Convergence and mesh sensitivity are not independent physical validation; "
            "review reactions, excavation loads, beam forces and external benchmarks."
        ),
    }
    (output / "excavation_mesh_audit.json").write_text(
        json.dumps(report, indent=2, allow_nan=False), encoding="utf-8"
    )
    return 1 if failures or not rows else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sizes", type=float, nargs="+", default=[2.5, 1.8, 1.2],
        help="Mesh target sizes (metres), coarse to fine",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("f7_audit"))
    args = parser.parse_args()
    if len(args.sizes) < 3 or len(set(args.sizes)) != len(args.sizes):
        parser.error("Specify at least three distinct mesh sizes.")
    if any(not math.isfinite(size) or size <= 0 for size in args.sizes):
        parser.error("Mesh sizes must be finite and positive.")
    return write_audit(args.output_dir, tuple(args.sizes))


if __name__ == "__main__":
    raise SystemExit(main())

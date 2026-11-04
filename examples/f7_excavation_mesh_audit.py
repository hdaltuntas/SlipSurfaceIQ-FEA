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
from slipsurface.fe2d.post.balance_acceptance import summarize_balances
from slipsurface.fe2d.post.dry_load_balance import dry_stage_load_balance_by_stage
from slipsurface.fe2d.post.excavation_coverage import excavation_audit_coverage
from slipsurface.fe2d.post.excavation_balance import excavation_balance_by_stage
from slipsurface.fe2d.post.global_balance import gravity_equilibrium_by_stage
from slipsurface.fe2d.post.interface_balance import stage_interface_pairs
from slipsurface.fe2d.post.interface_nodal_audit import stage_interface_nodal_audit
from slipsurface.fe2d.post.stage_interface_moment import stage_effective_interface_moment_audit
from slipsurface.fe2d.post.support_audit import compare_profiles, sample_support_profile
from slipsurface.fe2d.post.support_coverage_acceptance import support_coverage_acceptance
from slipsurface.fe2d.post.support_result_coverage import stage_support_result_coverage


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


def support_force_metrics(stage) -> dict:
    """Peak structural response per tag, preserving the engineering identity.

    No nonzero value is fabricated for an inactive or absent support.
    """
    return {
        "beam_moments": {
            tag: maximum_finite_magnitude([force[..., 2]])
            for tag, force in sorted(stage.beams.items())
        },
        "bar_axial_forces": {
            tag: maximum_finite_magnitude([force])
            for tag, force in sorted(stage.bars.items())
        },
    }


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


def compare_supports_by_stage(rows: list[dict]) -> list[dict]:
    """Compare structural forces between successive meshes at the same stage.

    An absent support does not mean zero force: it is an activation or
    data-coverage mismatch and must be visible in the audit.
    """
    previous: dict[str, dict] = {}
    output: list[dict] = []
    for row in rows:
        name = row["stage"]
        support = row.get("supports", {"beam_moments": {}, "bar_axial_forces": {}})
        before = previous.get(name)
        if before is not None:
            for kind in ("beam_moments", "bar_axial_forces"):
                earlier = before.get(kind, {})
                current = support.get(kind, {})
                for tag in sorted(set(earlier) | set(current)):
                    first, second = earlier.get(tag), current.get(tag)
                    change = (
                        abs(second - first) / max(abs(first), abs(second), 1e-12)
                        if first is not None and second is not None else None
                    )
                    output.append({
                        "stage": name, "h_m": row["h_m"],
                        "kind": kind, "tag": tag,
                        "previous_peak": first, "current_peak": second,
                        "relative_change": change,
                        "status": "compared" if change is not None else "missing",
                    })
        previous[name] = support
    return output


def stage_support_profiles(model, stage, count=51, *, signed=False):
    """Profiles for supports present in this stage; inactive supports are omitted."""
    drawing = Drawing.from_dict(model.geometry)
    entities = {entity.name: entity for entity in drawing.entities}
    profiles = {}
    for assignment in drawing.supports:
        tag = assignment.tag
        kind = "bar" if assignment.kind == "bolt" else "beam"
        available = stage.bars if kind == "bar" else stage.beams
        if tag not in available:
            continue
        entity = entities[assignment.entity]
        profile = sample_support_profile(
            model.mesh, stage, tag,
            (entity.points[0], entity.points[-1]),
            kind=kind, count=count, signed=signed,
        )
        profiles[tag] = profile
    return profiles


def stage_signed_profiles(model, stage, count=51):
    """Signed outputs are opt-in per support; report invalid local orientations."""
    drawing = Drawing.from_dict(model.geometry)
    entities = {entity.name: entity for entity in drawing.entities}
    valid, errors = {}, {}
    for assignment in drawing.supports:
        tag = assignment.tag
        kind = "bar" if assignment.kind == "bolt" else "beam"
        sources = stage.bars if kind == "bar" else stage.beams
        if tag not in sources:
            continue
        entity = entities[assignment.entity]
        try:
            valid[tag] = sample_support_profile(
                model.mesh, stage, tag,
                (entity.points[0], entity.points[-1]),
                kind=kind, count=count, signed=True,
            )
        except ValueError as exc:
            errors[tag] = str(exc)
    return valid, errors


def compare_stage_profiles(rows, field="profiles"):
    """Return differences for each stage and support between successive meshes."""
    previous = {}
    comparisons = []
    for row in rows:
        stage = row["stage"]
        current = row.get(field, {})
        old = previous.get(stage)
        if old is not None:
            for tag in sorted(set(old) | set(current)):
                before, after = old.get(tag), current.get(tag)
                comparisons.append({
                    "stage": stage,
                    "h_m": row["h_m"],
                    "tag": tag,
                    "relative_rms_components": (
                        compare_profiles(before, after)
                        if before is not None and after is not None else None
                    ),
                    "status": (
                        "compared" if before is not None and after is not None
                        else "missing"
                    ),
                })
        previous[stage] = current
    return comparisons


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
            gravity_balances = gravity_equilibrium_by_stage(model, result)
            dry_load_balances = dry_stage_load_balance_by_stage(model, result)
            excavation_balances = excavation_balance_by_stage(model, result)
            elements = sum(block.ne for block in model.mesh.continuum_blocks())
            for index, stage in enumerate(result.stages):
                metrics = stage_metrics(stage, h, model.mesh.nn, elements)
                metrics["gravity_balance"] = gravity_balances[index]
                metrics["dry_load_balance"] = dry_load_balances[index]
                metrics["excavation_balance"] = excavation_balances[index]
                metrics["supports"] = support_force_metrics(stage)
                metrics["support_result_coverage"] = stage_support_result_coverage(
                    model, stage, model.stages[index].active_structures,
                )
                metrics["interface_pairs"] = stage_interface_pairs(model, stage)
                metrics["interface_nodal_transfer"] = stage_interface_nodal_audit(model, stage)
                metrics["interface_moment_transfer"] = stage_effective_interface_moment_audit(
                    model, stage,
                )
                metrics["profiles"] = stage_support_profiles(model, stage)
                signed, errors = stage_signed_profiles(model, stage)
                metrics["signed_profiles"] = signed
                metrics["signed_profile_errors"] = errors
                rows.append(metrics)
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


def base_stages():
    """Canonical expected stages, independent of which meshes solve."""
    return excavation_model().stages


def write_audit(output: Path, sizes: tuple[float, ...]) -> int:
    output.mkdir(parents=True, exist_ok=True)
    rows, failures = run_audit(sizes)
    attach_mesh_differences(rows)
    comparisons = compare_supports_by_stage(rows)
    profile_comparisons = compare_stage_profiles(rows)
    signed_comparisons = compare_stage_profiles(rows, field="signed_profiles")
    (output / "excavation_force_distributions.json").write_text(
        json.dumps({
            "profiles": [
                {"stage": row["stage"], "h_m": row["h_m"],
                 "supports": row.get("profiles", {})}
                for row in rows
            ],
            "comparisons": profile_comparisons,
            "signed_comparisons": signed_comparisons,
            "signed_profiles": [
                {"stage": row["stage"], "h_m": row["h_m"],
                 "supports": row.get("signed_profiles", {}),
                 "errors": row.get("signed_profile_errors", {})}
                for row in rows
            ],
        }, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    with (output / "excavation_support_comparison.csv").open(
        "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(
            file, fieldnames=[
                "stage", "h_m", "kind", "tag", "previous_peak",
                "current_peak", "relative_change", "status",
            ],
        )
        writer.writeheader()
        writer.writerows(comparisons)
    with (output / "excavation_mesh_audit.csv").open("w", newline="", encoding="utf-8") as file:
        if rows:
            nested = {
                "supports", "profiles", "signed_profiles", "signed_profile_errors",
                "interface_pairs", "interface_nodal_transfer",
                "interface_moment_transfer",
                "support_result_coverage",
                "gravity_balance", "dry_load_balance", "excavation_balance",
            }
            fieldnames = [field for field in rows[0] if field not in nested]
            writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    balance_summary = {
        key: summarize_balances([row[key] for row in rows])
        for key in ("gravity_balance", "dry_load_balance", "excavation_balance")
    }
    expected_stages = tuple(stage.name for stage in base_stages())
    coverage = excavation_audit_coverage(rows, failures, sizes, expected_stages)
    support_acceptance = support_coverage_acceptance(rows, sizes, expected_stages)
    report = {
        "mesh_stage_coverage": coverage,
        "support_coverage_acceptance": support_acceptance,
        "force_balance_acceptance": balance_summary,
        "excavation_balance": [
            {"stage": row["stage"], "h_m": row["h_m"],
             **row.get("excavation_balance", {})}
            for row in rows
        ],
        "dry_load_balance": [
            {"stage": row["stage"], "h_m": row["h_m"],
             **row.get("dry_load_balance", {})}
            for row in rows
        ],
        "gravity_balance": [
            {"stage": row["stage"], "h_m": row["h_m"],
             **row.get("gravity_balance", {})}
            for row in rows
        ],
        "support_result_coverage": [
            {"stage": row["stage"], "h_m": row["h_m"],
             **row["support_result_coverage"]}
            for row in rows
        ],
        "interface_nodal_transfer": [
            {"stage": row["stage"], "h_m": row["h_m"],
             "interfaces": row.get("interface_nodal_transfer", {})}
            for row in rows
        ],
        "interface_moment_transfer": [
            {"stage": row["stage"], "h_m": row["h_m"],
             "interfaces": row.get("interface_moment_transfer", {})}
            for row in rows
        ],
        "interface_force_pairs": [
            {"stage": row["stage"], "h_m": row["h_m"],
             "interfaces": row.get("interface_pairs", {})}
            for row in rows
        ],
        "case": "RS2-inspired pile/anchor staged excavation (native demo)",
        "mesh_sizes_m": list(sizes),
        "results": rows,
        "support_comparisons": comparisons,
        "profile_comparisons": profile_comparisons,
        "signed_comparisons": signed_comparisons,
        "failures": failures,
        "warning": (
            "Convergence and mesh sensitivity are not independent physical validation; "
            "review reactions, excavation loads, beam forces and external benchmarks."
        ),
    }
    (output / "excavation_mesh_audit.json").write_text(
        json.dumps(report, indent=2, allow_nan=False), encoding="utf-8"
    )
    return 0 if (coverage["complete"] and support_acceptance["status"] == "passed") else 1


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

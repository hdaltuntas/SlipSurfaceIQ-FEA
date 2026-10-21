"""Export the explicit Rankine-apex S4 case and measure load-path discretization.

PYTHONPATH=src python examples/verify_sheet_pile.py --mixed --study --output /tmp/s4
Exports raw signed beam end forces (without averaging), wall displacements, full
model JSON and a mesh-independent physical case description for an external solver.
No external reference is bundled; these runs cannot by themselves close S4.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
from sheet_pile_staged_excavation import (
    DOMAIN_POINTS,
    EXCAVATION_POINTS,
    WALL_POINTS,
    model,
)

from slipsurface.fe2d import api
from slipsurface.fe2d.fem.static import StaticSolver
from slipsurface.fe2d.io import model_to_dict


def physical_case(m):
    """Only physical inputs; numerical settings and mesh belong in model.json."""
    doc = model_to_dict(m, include_mesh=False)
    # The JSON loader represents material parameters numerically (including flags).
    # Canonical types keep the physical identity stable across save/load.
    for material in doc["materials"].values():
        material["params"] = {
            k: bool(v) if k == "rankine_at_apex" else float(v)
            for k, v in material["params"].items()
        }
    stages = []
    for stage in doc["stages"]:
        physical = {k: v for k, v in stage.items() if k not in ("name", "load_split")}
        if not stages or physical != stages[-1]:
            stages.append(physical)
    wall = next(b for b in m.mesh.blocks if b.tag == "pile")
    continuum = [
        b
        for b in m.mesh.blocks
        if b.etype in (api.ElemType.T3, api.ElemType.T6, api.ElemType.Q4, api.ElemType.Q8)
    ]
    common = np.intersect1d(
        np.unique(wall.conn), np.unique(np.concatenate([b.conn.ravel() for b in continuum]))
    )
    closed_tips = {}
    for block in m.mesh.blocks:
        if block.tag in m.interfaces:
            count = block.conn.shape[1] // 2
            first, second = block.conn[:, :count], block.conn[:, count:]
            same = np.unique(first[first == second])
            closed_tips[block.tag] = m.mesh.coords[same].tolist()
    return {
        "schema_version": 1,
        "case": "S4-dry-cantilever-rankine-apex-v1",
        "units": {"length": "m", "force": "kN/m", "moment": "kN m/m", "stress": "kPa"},
        "coordinates": "x right, y up; depth=-y; unit width out of plane",
        "geometry": {
            "domain": DOMAIN_POINTS,
            "excavation": EXCAVATION_POINTS,
            "wall": WALL_POINTS,
        },
        "wall_soil_shared_points_m": m.mesh.coords[common].tolist(),
        "closed_interface_points_m": closed_tips,
        **{k: v for k, v in doc.items() if k not in ("schema_version", "settings", "stages")},
        "stages": stages,
        # Split runs release the same excavation in two numerical stages, not two lifts.
        "physical_sequence": [
            "K0 initial stress; interfaces initially present, wall absent",
            "activate stress-free wall with both interfaces; no installation disturbance",
            "remove right-hand region 2 to y=-5 m; fully release excavation imbalance",
        ],
        "apex_flow": "MC psi=0 plus associated Rankine flow at c*cot(phi)=0 kPa",
        "wall_signs": (
            "raw local end sections: -T*f at end 0, +T*f at end 1; "
            "local axial direction node0->node1, transverse=(-s,c), N tension positive; "
            "for this vertical wall M_up=local_s*M uses a common upward axis"
        ),
    }


def case_hash(case):
    payload = json.dumps(case, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def wall_tables(m, stage):
    """Keep both end values at a shared node; force jumps must remain visible."""
    block = next(b for b in m.mesh.blocks if b.tag == "pile")
    ids = np.flatnonzero(stage.active[block.tag])
    nodes = np.unique(block.conn[ids])
    end_rows, node_rows = [], []
    for e in ids:
        n0, n1 = block.conn[e]
        direction = m.mesh.coords[n1] - m.mesh.coords[n0]
        c, s = direction / np.linalg.norm(direction)
        if abs(c) > 1e-12:
            raise ValueError("S4 export requires a vertical wall for the upward moment convention")
        for end, node in enumerate((n0, n1)):
            n, v, moment = stage.beams[block.tag][e, end]
            end_rows.append(
                {
                    "element": int(e),
                    "end": end,
                    "node": int(node),
                    "depth_m": float(-m.mesh.coords[node, 1]),
                    "local_c": float(c),
                    "local_s": float(s),
                    "N_kN_per_m": float(n),
                    "V_kN_per_m": float(v),
                    "M_kNm_per_m": float(moment),
                    "M_up_kNm_per_m": float(s * moment),
                }
            )
    for node in nodes:
        node_rows.append(
            {
                "node": int(node),
                "depth_m": float(-m.mesh.coords[node, 1]),
                "ux_m": float(stage.u[node, 0]),
                "uy_m": float(stage.u[node, 1]),
                "rotation_rad": float(stage.rotation[node]),
            }
        )
    if not end_rows or not all(
        np.isfinite(list(row.values())).all() for row in (*end_rows, *node_rows)
    ):
        raise ValueError("wall output must contain finite active end forces and displacements")
    return (
        sorted(end_rows, key=lambda r: (r["depth_m"], r["element"], r["end"])),
        sorted(node_rows, key=lambda r: r["depth_m"]),
    )


def _write_json(path, doc):
    path.write_text(json.dumps(doc, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def export_run(m, output, *, save_project=False):
    """A failed solve propagates; it never emits a successful final result."""
    output = Path(output)
    # Prevent stale success files from a previous attempt being mistaken for this run.
    output.mkdir(parents=True, exist_ok=False)
    case = physical_case(m)
    _write_json(output / "case.json", case)
    _write_json(output / "model.json", model_to_dict(m))
    solver = StaticSolver(m)
    result = solver.run()
    if result.last.lam != 1.0:
        raise ValueError("comparison requires a fully completed final stage")
    for tag, flags in result.last.plastic.items():
        if np.any(flags[result.last.active[tag]] == 255):
            raise ValueError("invalid material flag in accepted result")
    ends, nodes = wall_tables(m, result.last)
    peak = max(ends, key=lambda r: abs(r["M_kNm_per_m"]))
    _, fint = solver.integrate_committed(solver.state, solver.system, solver._layout)
    fext = solver.external_force(solver.system, solver._ctx)
    residual = fext - fint
    steps = [step for stage in result.stages for step in stage.history.steps]
    summary = {
        "case_sha256": case_hash(case),
        "external_reference_status": "pending",
        "completed": True,
        "lambda": result.last.lam,
        "nodes": m.mesh.nn,
        "settings": model_to_dict(m, include_mesh=False)["settings"],
        "stages": [{"name": s.name, "lambda": s.lam} for s in result.stages],
        "max_abs_moment_kNm_per_m": abs(peak["M_kNm_per_m"]),
        "peak_moment_depth_m": peak["depth_m"],
        "max_abs_wall_ux_m": max(abs(r["ux_m"]) for r in nodes),
        "wall_top_ux_m": nodes[0]["ux_m"],
        "wall_toe_ux_m": nodes[-1]["ux_m"],
        "max_domain_displacement_norm_m": float(np.nanmax(np.linalg.norm(result.last.u, axis=1))),
        "free_residual_l2": float(np.linalg.norm(residual[solver.system.dm.free])),
        "external_force_l2": float(np.linalg.norm(fext)),
        "accepted_steps": sum(s.converged for s in steps),
        "rejected_steps": sum(not s.converged for s in steps),
        "material_return_rejected_steps": sum(s.termination == "material_return" for s in steps),
        "iterations": sum(s.iterations for s in steps),
    }
    _write_csv(output / "wall-end-forces.csv", ends)
    _write_csv(output / "wall-displacements.csv", nodes)
    if save_project:
        api.save_project(m, output / "result.ssproj", results=result)
    _write_json(output / "summary.json", summary)
    print(json.dumps({"output": str(output), **summary}), flush=True)
    return summary, ends, nodes


def compare_runs(reference, other):
    """Same-mesh numerical sensitivity, not an independent S4 comparison."""
    ref, ref_ends, ref_nodes = reference
    out, ends, nodes = other
    if ref["case_sha256"] != out["case_sha256"]:
        raise ValueError("physical cases differ")
    for a, b, keys in (
        (ref_ends, ends, ("node", "element", "end", "depth_m", "local_c", "local_s")),
        (ref_nodes, nodes, ("node", "depth_m")),
    ):
        if len(a) != len(b) or any(any(x[k] != y[k] for k in keys) for x, y in zip(a, b)):
            raise ValueError("sensitivity comparison requires identical wall sampling")
    moment_scale = ref["max_abs_moment_kNm_per_m"]
    ux_scale = ref["max_abs_wall_ux_m"]
    if min(moment_scale, ux_scale) <= 0:
        raise ValueError("nonzero reference response required for relative differences")
    return {
        "relative_peak_moment_change": abs(out["max_abs_moment_kNm_per_m"] - moment_scale)
        / moment_scale,
        "relative_moment_field_change": max(
            abs(a["M_kNm_per_m"] - b["M_kNm_per_m"]) for a, b in zip(ref_ends, ends)
        )
        / moment_scale,
        "relative_wall_ux_field_change": max(
            abs(a["ux_m"] - b["ux_m"]) for a, b in zip(ref_nodes, nodes)
        )
        / ux_scale,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=float, default=0.5)
    parser.add_argument("--mixed", action="store_true")
    parser.add_argument(
        "--study", action="store_true", help="also halve step sizes and split release"
    )
    parser.add_argument("--output", type=Path, required=True, help="new output directory")
    parser.add_argument("--save-project", action="store_true")
    args = parser.parse_args()
    if not np.isfinite(args.size) or not 0 < args.size <= 1.5:
        parser.error("size must be finite and in (0, 1.5] m")
    if args.output.exists():
        parser.error("output directory already exists; choose a new path")
    m = model(args.size, mixed=args.mixed, gauss_order="high", rankine_at_apex=True)
    reference = export_run(m, args.output / "baseline", save_project=args.save_project)
    if args.study:
        variants = {
            "half-steps": replace(m, settings=replace(m.settings, dlam0=0.05, dlam_max=0.25)),
            "split-release": replace(
                m,
                stages=[
                    m.stages[0],
                    replace(m.stages[1], name="half-release", load_split=0.5),
                    replace(m.stages[1], name="complete-release"),
                ],
            ),
        }
        study = {}
        for name, variant in variants.items():
            other = export_run(variant, args.output / name, save_project=args.save_project)
            study[name] = compare_runs(reference, other)
        _write_json(args.output / "sensitivity.json", study)
        print(json.dumps(study), flush=True)


if __name__ == "__main__":
    main()

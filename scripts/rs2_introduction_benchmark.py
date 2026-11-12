"""Reproduce the official RS2 Introduction / Surface Excavation tutorial.

This is an external tutorial benchmark: the geometry, material, stages, load and
published approximate maximum displacements come from Rocscience documentation.
The script runs three SlipSurface mesh levels and reports results; characterization
mode does not claim a pass before the numerical differences have been reviewed.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from slipsurface.fe2d import api  # noqa: E402
from slipsurface.fe2d.examples.validation import rs2_introduction_model  # noqa: E402
from slipsurface.fe2d.mesh import mesh_quality  # noqa: E402

SOURCE_URL = "https://www.rocscience.com/help/rs2/tutorials/introduction"
LEGACY_SOURCE_URL = "https://www.rocscience.com/downloads/phase2/Phase2_TutorialManual.pdf"
PUBLISHED_MAX_MM = (3.0, 4.7, 18.0)
PUBLISHED_RELATIVE_LIMIT = 0.05
MESH_CONVERGENCE_LIMIT = 0.02
MESH_LEVELS = {
    "coarse": (0.35, 1.20),
    "medium": (0.25, 0.85),
    "fine": (0.18, 0.60),
}


def build_model(h_min: float, h_max: float) -> api.Model:
    return rs2_introduction_model(h_min, h_max)


def _stage_max(stage, coords: np.ndarray) -> dict:
    valid = np.isfinite(stage.u[:, 0]) & np.isfinite(stage.u[:, 1])
    if not np.any(valid):
        raise RuntimeError(f"stage {stage.name!r} has no active displacement results")
    ids = np.flatnonzero(valid)
    mag = np.linalg.norm(stage.u[ids, :2], axis=1)
    local = int(np.argmax(mag))
    node = int(ids[local])
    return {
        "name": stage.name,
        "max_total_displacement_mm": float(mag[local] * 1000.0),
        "max_node": node,
        "max_xy_m": [float(v) for v in coords[node]],
        "ux_mm": float(stage.u[node, 0] * 1000.0),
        "uy_mm": float(stage.u[node, 1] * 1000.0),
    }


def run_level(name: str, h_min: float, h_max: float) -> dict:
    model = build_model(h_min, h_max)
    result = api.run(model)
    stages = [_stage_max(stage, model.mesh.coords) for stage in result.stages]
    for stage, target in zip(stages, PUBLISHED_MAX_MM):
        stage["rs2_published_approx_mm"] = target
        stage["relative_difference"] = abs(stage["max_total_displacement_mm"] - target) / target
    quality = mesh_quality(model.mesh)
    return {
        "level": name,
        "h_min_m": h_min,
        "h_max_m": h_max,
        "nodes": model.mesh.nn,
        "continuum_elements": int(sum(block.ne for block in model.mesh.continuum_blocks())),
        "mesh_quality": {
            "min_angle_deg": quality.min_angle,
            "mean_min_angle_deg": quality.mean_min_angle,
            "max_aspect": quality.max_aspect,
            "n_triangles": quality.n_triangles,
            "n_quads": quality.n_quads,
        },
        "stages": stages,
    }


def _distance_to_trench_boundary(x: float, y: float) -> float:
    if 4.5 <= x <= 6.5:
        vertical = min(abs(y + 1.0), abs(y - 4.0))
    else:
        vertical = min(math.hypot(x - 4.5, y + 1.0), math.hypot(x - 6.5, y + 1.0))
    if -1.0 <= y <= 4.0:
        horizontal = min(abs(x - 4.5), abs(x - 6.5))
    else:
        horizontal = min(math.hypot(x - 4.5, y - 4.0), math.hypot(x - 6.5, y - 4.0))
    return min(vertical, horizontal)


def _location_checks(stages: list[dict]) -> dict:
    p1, p2, p3 = (stage["max_xy_m"] for stage in stages)
    return {
        "stage1_tunnel_bottom": math.hypot(p1[0], p1[1] + 1.0) <= 0.25,
        "stage2_on_trench_boundary": _distance_to_trench_boundary(*p2) <= 0.15,
        "stage3_below_surface_load": abs(p3[0]) <= 1.1 and abs(p3[1] - 4.0) <= 0.15,
    }


def benchmark(levels: tuple[str, ...]) -> dict:
    runs = [run_level(name, *MESH_LEVELS[name]) for name in levels]
    finest = runs[-1]
    target_checks = {
        stage["name"]: stage["relative_difference"] <= PUBLISHED_RELATIVE_LIMIT
        for stage in finest["stages"]
    }
    convergence_checks = {}
    if len(runs) >= 2:
        previous = runs[-2]
        for old, new in zip(previous["stages"], finest["stages"]):
            denominator = max(abs(new["max_total_displacement_mm"]), 1e-12)
            change = abs(new["max_total_displacement_mm"] - old["max_total_displacement_mm"])
            convergence_checks[new["name"]] = change / denominator <= MESH_CONVERGENCE_LIMIT
    location_checks = _location_checks(finest["stages"])
    acceptance = all(target_checks.values()) and all(convergence_checks.values())
    acceptance = acceptance and all(location_checks.values())
    max_relative = max(stage["relative_difference"] for stage in finest["stages"])
    return {
        "schema": "slipsurface.external-benchmark.rs2-introduction.v1",
        "benchmark": "RS2 Introduction - Surface Excavation",
        "source_url": SOURCE_URL,
        "legacy_geometry_source_url": LEGACY_SOURCE_URL,
        "claim": "external_tutorial_reproduction_characterization",
        "locked_inputs": {
            "units": "m, kN, kPa",
            "domain": [[15.0, 4.0], [-10.0, 4.0], [-10.0, -8.0], [15.0, -8.0]],
            "tunnel": {"center_m": [0.0, 0.0], "radius_m": 1.0, "segments": 60},
            "trench": [[4.5, 4.0], [4.5, -1.0], [6.5, -1.0], [6.5, 4.0]],
            "material": {"E_kPa": 50000.0, "nu": 0.25, "gamma_kN_m3": 20.0},
            "field_stress": {"surface_y_m": 4.0, "k0_in_plane": 0.5, "k0_out_of_plane": 0.5},
            "surface_load": {"x_m": [-1.0, 1.0], "pressure_kPa": 200.0, "stage": 3},
            "stages": ["Excavate Tunnel", "Excavate Trench", "Surface Load"],
            "published_max_displacement_mm": list(PUBLISHED_MAX_MM),
        },
        "runs": runs,
        "acceptance": {
            "published_relative_limit": PUBLISHED_RELATIVE_LIMIT,
            "medium_to_fine_relative_change_limit": MESH_CONVERGENCE_LIMIT,
            "published_value_checks": target_checks,
            "mesh_convergence_checks": convergence_checks,
            "qualitative_location_checks": location_checks,
        },
        "finest_max_relative_difference": max_relative,
        "acceptance_status": "passed" if acceptance else "failed",
    }


def markdown(report: dict) -> str:
    lines = [
        "# RS2 Introduction benchmark",
        "",
        f"Status: **{report['acceptance_status'].upper()}**",
        "",
        "| Mesh | Nodes | Stage 1 (mm) | Stage 2 (mm) | Stage 3 (mm) |",
        "|---|---:|---:|---:|---:|",
    ]
    for run in report["runs"]:
        values = [stage["max_total_displacement_mm"] for stage in run["stages"]]
        lines.append(
            f"| {run['level']} | {run['nodes']} | "
            f"{values[0]:.5g} | {values[1]:.5g} | {values[2]:.5g} |"
        )
    lines.extend(
        [
            "",
            "Published RS2 approximate maxima: **3.0 mm, 4.7 mm, 18 mm**.",
            "",
            "Acceptance: each finest-mesh maximum within 5% of the published approximate value; "
            "medium-to-fine change within 2%; maximum locations must remain in the documented "
            "tunnel/trench/load regions.",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--levels",
        nargs="+",
        choices=tuple(MESH_LEVELS),
        default=("coarse", "medium", "fine"),
    )
    parser.add_argument("--json", dest="json_path", type=Path)
    parser.add_argument("--markdown", dest="markdown_path", type=Path)
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args(argv)
    report = benchmark(tuple(args.levels))
    payload = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    print(payload, end="")
    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(payload, encoding="utf-8")
    if args.markdown_path:
        args.markdown_path.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_path.write_text(markdown(report), encoding="utf-8")
    return 1 if args.require_pass and report["acceptance_status"] != "passed" else 0


if __name__ == "__main__":
    raise SystemExit(main())

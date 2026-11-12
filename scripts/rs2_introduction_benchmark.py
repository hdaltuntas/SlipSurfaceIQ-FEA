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
from slipsurface.fe2d.mesh import DistanceSize, Domain, circle, mesh_quality, unstructured_mesh  # noqa: E402

SOURCE_URL = "https://www.rocscience.com/help/rs2/tutorials/introduction"
LEGACY_SOURCE_URL = "https://www.rocscience.com/downloads/phase2/Phase2_TutorialManual.pdf"
PUBLISHED_MAX_MM = (3.0, 4.7, 18.0)
MESH_LEVELS = {
    "coarse": (0.35, 1.20),
    "medium": (0.25, 0.85),
    "fine": (0.18, 0.60),
}


def build_model(h_min: float, h_max: float) -> api.Model:
    outer = [
        (-10.0, -8.0),
        (15.0, -8.0),
        (15.0, 4.0),
        (6.5, 4.0),
        (4.5, 4.0),
        (1.0, 4.0),
        (-1.0, 4.0),
        (-10.0, 4.0),
    ]
    outer_edges = [
        "bottom",
        "right",
        "top_right",
        "trench_top",
        "top_middle",
        "surface_load",
        "top_left",
        "left",
    ]
    tunnel = circle(0.0, 0.0, 1.0, 60)
    trench = np.asarray(
        [(4.5, 4.0), (4.5, -1.0), (6.5, -1.0), (6.5, 4.0)],
        dtype=float,
    )

    domain = Domain()
    domain.add_polygon(outer, region=1, name="Till", edge_names=outer_edges)
    domain.add_polygon(tunnel, region=2, name="Tunnel")
    domain.add_polygon(trench, region=3, name="Trench")

    size = DistanceSize(
        h_min,
        h_max,
        1.25,
        lines=[np.asarray(tunnel), trench],
        closed=[True, True],
    )
    mesh = unstructured_mesh(domain, h=size)

    # RS2 tutorial is an elastic stress/deformation analysis. Its c/phi values are
    # used for the displayed strength-factor diagnostic, not for plastic yielding.
    till = api.MaterialSpec.elastic("Till", E=50000.0, nu=0.25, gamma=20.0)
    return api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"Till": till},
        region_material={1: "Till", 2: "Till", 3: "Till"},
        fixities=(
            api.Fixity("bottom", False, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        initial=api.InitialStress("k0_field", k0=0.5, surface_y=4.0),
        stages=[
            api.Stage("Excavate Tunnel", active_regions={1, 3}),
            api.Stage("Excavate Trench", active_regions={1}),
            api.Stage(
                "Surface Load",
                active_regions={1},
                loads=(api.EdgeLoad("surface_load", qn=200.0),),
            ),
        ],
    )


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


def benchmark(levels: tuple[str, ...]) -> dict:
    runs = [run_level(name, *MESH_LEVELS[name]) for name in levels]
    finest = runs[-1]
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
        "finest_max_relative_difference": max_relative,
        "acceptance_status": "characterization_pending_review",
    }


def markdown(report: dict) -> str:
    lines = [
        "# RS2 Introduction benchmark",
        "",
        "Status: **CHARACTERIZATION — acceptance tolerance not enabled yet**",
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
            "No pass is claimed until the reproduced values, peak locations and mesh trend are reviewed.",
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

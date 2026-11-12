"""Reproduce PLAXIS 2D Tutorial 01, Case A: rigid circular footing on sand.

Official tutorial facts used here:
- axisymmetric sand domain, radius 5 m and thickness 4 m;
- water level y=2 m;
- drained Mohr-Coulomb sand: gamma_unsat=17, gamma_sat=20 kN/m3,
  E=13000 kPa, nu=0.3, c=1 kPa, phi=30 deg, psi=0;
- rigid rough footing radius 1 m represented by prescribed ux=0 and uy=-0.05 m;
- K0 initial procedure;
- published total footing reaction about 588 kN at 50 mm indentation.

SlipSurface axisymmetric reactions are per radian, so the reported full circular
footing force is 2*pi times the summed vertical footing reaction.
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
from slipsurface.fe2d.mesh import DistanceSize, Domain, mesh_quality, unstructured_mesh  # noqa: E402

SOURCE_URL = (
    "https://bentleysystems.service-now.com/community"
    "?id=kb_article&sysparm_article=KB0108033"
)
PUBLISHED_TOTAL_REACTION_KN = 588.0
MESH_LEVELS = {
    "coarse": (0.16, 0.55),
    "medium": (0.11, 0.40),
    "fine": (0.08, 0.30),
}


def build_model(h_min: float, h_max: float) -> api.Model:
    # The top edge is split at r=1 m so the rigid-footing prescribed displacement
    # is applied only over the published footing radius.
    domain = Domain()
    domain.add_polygon(
        [(0.0, 0.0), (5.0, 0.0), (5.0, 4.0), (1.0, 4.0), (0.0, 4.0)],
        region=1,
        name="Sand",
        edge_names=["bottom", "right", "top_free", "footing", "axis"],
    )
    footprint = np.asarray([(0.0, 4.0), (1.0, 4.0)], dtype=float)
    mesh = unstructured_mesh(
        domain,
        h=DistanceSize(
            h_min,
            h_max,
            1.25,
            lines=[footprint],
            closed=[False],
        ),
    )
    sand = api.MaterialSpec.mohr_coulomb(
        "Sand",
        E=13000.0,
        nu=0.3,
        c=1.0,
        phi=30.0,
        psi=0.0,
        sig_t=0.0,
        gamma=17.0,
        gamma_sat=20.0,
    )
    water = api.WaterCondition.piezo([(0.0, 2.0)])
    return api.Model(
        analysis=api.Analysis.AXISYMMETRIC,
        mesh=mesh,
        materials={"Sand": sand},
        region_material={1: "Sand"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("right", True, False),
            api.Fixity("axis", True, False),
        ),
        initial=api.InitialStress(
            "k0_field",
            surface_y=4.0,
            water=water,
        ),
        stages=[
            api.Stage(
                "Rigid footing indentation",
                water=water,
                displacements=(api.Displacement("footing", ux=0.0, uy=-0.05),),
            )
        ],
        settings=api.SolverSettings(
            method="NR",
            max_iter=40,
            tol_force=1e-4,
            tol_energy=1e-5,
            dlam0=0.1,
            dlam_min=1e-4,
            dlam_max=0.25,
            line_search=True,
        ),
    )


def run_level(name: str, h_min: float, h_max: float) -> dict:
    model = build_model(h_min, h_max)
    result = api.run(model)
    stage = result.last
    nodes = np.asarray(model.mesh.nodes("footing"), dtype=int)
    reaction_per_radian = float(np.sum(stage.reactions[nodes, 1]))
    total_reaction = abs(reaction_per_radian) * 2.0 * math.pi
    settlement = -float(np.mean(stage.u[nodes, 1])) * 1000.0
    radial_spread = float(np.ptp(stage.u[nodes, 1])) * 1000.0
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
        },
        "footing_node_count": int(nodes.size),
        "mean_settlement_mm": settlement,
        "settlement_spread_mm": radial_spread,
        "vertical_reaction_per_radian_kN": reaction_per_radian,
        "total_circular_reaction_kN": total_reaction,
        "published_total_reaction_kN": PUBLISHED_TOTAL_REACTION_KN,
        "relative_difference": abs(total_reaction - PUBLISHED_TOTAL_REACTION_KN)
        / PUBLISHED_TOTAL_REACTION_KN,
        "accepted_steps": 0 if stage.history is None else stage.history.n_steps,
        "iterations": 0 if stage.history is None else stage.history.n_iterations,
    }


def benchmark(levels: tuple[str, ...]) -> dict:
    runs = [run_level(name, *MESH_LEVELS[name]) for name in levels]
    return {
        "schema": "slipsurface.external-benchmark.plaxis-tutorial01a.v1",
        "benchmark": "PLAXIS 2D Tutorial 01A - rigid circular footing on sand",
        "source_url": SOURCE_URL,
        "claim": "external_tutorial_reproduction_characterization",
        "locked_inputs": {
            "analysis": "axisymmetric",
            "domain_radius_m": 5.0,
            "sand_thickness_m": 4.0,
            "footing_radius_m": 1.0,
            "water_level_y_m": 2.0,
            "material": {
                "model": "Mohr-Coulomb",
                "drainage": "drained",
                "gamma_unsat_kN_m3": 17.0,
                "gamma_sat_kN_m3": 20.0,
                "E_kPa": 13000.0,
                "nu": 0.3,
                "c_kPa": 1.0,
                "phi_deg": 30.0,
                "psi_deg": 0.0,
                "tension_cutoff_kPa": 0.0,
            },
            "footing_prescribed_displacement": {"ux_m": 0.0, "uy_m": -0.05},
            "published_total_reaction_kN": PUBLISHED_TOTAL_REACTION_KN,
        },
        "runs": runs,
        "acceptance_status": "characterization_pending_review",
    }


def markdown(report: dict) -> str:
    lines = [
        "# PLAXIS Tutorial 01A benchmark",
        "",
        "Status: **CHARACTERIZATION — acceptance tolerance not enabled yet**",
        "",
        "| Mesh | Nodes | Settlement (mm) | Total reaction (kN) | Difference vs 588 kN |",
        "|---|---:|---:|---:|---:|",
    ]
    for run in report["runs"]:
        lines.append(
            f"| {run['level']} | {run['nodes']} | {run['mean_settlement_mm']:.6g} | "
            f"{run['total_circular_reaction_kN']:.6g} | "
            f"{100 * run['relative_difference']:.3f}% |"
        )
    lines.extend(
        [
            "",
            "PLAXIS publishes a prescribed 50 mm indentation and a total reaction of about 588 kN.",
            "",
            "No pass is claimed until the reaction level and mesh trend are reviewed.",
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

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
from slipsurface.fe2d.examples.validation import plaxis_tutorial01a_model  # noqa: E402
from slipsurface.fe2d.mesh import mesh_quality  # noqa: E402

SOURCE_URL = (
    "https://bentleysystems.service-now.com/community"
    "?id=kb_article&sysparm_article=KB0108033"
)
PUBLISHED_TOTAL_REACTION_KN = 588.0
PUBLISHED_RELATIVE_LIMIT = 0.10
MESH_CONVERGENCE_LIMIT = 0.02
MESH_LEVELS = {
    "coarse": (0.16, 0.55),
    "medium": (0.11, 0.40),
    "fine": (0.08, 0.30),
}


def build_model(h_min: float, h_max: float) -> api.Model:
    return plaxis_tutorial01a_model(h_min, h_max)


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
    finest = runs[-1]
    published_ok = finest["relative_difference"] <= PUBLISHED_RELATIVE_LIMIT
    convergence_change = None
    convergence_ok = True
    if len(runs) >= 2:
        previous = runs[-2]["total_circular_reaction_kN"]
        current = finest["total_circular_reaction_kN"]
        convergence_change = abs(current - previous) / max(abs(current), 1e-12)
        convergence_ok = convergence_change <= MESH_CONVERGENCE_LIMIT
    settlement_ok = abs(finest["mean_settlement_mm"] - 50.0) <= 1e-8
    uniform_ok = abs(finest["settlement_spread_mm"]) <= 1e-8
    acceptance = published_ok and convergence_ok and settlement_ok and uniform_ok
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
        "acceptance": {
            "published_reaction_relative_limit": PUBLISHED_RELATIVE_LIMIT,
            "medium_to_fine_relative_change_limit": MESH_CONVERGENCE_LIMIT,
            "published_reaction_check": published_ok,
            "medium_to_fine_relative_change": convergence_change,
            "mesh_convergence_check": convergence_ok,
            "prescribed_50mm_check": settlement_ok,
            "rigid_uniform_settlement_check": uniform_ok,
        },
        "acceptance_status": "passed" if acceptance else "failed",
    }


def markdown(report: dict) -> str:
    lines = [
        "# PLAXIS Tutorial 01A benchmark",
        "",
        f"Status: **{report['acceptance_status'].upper()}**",
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
            "Acceptance: finest-mesh reaction within 10% of the published approximate value; "
            "medium-to-fine reaction change within 2%; prescribed settlement must remain exactly "
            "50 mm and uniform over the rigid footing.",
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

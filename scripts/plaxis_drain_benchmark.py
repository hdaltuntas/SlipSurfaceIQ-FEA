"""Reproduce the PLAXIS Drain groundwater-flow verification.

Published PLAXIS validation problem:
- plane-strain soil block 50 m long and 20 m high;
- vertical drain at x=25 m;
- external phreatic level / groundwater head 18 m;
- drain head 10 m;
- saturated permeability k=1 m/day isotropic;
- bottom impermeable; remaining outer flow boundary open;
- Standard/Coarse Van Genuchten retention curve;
- Dupuit one-side discharge = 4.480 m3/day/m;
- PLAXIS 2D one-side discharge ~= 4.489 m3/day/m.

SlipSurface's current van Genuchten-Mualem conductivity law fixes the pore-connectivity
exponent to 0.5, whereas PLAXIS' Hypres/Standard Coarse data use another exponent.
Therefore this first run is characterization: it reproduces the geometry, saturated
permeability, heads and free-surface boundary, reports the analytical and PLAXIS
differences, and does not claim identical unsaturated constitutive input.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from slipsurface.fe2d import api  # noqa: E402
from slipsurface.fe2d.mesh import DistanceSize, Domain, mesh_quality, unstructured_mesh  # noqa: E402

PLAXIS_PAGE = (
    "https://bentleysystems.service-now.com/community"
    "?id=kb_article_view&sysparm_article=KB0110712"
)
DUPUIT_ONE_SIDE_Q_M3_DAY_M = 4.480
PLAXIS_2D_ONE_SIDE_Q_M3_DAY_M = 4.489
K_M_DAY = 1.0
DAY_S = 86400.0
REFERENCE_RELATIVE_LIMIT = 0.01
MESH_CONVERGENCE_LIMIT = 0.01
MASS_BALANCE_RELATIVE_LIMIT = 1.0e-8
MESH_LEVELS = {
    "coarse": (0.70, 2.00),
    "medium": (0.45, 1.35),
    "fine": (0.30, 0.95),
}


def build_model(h_min: float, h_max: float) -> api.Model:
    # Split vertical outer edges at the 18 m phreatic level. Below it the total
    # head is prescribed; above it the outer boundary is a potential seepage face.
    domain = Domain()
    domain.add_polygon(
        [
            (0.0, 0.0),
            (50.0, 0.0),
            (50.0, 18.0),
            (50.0, 20.0),
            (0.0, 20.0),
            (0.0, 18.0),
        ],
        region=1,
        name="Soil",
        edge_names=[
            "bottom",
            "right_wet",
            "right_dry",
            "top",
            "left_dry",
            "left_wet",
        ],
    )
    # A normal drain with h=10 m only constrains the saturated part; above y=10
    # the equivalent pressure is non-positive and is left to the unsaturated flow.
    drain = np.asarray([(25.0, 0.0), (25.0, 10.0)], dtype=float)
    domain.add_line(drain, name="drain")
    mesh = unstructured_mesh(
        domain,
        h=DistanceSize(
            h_min,
            h_max,
            1.22,
            lines=[drain],
            closed=[False],
        ),
    )

    # PLAXIS Standard "Coarse" is based on Hypres topsoil. Match alpha/n and
    # saturated k. SlipSurface currently fixes the Mualem connectivity exponent
    # and therefore this is explicitly not claimed as an identical retention law.
    soil = api.MaterialSpec(
        "soil",
        "elastic",
        {"E": 1.0e4, "nu": 0.3},
        gamma_unsat=0.0,
        gamma_sat=0.0,
        k_sat=(K_M_DAY / DAY_S, K_M_DAY / DAY_S),
        vg=(3.83, 1.3774, 1.0e-8),
    )
    water = api.WaterCondition.seepage(
        {
            "left_wet": 18.0,
            "right_wet": 18.0,
            "drain": 10.0,
        },
        seepage_faces=("left_dry", "top", "right_dry"),
    )
    return api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"soil": soil},
        region_material={1: "soil"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left_wet", True, False),
            api.Fixity("right_wet", True, False),
        ),
        initial=api.InitialStress("none"),
        stages=[api.Stage("PLAXIS Drain steady flow", water=water)],
    )


def run_level(name: str, h_min: float, h_max: float) -> dict:
    model = build_model(h_min, h_max)
    stage = api.run(model).last
    drain_total_m3_day_m = abs(float(stage.flow["drain"])) * DAY_S
    one_side = 0.5 * drain_total_m3_day_m
    external_in = (
        float(stage.flow["left_wet"])
        + float(stage.flow["right_wet"])
        + float(stage.flow.get("left_dry", 0.0))
        + float(stage.flow.get("right_dry", 0.0))
        + float(stage.flow.get("top", 0.0))
    )
    mass_balance_m3_day_m = abs(external_in + float(stage.flow["drain"])) * DAY_S
    q_scale = max(drain_total_m3_day_m, 1.0e-30)
    quality = mesh_quality(model.mesh)
    active_head = stage.head[np.isfinite(stage.head)]
    return {
        "level": name,
        "h_min_m": h_min,
        "h_max_m": h_max,
        "nodes": model.mesh.nn,
        "continuum_elements": int(sum(b.ne for b in model.mesh.continuum_blocks())),
        "mesh_quality": {
            "min_angle_deg": quality.min_angle,
            "mean_min_angle_deg": quality.mean_min_angle,
            "max_aspect": quality.max_aspect,
        },
        "drain_total_m3_day_m": drain_total_m3_day_m,
        "one_side_discharge_m3_day_m": one_side,
        "dupuit_relative_difference": abs(one_side - DUPUIT_ONE_SIDE_Q_M3_DAY_M)
        / DUPUIT_ONE_SIDE_Q_M3_DAY_M,
        "plaxis2d_relative_difference": abs(one_side - PLAXIS_2D_ONE_SIDE_Q_M3_DAY_M)
        / PLAXIS_2D_ONE_SIDE_Q_M3_DAY_M,
        "mass_balance_abs_m3_day_m": mass_balance_m3_day_m,
        "mass_balance_relative": mass_balance_m3_day_m / q_scale,
        "head_min_m": float(active_head.min()),
        "head_max_m": float(active_head.max()),
    }


def benchmark(levels: tuple[str, ...]) -> dict:
    runs = [run_level(name, *MESH_LEVELS[name]) for name in levels]
    finest = runs[-1]
    convergence = None
    convergence_ok = True
    if len(runs) >= 2:
        previous = runs[-2]["one_side_discharge_m3_day_m"]
        current = finest["one_side_discharge_m3_day_m"]
        convergence = abs(current - previous) / max(abs(current), 1.0e-30)
        convergence_ok = convergence <= MESH_CONVERGENCE_LIMIT
    checks = {
        "dupuit_within_1_percent": (
            finest["dupuit_relative_difference"] <= REFERENCE_RELATIVE_LIMIT
        ),
        "plaxis2d_within_1_percent": (
            finest["plaxis2d_relative_difference"] <= REFERENCE_RELATIVE_LIMIT
        ),
        "medium_to_fine_within_1_percent": convergence_ok,
        "mass_balance": finest["mass_balance_relative"] <= MASS_BALANCE_RELATIVE_LIMIT,
        "head_bounds": (
            abs(finest["head_min_m"] - 10.0) <= 1.0e-10
            and abs(finest["head_max_m"] - 18.0) <= 1.0e-10
        ),
    }
    return {
        "schema": "slipsurface.external-benchmark.plaxis-drain.v1",
        "benchmark": "PLAXIS Drain / Dupuit groundwater-flow verification",
        "source_url": PLAXIS_PAGE,
        "claim": "external_validation_reproduction_characterization",
        "locked_inputs": {
            "analysis": "plane_strain",
            "block_m": [50.0, 20.0],
            "drain_x_m": 25.0,
            "external_head_m": 18.0,
            "drain_head_m": 10.0,
            "k_m_day": K_M_DAY,
            "bottom_boundary": "impermeable",
            "outer_boundary_above_head": "seepage_open",
            "plaxis_hydraulic_class": "Standard Coarse / Van Genuchten",
            "slipsurface_vg_alpha_1_m": 3.83,
            "slipsurface_vg_n": 1.3774,
            "constitutive_note": (
                "alpha/n and saturated k matched; PLAXIS pore-connectivity exponent "
                "is not independently configurable in current SlipSurface"
            ),
        },
        "references": {
            "dupuit_one_side_m3_day_m": DUPUIT_ONE_SIDE_Q_M3_DAY_M,
            "plaxis2d_one_side_m3_day_m": PLAXIS_2D_ONE_SIDE_Q_M3_DAY_M,
            "dupuit_total_drain_m3_day_m": 2.0 * DUPUIT_ONE_SIDE_Q_M3_DAY_M,
        },
        "runs": runs,
        "acceptance": {
            "reference_relative_limit": REFERENCE_RELATIVE_LIMIT,
            "medium_to_fine_relative_change_limit": MESH_CONVERGENCE_LIMIT,
            "mass_balance_relative_limit": MASS_BALANCE_RELATIVE_LIMIT,
            "checks": checks,
        },
        "medium_to_fine_relative_change": convergence,
        "acceptance_status": "passed" if all(checks.values()) else "failed",
    }


def markdown(report: dict) -> str:
    lines = [
        "# PLAXIS Drain / Dupuit benchmark",
        "",
        f"Status: **{report['acceptance_status'].upper()}**",
        "",
        "| Mesh | Nodes | One-side Q | vs Dupuit | vs PLAXIS 2D | mass balance |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for run in report["runs"]:
        lines.append(
            f"| {run['level']} | {run['nodes']} | "
            f"{run['one_side_discharge_m3_day_m']:.6g} | "
            f"{100 * run['dupuit_relative_difference']:.3f}% | "
            f"{100 * run['plaxis2d_relative_difference']:.3f}% | "
            f"{run['mass_balance_relative']:.3e} |"
        )
    lines.extend(
        [
            "",
            "Published references: Dupuit **4.480** and PLAXIS 2D **4.489 m3/day/m** per side.",
            "",
            "Acceptance: finest result within 1% of both Dupuit and PLAXIS 2D; "
            "medium-to-fine change within 1%; relative mass-balance residual <=1e-8; "
            "head extrema remain 10 and 18 m.",
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

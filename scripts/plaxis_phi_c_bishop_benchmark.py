"""Reproduce the PLAXIS phi-c reduction / Bishop validation embankment.

Official PLAXIS 2012 validation inputs:
- 2D plane strain embankment, slope 1:2, slope height 4.5 m;
- base soil thickness 2 m and dimension chain 3 + 9 + 3 + 3 = 18 m;
- Mohr-Coulomb soil: gamma=16 kN/m3, E=2600 kPa, nu=0.3,
  c=5 kPa, phi=20 deg, psi=20 deg;
- initial stresses by gravity loading;
- phi-c reduction without surcharge and after 30 kPa surcharge over 3 m crest width;
- published PLAXIS safety factors 1.57 (unloaded) and 1.25 (loaded);
- published Bishop safety factor 1.564 for the unloaded case.

This benchmark uses SlipSurface shear-strength reduction with the same c/tan(phi)
definition. Characterization runs multiple T6 mesh levels before enabling a strict gate.
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
from slipsurface.fe2d.fem.srf import strength_reduction  # noqa: E402
from slipsurface.fe2d.mesh import DistanceSize, Domain, mesh_quality, unstructured_mesh  # noqa: E402

SOURCE_URL = (
    "https://bentleysystems.service-now.com/community"
    "?id=kb_article_view&sysparm_article=KB0110685"
)
VALIDATION_PDF = (
    "https://www.jip-ts.co.jp/plaxis/verifications/"
    "05_phi-c_reduction_and_comparison_with_bishops_method.pdf"
)
PUBLISHED_FS = {"unloaded": 1.57, "loaded_30kPa": 1.25}
PUBLISHED_BISHOP_FS = 1.564
MESH_LEVELS = {
    "coarse": (0.45, 0.90),
    "medium": (0.32, 0.65),
    "fine": (0.24, 0.50),
}


def build_model(h_min: float, h_max: float, *, surcharge_kPa: float = 0.0) -> api.Model:
    # Figure-1 dimension chain: 3 m horizontal ground, 9 m slope run,
    # then two 3 m crest segments; base-to-left-ground = 2 m and total
    # base-to-crest height = 6.5 m.
    points = [
        (0.0, 0.0),
        (18.0, 0.0),
        (18.0, 6.5),
        (15.0, 6.5),
        (12.0, 6.5),
        (3.0, 2.0),
        (0.0, 2.0),
    ]
    domain = Domain()
    domain.add_polygon(
        points,
        region=1,
        name="Embankment",
        edge_names=[
            "base",
            "right",
            "crest_right",
            "surcharge",
            "slope",
            "left_ground",
            "left",
        ],
    )
    focus = [
        np.asarray([(3.0, 2.0), (12.0, 6.5)], dtype=float),
        np.asarray([(12.0, 6.5), (15.0, 6.5)], dtype=float),
    ]
    mesh = unstructured_mesh(
        domain,
        h=DistanceSize(
            h_min,
            h_max,
            1.25,
            lines=focus,
            closed=[False, False],
        ),
    )
    soil = api.MaterialSpec.mohr_coulomb(
        "soil",
        E=2600.0,
        nu=0.3,
        c=5.0,
        phi=20.0,
        psi=20.0,
        gamma=16.0,
    )
    stages = []
    if surcharge_kPa:
        stages.append(
            api.Stage(
                "30 kPa crest surcharge",
                loads=(api.EdgeLoad("surcharge", qn=surcharge_kPa),),
            )
        )
    return api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"soil": soil},
        region_material={1: "soil"},
        fixities=(
            api.Fixity("base", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        initial=api.InitialStress("gravity"),
        stages=stages,
        settings=api.SolverSettings(
            method="NR",
            max_iter=35,
            tol_force=1e-4,
            tol_energy=1e-5,
            dlam0=0.1,
            dlam_min=1e-4,
            dlam_max=0.35,
            line_search=True,
        ),
    )


def run_case(level: str, h_min: float, h_max: float, *, surcharge_kPa: float) -> dict:
    model = build_model(h_min, h_max, surcharge_kPa=surcharge_kPa)
    result = strength_reduction(
        model,
        tol=0.01,
        F_first=1.0,
        growth=1.2,
        F_max=3.0,
        dlam_min=1e-3,
    )
    quality = mesh_quality(model.mesh)
    failed_u = np.linalg.norm(np.nan_to_num(result.u_failed), axis=1)
    peak_node = int(np.argmax(failed_u))
    return {
        "level": level,
        "h_min_m": h_min,
        "h_max_m": h_max,
        "nodes": model.mesh.nn,
        "continuum_elements": int(sum(block.ne for block in model.mesh.continuum_blocks())),
        "mesh_quality": {
            "min_angle_deg": quality.min_angle,
            "mean_min_angle_deg": quality.mean_min_angle,
            "max_aspect": quality.max_aspect,
        },
        "surcharge_kPa": surcharge_kPa,
        "factor": result.factor,
        "failed_bracket": result.F_failed,
        "bracket_width": result.F_failed - result.factor,
        "trial_count": len(result.trials),
        "failure_peak_xy_m": [float(v) for v in model.mesh.coords[peak_node]],
        "failure_peak_increment_m": float(failed_u[peak_node]),
    }


def benchmark(levels: tuple[str, ...]) -> dict:
    runs = {}
    for case, surcharge in (("unloaded", 0.0), ("loaded_30kPa", 30.0)):
        runs[case] = [run_case(name, *MESH_LEVELS[name], surcharge_kPa=surcharge) for name in levels]
    return {
        "schema": "slipsurface.external-benchmark.plaxis-phi-c-bishop.v1",
        "benchmark": "PLAXIS Phi-c reduction and comparison with Bishop's method",
        "source_url": SOURCE_URL,
        "validation_pdf": VALIDATION_PDF,
        "claim": "external_validation_reproduction_characterization",
        "locked_inputs": {
            "analysis": "plane_strain",
            "geometry": {
                "base_thickness_m": 2.0,
                "slope_height_m": 4.5,
                "slope_run_m": 9.0,
                "left_ground_m": 3.0,
                "crest_segments_m": [3.0, 3.0],
                "total_width_m": 18.0,
            },
            "material": {
                "model": "Mohr-Coulomb",
                "gamma_kN_m3": 16.0,
                "E_kPa": 2600.0,
                "nu": 0.3,
                "c_kPa": 5.0,
                "phi_deg": 20.0,
                "psi_deg": 20.0,
            },
            "initial_stress": "gravity loading",
            "surcharge": {"width_m": 3.0, "pressure_kPa": 30.0},
            "published_plaxis_fs": PUBLISHED_FS,
            "published_bishop_unloaded_fs": PUBLISHED_BISHOP_FS,
        },
        "runs": runs,
        "acceptance_status": "characterization_pending_review",
    }


def markdown(report: dict) -> str:
    lines = [
        "# PLAXIS phi-c / Bishop benchmark",
        "",
        "Status: **CHARACTERIZATION — acceptance tolerance not enabled yet**",
        "",
        "| Case | Mesh | Nodes | SlipSurface FoS | PLAXIS FoS | Difference |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for case, runs in report["runs"].items():
        target = PUBLISHED_FS[case]
        for run in runs:
            diff = abs(run["factor"] - target) / target
            lines.append(
                f"| {case} | {run['level']} | {run['nodes']} | {run['factor']:.6g} | "
                f"{target:.4g} | {100 * diff:.3f}% |"
            )
    lines.extend(
        [
            "",
            "Published Bishop unloaded FoS: **1.564**.",
            "",
            "No pass is claimed until the FoS levels, mesh trend and failure location are reviewed.",
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

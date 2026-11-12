"""Independent free-length + bonded-tail tieback series benchmark.

The host continuum is fixed so the FE system reduces to one unbonded axial spring
in series with an elastic shear-lag bonded tail. The reference is closed form and
does not use RS2 response targets.
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
from slipsurface.fe2d.mesh import rectangle  # noqa: E402
from slipsurface.fe2d.mesh.structures import (  # noqa: E402
    add_tieback_series,
    tieback_component_tags,
)


FREE_LENGTH = 3.0
BOND_LENGTH = 5.0
EA = 90_000.0
KB = 12_000.0
HEAD_PULL = 0.001


def build_model(nx: int):
    base = rectangle(BOND_LENGTH, 1.0, nx, 1, api.ElemType.Q4)
    head = base.nn
    mesh = api.Mesh(
        np.vstack([base.coords, [-FREE_LENGTH, 0.0]]),
        base.blocks,
        {**base.node_sets, "head": np.array([head], dtype=np.int64)},
        base.edge_sets,
    )
    bottom = base.nodes("bottom")
    start = int(bottom[np.argmin(base.coords[bottom, 0])])
    mesh = add_tieback_series(mesh, head, "bottom", "tie", bond_start_node=start)
    free_tag, bond_tag = tieback_component_tags("tie")
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"host": api.MaterialSpec.elastic("host", 10_000.0, 0.25)},
        region_material={1: "host"},
        fixities=(api.Fixity("bottom", True, True),),
        initial=api.InitialStress("none"),
        stages=[
            api.Stage(
                "pull",
                active_structures={free_tag, bond_tag},
                displacements=(api.Displacement("tie:head", ux=-HEAD_PULL, uy=0.0),),
            )
        ],
        bolts={
            free_tag: api.BoltSpec(free_tag, EA=EA, T_yield=1e12),
            bond_tag: api.BoltSpec(bond_tag, EA=EA, T_yield=1e12),
        },
        bonds={bond_tag: api.BondSlipSpec(bond_tag, stiffness=KB, strength=1e9)},
    )
    return model, free_tag, bond_tag


def analytical_reaction() -> float:
    ku = EA / FREE_LENGTH
    lam = math.sqrt(KB / EA)
    bonded = EA * lam * math.tanh(lam * BOND_LENGTH)
    series = ku * bonded / (ku + bonded)
    return series * HEAD_PULL


def run_level(nx: int) -> dict:
    model, free_tag, bond_tag = build_model(nx)
    stage = api.run(model).last
    head = int(model.mesh.nodes("tie:head")[0])
    reaction = abs(float(stage.reactions[head, 0]))
    free_force = abs(float(stage.bars[free_tag][0]))
    bond_head_force = abs(float(stage.bars[bond_tag][0]))
    exact = analytical_reaction()
    scale = max(exact, 1e-30)
    return {
        "nx": nx,
        "reaction_kN_per_m": reaction,
        "analytical_kN_per_m": exact,
        "relative_error": abs(reaction - exact) / scale,
        "free_force_kN_per_m": free_force,
        "bond_head_force_kN_per_m": bond_head_force,
        "series_force_mismatch": abs(free_force - bond_head_force) / scale,
    }


def benchmark() -> dict:
    levels = [run_level(nx) for nx in (4, 8, 16, 32)]
    errors = [row["relative_error"] for row in levels]
    mismatch = [row["series_force_mismatch"] for row in levels]
    checks = {
        "fine_within_0_1pct": errors[-1] <= 1e-3,
        "errors_monotone": all(b < a for a, b in zip(errors, errors[1:])),
        "fine_series_force_continuity": mismatch[-1] <= 1e-8,
        "medium_to_fine_improves": errors[-1] < 0.35 * errors[-2],
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "levels": levels,
        "locked_inputs": {
            "free_length_m": FREE_LENGTH,
            "bond_length_m": BOND_LENGTH,
            "EA_kN": EA,
            "bond_stiffness_kN_m2": KB,
            "head_pull_m": HEAD_PULL,
        },
        "scope": (
            "TIE3 unbonded spring in series with verified BOND4 shear-lag tail; "
            "constant-force installation pretension and full RS2 wall model excluded."
        ),
    }


def markdown(report: dict) -> str:
    lines = [
        "# B5 tieback series benchmark",
        "",
        f"Status: **{'PASS' if report['passed'] else 'FAIL'}**",
        "",
        "| bonded segments | FE head reaction | analytical | relative error | force mismatch |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in report["levels"]:
        lines.append(
            f"| {row['nx']} | {row['reaction_kN_per_m']:.9g} | "
            f"{row['analytical_kN_per_m']:.9g} | {row['relative_error']:.3e} | "
            f"{row['series_force_mismatch']:.3e} |"
        )
    lines += ["", "Checks:"]
    for name, ok in report["checks"].items():
        lines.append(f"- {name}: {'PASS' if ok else 'FAIL'}")
    lines += ["", "Scope: " + report["scope"], ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args()
    report = benchmark()
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    text = markdown(report)
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(text, encoding="utf-8")
    print(text)
    return 1 if args.require_pass and not report["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

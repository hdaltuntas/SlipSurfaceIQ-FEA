"""Independent B5 embedded-bond transfer characterization.

This benchmark uses a fixed host continuum so the embedded tendon reduces to the
classical one-dimensional elastic shear-lag problem. It does not use RS2 response
targets and is not an external B5 pass.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from slipsurface.fe2d import api
from slipsurface.fe2d.mesh import rectangle
from slipsurface.fe2d.mesh.structures import add_embedded_bonded_bar


def build_model(nx: int, *, tip_fixed: bool = False):
    length = 6.0
    ea = 90_000.0
    kb = 12_000.0
    head_slip = -0.001
    mesh = rectangle(length, 1.0, nx, 1, api.ElemType.Q4)
    mesh = add_embedded_bonded_bar(mesh, "bottom", "tie")
    displacements = [api.Displacement("tie:slip_start", ux=head_slip)]
    if tip_fixed:
        displacements.append(api.Displacement("tie:slip_end", ux=0.0))
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"soil": api.MaterialSpec.elastic("soil", 10_000.0, 0.25)},
        region_material={1: "soil"},
        fixities=(api.Fixity("bottom", True, True),),
        initial=api.InitialStress("none"),
        stages=[api.Stage("pull", active_structures={"tie"}, displacements=tuple(displacements))],
        bolts={"tie": api.BoltSpec("tie", EA=ea, T_yield=1e12)},
        bonds={"tie": api.BondSlipSpec("tie", stiffness=kb, strength=1e9)},
    )
    return model, length, ea, kb, abs(head_slip)


def run_level(nx: int) -> dict:
    model, length, ea, kb, u0 = build_model(nx)
    result = api.run(model)
    start = int(model.mesh.nodes("tie:slip_start")[0])
    reaction = abs(float(result.last.reactions[start, 0]))
    lam = math.sqrt(kb / ea)
    exact = ea * lam * math.tanh(lam * length) * u0
    return {
        "nx": nx,
        "reaction_kN_per_m": reaction,
        "analytical_kN_per_m": exact,
        "relative_error": abs(reaction - exact) / exact,
        "max_bond_shear_kN_per_m": float(abs(result.last.bonds["tie"][..., 1]).max()),
        "max_axial_kN_per_m": float(abs(result.last.bars["tie"]).max()),
    }


def one_element_exact() -> dict:
    length, ea, kb, delta = 2.0, 60_000.0, 9_000.0, 0.001
    mesh = rectangle(length, 1.0, 1, 1, api.ElemType.Q4)
    mesh = add_embedded_bonded_bar(mesh, "bottom", "tie")
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"soil": api.MaterialSpec.elastic("soil", 10_000.0, 0.25)},
        region_material={1: "soil"},
        fixities=(api.Fixity("bottom", True, True),),
        initial=api.InitialStress("none"),
        stages=[api.Stage(
            "pull", active_structures={"tie"},
            displacements=(
                api.Displacement("tie:slip_start", ux=-delta),
                api.Displacement("tie:slip_end", ux=0.0),
            ),
        )],
        bolts={"tie": api.BoltSpec("tie", EA=ea, T_yield=1e12)},
        bonds={"tie": api.BondSlipSpec("tie", stiffness=kb, strength=1e9)},
    )
    result = api.run(model)
    start = int(mesh.nodes("tie:slip_start")[0])
    actual = float(result.last.reactions[start, 0])
    expected = -(ea / length + kb * length / 3.0) * delta
    return {
        "actual_reaction": actual,
        "expected_reaction": expected,
        "absolute_error": abs(actual - expected),
    }


def benchmark() -> dict:
    exact = one_element_exact()
    levels = [run_level(nx) for nx in (4, 8, 16, 32)]
    errors = [row["relative_error"] for row in levels]
    checks = {
        "one_element_exact": exact["absolute_error"] <= 1e-8,
        "shear_lag_fine_within_0_1pct": errors[-1] <= 1e-3,
        "mesh_errors_monotone": all(b < a for a, b in zip(errors, errors[1:])),
        "medium_to_fine_improves": errors[-1] < 0.35 * errors[-2],
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "one_element": exact,
        "mesh_levels": levels,
        "scope": (
            "Embedded BOND4 axial transfer against an independent elastic shear-lag solution; "
            "no unbonded tieback length, no RS2 target matching and no B5 external pass."
        ),
    }


def markdown(report: dict) -> str:
    lines = [
        "# B5 embedded bond-transfer benchmark",
        "",
        f"Status: **{'PASS' if report['passed'] else 'FAIL'}**",
        "",
        "| nx | FE head reaction | analytical | relative error |",
        "|---:|---:|---:|---:|",
    ]
    for row in report["mesh_levels"]:
        lines.append(
            f"| {row['nx']} | {row['reaction_kN_per_m']:.9g} | "
            f"{row['analytical_kN_per_m']:.9g} | {row['relative_error']:.3e} |"
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

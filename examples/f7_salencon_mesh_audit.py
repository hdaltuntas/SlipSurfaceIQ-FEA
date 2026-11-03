"""F7 optional plastic tunnel benchmark: Salencon cavity with three mesh levels.

Run from repository root after installing the core dependencies:

    python examples/f7_salencon_mesh_audit.py --output-dir f7_salencon

The independent reference uses the circular MC plastic cavity equations.
It does not use the FEM result to establish the reference. Three graded T6
meshes are solved separately and the report includes displacement, plastic
radius and nonlinear iteration history. Every failed solve is retained in JSON.
This audit is deliberately opt-in: its nonlinear solves can be expensive.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np
from scipy.integrate import quad

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.mesh import plate_with_hole

A = 1.0
OUTER = 25.0
P0 = 100.0
PI = 10.0
E = 10000.0
NU = 0.25
COHESION = 10.0
PHI = 30.0


def analytical_cavity(pi: float, psi: float) -> tuple[float, float]:
    """Return plastic radius and inward wall displacement for circular cavity.

    Boundary loading and sign conventions follow the Salencon P3 test:
    tensile stress positive; total far-field initial stress = -P0.
    """
    if not 0 <= pi <= P0 or not 0 <= psi <= PHI:
        raise ValueError("Require 0 <= pi <= p0 and 0 <= psi <= phi")
    k = (1 + math.sin(math.radians(PHI))) / (1 - math.sin(math.radians(PHI)))
    m = (1 + math.sin(math.radians(psi))) / (1 - math.sin(math.radians(psi)))
    h = COHESION / math.tan(math.radians(PHI))
    sc = 2 * COHESION * math.sqrt(k)
    g = E / (2 * (1 + NU))
    pcr = (2 * P0 - sc) / (1 + k)
    if pi >= pcr:
        return A, -(P0 - pi) * A / (2 * g)
    radius = A * (
        2 * (P0 + h) / ((1 + k) * (pi + h))
    ) ** (1 / (k - 1))

    def rhs(r: float) -> float:
        sr = -((pi + h) * (r / A) ** (k - 1) - h)
        st = -(k * (pi + h) * (r / A) ** (k - 1) - h)
        dsr, dst = sr + P0, st + P0
        er = ((1 - NU) * dsr - NU * dst) / (2 * g)
        et = ((1 - NU) * dst - NU * dsr) / (2 * g)
        return r**m * (er + m * et)

    u_radius = -(P0 - pcr) * radius / (2 * g)
    wall = (u_radius * radius**m - quad(
        rhs, A, radius, epsabs=0, epsrel=1e-11
    )[0]) / A**m
    return radius, wall


def cavity_model(nr: int, nt: int, psi: float):
    if nr < 2 or nt < 4:
        raise ValueError("Mesh resolution too low")
    mesh = plate_with_hole(A, OUTER, nr, nt, ElemType.T6, grade=40.0)
    return api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={
            "rock": api.MaterialSpec.mohr_coulomb(
                "rock", E, NU, COHESION, PHI, psi
            )
        },
        region_material={1: "rock"},
        fixities=(
            api.Fixity("x_sym", False, True),
            api.Fixity("y_sym", True, False),
        ),
        initial=api.InitialStress(
            "field", field=(-P0, -P0, -P0, 0.0)
        ),
        stages=[
            api.Stage(
                "pressure release",
                loads=(
                    api.EdgeLoad("hole", qn=PI),
                    api.EdgeLoad("outer_x", qn=P0),
                    api.EdgeLoad("outer_y", qn=P0),
                ),
            )
        ],
        settings=api.SolverSettings(tol_force=1e-5, tol_energy=1e-7),
    )


def plastic_radius_from_gauss(
    points: np.ndarray, flags: np.ndarray
) -> float | None:
    """Bracket the plastic front from Gauss point radii (approximate)."""
    radii = np.linalg.norm(points.reshape(-1, 2), axis=1)
    plastic = flags.ravel() > 0
    if len(radii) != len(plastic):
        raise ValueError("Gauss positions and plastic flags must align")
    if not np.any(plastic) or np.all(plastic):
        return None
    return float(0.5 * (radii[plastic].max() + radii[~plastic].min()))


def stage_diagnostics(stage) -> dict:
    history = stage.history
    records = history.steps if history is not None else []
    accepted = [r for r in records if r.converged]
    rejected = [r for r in records if not r.converged]
    return {
        "load_factor": float(stage.lam),
        "accepted_steps": len(accepted),
        "rejected_steps": len(rejected),
        "newton_iterations": sum(int(r.iterations) for r in records),
        "last_accepted_residual": (
            float(accepted[-1].residuals[-1])
            if accepted and accepted[-1].residuals else None
        ),
    }


def audit_one(nr: int, nt: int, psi: float) -> dict:
    from slipsurface.fe2d.gui.mesh_quality import mesh_quality_report

    model = cavity_model(nr, nt, psi)
    quality = mesh_quality_report(model.mesh)
    if quality.nonpositive_jacobian_elements:
        raise ValueError("Invalid Gauss-point Jacobian in cavity mesh")
    result = api.run(model)
    radius_reference, u_reference = analytical_cavity(PI, psi)
    wall = model.mesh.nodes("hole")
    coords = model.mesh.coords[wall]
    radius = np.linalg.norm(coords, axis=1)
    radial = np.einsum("ij,ij->i", result.last.u[wall], coords) / radius
    radius_fem = plastic_radius_from_gauss(
        result.geom["soil"].xg, result.last.plastic["soil"]
    )
    return {
        "nr": nr,
        "nt": nt,
        "psi_deg": psi,
        "nodes": model.mesh.nn,
        "elements": sum(b.ne for b in model.mesh.continuum_blocks()),
        "reference_plastic_radius_m": radius_reference,
        "fem_plastic_radius_m": radius_fem,
        "relative_plastic_radius_error": (
            abs(radius_fem - radius_reference) / radius_reference
            if radius_fem is not None else None
        ),
        "reference_wall_radial_m": u_reference,
        "fem_wall_radial_m": float(radial.mean()),
        "wall_radial_nonuniformity_m": float(np.ptp(radial)),
        "relative_wall_displacement_error": abs(
            float(radial.mean()) - u_reference
        ) / max(abs(u_reference), 1e-15),
        "plastic_gauss_points": int(np.count_nonzero(
            result.last.plastic["soil"]
        )),
        **stage_diagnostics(result.last),
    }


def run_audit(resolutions: tuple[tuple[int, int], ...], psi: float):
    records = []
    failures = []
    for nr, nt in resolutions:
        try:
            records.append(audit_one(nr, nt, psi))
        except Exception as exc:
            failures.append({
                "nr": nr, "nt": nt,
                "exception": type(exc).__name__, "message": str(exc),
            })
    return records, failures


def write_report(directory: Path, resolutions, psi: float) -> int:
    directory.mkdir(parents=True, exist_ok=True)
    results, failures = run_audit(resolutions, psi)
    document = {
        "case": "Salencon circular Mohr-Coulomb cavity",
        "unit_system": "kN-m-kPa",
        "psi_deg": psi,
        "reference": "independent axisymmetric plastic cavity equation",
        "results": results,
        "failures": failures,
        "note": (
            "Plastic radius is an approximate Gauss-point front bracket. "
            "This report is not a proof of convergence or external software parity."
        ),
    }
    (directory / "salencon_mesh_audit.json").write_text(
        json.dumps(document, indent=2, allow_nan=False), encoding="utf-8"
    )
    if results:
        with (directory / "salencon_mesh_audit.csv").open(
            "w", newline="", encoding="utf-8"
        ) as file:
            writer = csv.DictWriter(file, fieldnames=list(results[0]))
            writer.writeheader()
            writer.writerows(results)
    return int(bool(failures) or not results)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--psi", type=float, default=15.0)
    parser.add_argument(
        "--resolutions", nargs="+", default=["24x24", "40x32", "60x48"]
    )
    parser.add_argument("--output-dir", type=Path, default=Path("f7_salencon"))
    args = parser.parse_args()
    try:
        resolutions = tuple(
            tuple(int(v) for v in pair.split("x")) for pair in args.resolutions
        )
    except (ValueError, TypeError) as exc:
        parser.error(f"Invalid resolution: {exc}")
    if (len(resolutions) < 3 or len(set(resolutions)) != len(resolutions)
            or any(len(x) != 2 or x[0] < 2 or x[1] < 4 for x in resolutions)):
        parser.error("Use at least three distinct resolutions like 24x24 40x32 60x48")
    if not math.isfinite(args.psi) or not 0 <= args.psi <= PHI:
        parser.error("psi must be finite and between 0 and phi")
    return write_report(args.output_dir, resolutions, args.psi)


if __name__ == "__main__":
    raise SystemExit(main())

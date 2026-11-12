"""Independent characterization gate for the B5 scalar grout bond-slip law."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from slipsurface.fe2d.fem.bond_slip import bond_slip_return
from slipsurface.fe2d.model.materials import BondSlipSpec


def _history(spec: BondSlipSpec, increments: list[float]) -> list[dict]:
    q = 0.0
    rows = []
    for ds in increments:
        value, tangent, yielded = bond_slip_return(q, ds, spec)
        q = float(value)
        rows.append(
            {
                "slip_increment_m": ds,
                "shear_kN_per_m": q,
                "tangent_kN_per_m2": float(tangent),
                "yielded": bool(yielded),
            }
        )
    return rows


def benchmark() -> dict:
    synthetic = BondSlipSpec("synthetic", stiffness=2_000.0, strength=10.0)
    synthetic_rows = _history(synthetic, [0.002, 0.004, -0.003, -0.010, 0.001])
    expected_q = np.array([4.0, 10.0, 4.0, -10.0, -8.0])
    expected_kt = np.array([2_000.0, 0.0, 2_000.0, 0.0, 2_000.0])
    expected_y = np.array([False, True, False, True, False])
    actual_q = np.array([row["shear_kN_per_m"] for row in synthetic_rows])
    actual_kt = np.array([row["tangent_kN_per_m2"] for row in synthetic_rows])
    actual_y = np.array([row["yielded"] for row in synthetic_rows])
    synthetic_ok = bool(
        np.allclose(actual_q, expected_q, rtol=0.0, atol=1e-12)
        and np.allclose(actual_kt, expected_kt, rtol=0.0, atol=1e-12)
        and np.array_equal(actual_y, expected_y)
    )

    rs2 = BondSlipSpec("rs2-tutorial", stiffness=10_000.0, strength=5_000.0)
    rs2_rows = _history(rs2, [0.001, 0.009, -0.005])
    rs2_q = np.array([row["shear_kN_per_m"] for row in rs2_rows])
    rs2_ok = bool(
        np.allclose(rs2_q, [10.0, 100.0, 50.0], rtol=0.0, atol=1e-12)
        and not any(row["yielded"] for row in rs2_rows)
        and abs(rs2.strength / rs2.stiffness - 0.5) <= 1e-15
    )

    smooth = BondSlipSpec("tangent", stiffness=3_500.0, strength=100.0)
    q0, ds, eps = 12.0, 0.004, 1e-8
    tangent = float(bond_slip_return(q0, ds, smooth)[1])
    qp = float(bond_slip_return(q0, ds + eps, smooth)[0])
    qm = float(bond_slip_return(q0, ds - eps, smooth)[0])
    numerical = (qp - qm) / (2.0 * eps)
    tangent_error = abs(numerical - tangent) / smooth.stiffness
    tangent_ok = bool(tangent_error <= 1e-9)

    checks = {
        "synthetic_path_exact": synthetic_ok,
        "rs2_property_scale_exact": rs2_ok,
        "smooth_tangent_finite_difference": tangent_ok,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "synthetic_history": synthetic_rows,
        "rs2_tutorial_history": rs2_rows,
        "rs2_yield_slip_m": rs2.strength / rs2.stiffness,
        "tangent_relative_error": tangent_error,
        "scope": (
            "Scalar axial bond-slip constitutive primitive only; no embedded transfer element, "
            "no soil/tieback assembly and no B5 external-validation pass."
        ),
    }


def _markdown(report: dict) -> str:
    status = "PASS" if report["passed"] else "FAIL"
    lines = [
        "# B5 grout bond-slip constitutive benchmark",
        "",
        f"Status: **{status}**",
        "",
        f"RS2-property yield slip: {report['rs2_yield_slip_m']:.6g} m",
        f"Smooth-branch tangent relative error: {report['tangent_relative_error']:.3e}",
        "",
        "Checks:",
    ]
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
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(_markdown(report), encoding="utf-8")
    print(_markdown(report))
    return 1 if args.require_pass and not report["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

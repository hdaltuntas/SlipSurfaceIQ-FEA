"""Native partial-stage contact equilibrium with independent load-history targets.

Analytical fixtures use direct products of stage weights, not the audit's recursive
nodal force reconstruction. Uniform layers additionally check exact gap and reactions.
Eccentric multilayer-element fixtures check equilibrium, not an exact contact patch.
"""

from __future__ import annotations

import argparse
import json
import runpy
from dataclasses import replace
from pathlib import Path

import numpy as np

from slipsurface.fe2d import api
from slipsurface.fe2d.post.contact_partial_equilibrium import contact_partial_equilibrium_by_stage

_ROOT = Path(__file__).resolve().parent
_LAYER = runpy.run_path(str(_ROOT / "f7_contact_static_benchmark.py"))
_ECCENTRIC = runpy.run_path(str(_ROOT / "f7_contact_equilibrium_benchmark.py"))
FRACTIONS = (0.4, 0.5, 0.25, 1.0, 0.6, 1.0, 0.5)


def weighted_targets(targets, fractions):
    """Closed sum of products: coefficient_j = alpha_j * product(1-alpha_k, k>j)."""
    targets = np.asarray(targets, dtype=float)
    return np.array([
        sum(targets[j] * fractions[j] * np.prod([1 - a for a in fractions[j + 1:i + 1]])
            for j in range(i + 1))
        for i in range(len(fractions))
    ])


def build_partial_layer(*, element_type="IFACE4", initial_gap=0.0, mode="force"):
    if mode not in ("force", "displacement", "mixed"):
        raise ValueError("Unsupported control mode")
    model, targets = _LAYER["build_model"](
        element_type=element_type, initial_gap=initial_gap,
        mode="displacement" if mode == "displacement" else "force",
    )
    tops = (0.006, 0.005, 0.001, -0.001, -0.003, 0.004, -0.004)
    model.stages = [replace(
        st, load_split=alpha, name=f"partial_{i}",
        displacements=((api.Displacement("top", uy=tops[i]),)
                       if mode == "mixed" else st.displacements),
    ) for i, (st, alpha) in enumerate(zip(model.stages, FRACTIONS))]
    force_targets = np.zeros(7) if mode == "displacement" else np.asarray(targets)
    top_targets = np.zeros(7) if mode == "force" else np.asarray(tops)
    forces = weighted_targets(force_targets, FRACTIONS)
    displacements = weighted_targets(top_targets, FRACTIONS)
    return model, forces, displacements


def layer_reference(force, top, initial_gap):
    """Independent fixed-width elastic-layer/contact equilibrium (kPa, m, kN/m)."""
    width, modulus, height, kn = 2.0, 2400.0, 1.0, 2000.0
    k, q = modulus / height, force / width
    free_bottom = top + q / k
    bottom = (free_bottom if free_bottom >= -initial_gap else
              (q + k * top - kn * initial_gap) / (k + kn))
    gap = initial_gap + bottom
    normal = kn * min(gap, 0.0)
    return dict(gap=gap, normal=normal, top_reaction=width*k*(top-bottom),
                base_reaction=-width*normal, applied_force=force, top_displacement=top)


def run_layer_case(*, element_type="IFACE4", initial_gap=0.0, mode="force"):
    model, forces, displacements = build_partial_layer(
        element_type=element_type, initial_gap=initial_gap, mode=mode,
    )
    result = api.run(model)
    report = contact_partial_equilibrium_by_stage(result)
    references = []
    for i, (st, force, top) in enumerate(zip(result.stages, forces, displacements)):
        expected = layer_reference(force, top, initial_gap)
        checks = {
            "gap_m": (st.contact_gap["contact"], expected["gap"], 1e-10),
            "normal_kpa": (st.interfaces["contact"][..., 1], expected["normal"], 1e-8),
            "top_reaction_kn_per_m": (st.reactions[model.mesh.nodes("top"), 1].sum(),
                                      expected["top_reaction"], 1e-8),
            "base_reaction_kn_per_m": (st.reactions[model.mesh.nodes("base"), 1].sum(),
                                       expected["base_reaction"], 1e-8),
            "applied_force_kn_per_m": (report["stages"][i].get("external_resultant", [np.nan]*3)[1],
                                       force, 1e-8),
        }
        errors = {}
        for key, (actual, target, tolerance) in checks.items():
            finite = np.isfinite(actual).all()
            error = float(np.max(np.abs(actual-target))) if finite else None
            errors[key] = {"status": "passed" if finite and error <= tolerance else "failed",
                           "maximum_absolute_error": error, "tolerance": tolerance}
        valid = all(v["status"] == "passed" for v in errors.values())
        references.append({"stage_index": i, "status": "passed" if valid else "failed",
                           "expected": expected, "checks": errors})
    passed = (report["status"] == "passed" and len(references) == 7
              and all(r["status"] == "passed" for r in references))
    return {**report, "status": "passed" if passed else "failed", "case": "partial_layer",
            "element_type": element_type, "initial_gap_m": initial_gap, "mode": mode,
            "analytical_layer_checks": references}


def build_partial_eccentric(*, element_type="IFACE4", initial_gap=0.0, quarter_turn=False):
    model, targets = _ECCENTRIC["build_loaded_model"](
        element_type=element_type, initial_gap=initial_gap, quarter_turn=quarter_turn,
    )
    fractions = (0.35, 0.6, 1.0, 0.25, 0.5, 1.0)
    model.stages = [replace(st, load_split=a, active_structures={"contact"}, name=f"partial_{i}")
                    for i, (st, a) in enumerate(zip(model.stages, fractions))]
    return model, weighted_targets(targets, fractions)


def run_eccentric_case(**kwargs):
    model, expected = build_partial_eccentric(**kwargs)
    result = api.run(model)
    report = contact_partial_equilibrium_by_stage(result)
    references = []
    for row, target in zip(report["stages"], expected):
        actual = np.asarray(row.get("external_resultant", [np.nan]*3))
        finite = np.isfinite(actual).all()
        error = float(np.max(np.abs(actual-target))) if finite else None
        references.append({"status": "passed" if finite and error <= 1e-10 else "failed",
                           "expected_applied_resultant": target.tolist(),
                           "maximum_absolute_error": error})
    passed = (report["status"] == "passed" and len(references) == 6
              and all(r["status"] == "passed" for r in references))
    return {**report, "status": "passed" if passed else "failed", "case": "partial_eccentric",
            **kwargs, "analytical_applied_checks": references}


def run_benchmark():
    cases = []
    for etype in ("IFACE4", "IFACE6"):
        for gap in (0.0, 0.002):
            cases += [run_layer_case(element_type=etype, initial_gap=gap, mode=mode)
                      for mode in ("force", "displacement", "mixed")]
            cases += [run_eccentric_case(element_type=etype, initial_gap=gap, quarter_turn=rot)
                      for rot in (False, True)]
    return {"status": "passed" if all(c["status"] == "passed" for c in cases) else "failed",
            "native_solver": "api.run / StaticSolver", "case_count": len(cases),
            "stage_count": sum(c["stage_count"] for c in cases), "cases": cases,
            "scope": "Fixed topology and support membership; no retained release, excavation, "
                     "water, restart or independent full-system physical validation."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_benchmark()
    payload = json.dumps(report, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

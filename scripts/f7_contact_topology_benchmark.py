"""Native result-snapshot topology audit against retained independent references.

No fixture geometry or closed-form target is passed to the reusable audit. The
old independent evaluators remain separate and check the same native solutions.
"""

from __future__ import annotations

import argparse
import json
import runpy
from dataclasses import replace
from pathlib import Path

import numpy as np

from slipsurface.fe2d import api
from slipsurface.fe2d.post.contact_topology_equilibrium import contact_topology_equilibrium_by_stage

_HERE = Path(__file__).parent
_REBIRTH = runpy.run_path(str(_HERE / "f7_contact_reactivation_benchmark.py"))
_REMOVE = runpy.run_path(str(_HERE / "f7_contact_excavation_benchmark.py"))


def asymmetric_model(*, element_type="IFACE4", initial_gap=0.002):
    """Partial lateral notch, heterogeneous elasticity and nonuniform biaxial loads.

    This deliberately breaks the scalar layer assumptions. Only equilibrium and
    incremental elasticity are claimed; no closed-form displacement/contact patch.
    """
    model, _ = _REBIRTH["build_model"](element_type=element_type, initial_gap=initial_gap)
    lower = model.mesh.block("lower")
    region = lower.region.copy()
    candidates = np.flatnonzero(region == 2)
    region[candidates[-1]] = 4
    blocks = tuple(replace(b, region=region) if b.tag == "lower" else b for b in model.mesh.blocks)
    model.mesh = replace(model.mesh, blocks=blocks)
    model.materials["stiffer"] = api.MaterialSpec.elastic("stiffer", 3700.0, 0.28)
    model.region_material[4] = "stiffer"
    n = model.mesh.block("contact").etype.nen // 2
    node = int(model.mesh.block("contact").conn[0, n])
    regions = (None, {1, 3, 4}, {1, 3, 4}, None, {1, 3, 4}, None)
    fractions = (1.0, 0.25, 1.0, 0.5, 0.4, 1.0)
    targets = (-0.012, -0.008, -0.004, 0.006, 0.004, -0.014)
    model.stages = [
        api.Stage(
            f"notch_{i}",
            active_regions=active,
            active_structures={"contact"},
            load_split=a,
            displacements=(api.Displacement("top", uy=u),),
            loads=(api.PointLoad(node, fx=1.5, fy=-2.0 - i),),
            reset_displacements=i in (1, 3),
        )
        for i, (active, a, u) in enumerate(zip(regions, fractions, targets))
    ]
    return model


def run_case(family="reactivation", **parameters):
    if family not in ("reactivation", "excavation", "asymmetric"):
        raise ValueError("Unknown topology benchmark family")
    fixture = None
    if family == "asymmetric":
        model = asymmetric_model(**parameters)
    else:
        reference = _REBIRTH if family == "reactivation" else _REMOVE
        model, fixture = reference["build_model"](**parameters)
    result = api.run(model)
    audit = contact_topology_equilibrium_by_stage(result)
    exact = None if fixture is None else reference["evaluate"](result, model, fixture)
    matches = exact is None or (
        exact["status"] == "passed"
        and all(
            row.get("physical_equilibrium", {}).get("status")
            == ("passed" if expected["physical_only_equilibrium"] else "failed")
            for row, expected in zip(audit["stages"], exact["stages"])
        )
    )
    return {
        "family": family,
        "parameters": parameters,
        "status": "passed" if audit["status"] == "passed" and matches else "failed",
        "stage_count": len(result.stages),
        "audit": audit,
        "independent_fixture_status": "not_available" if exact is None else exact["status"],
        "classification_matches": bool(matches),
    }


def run_benchmark():
    cases = [
        run_case(family, element_type=etype, initial_gap=gap, quarter_turn=turn, mode=mode)
        for family in ("reactivation", "excavation")
        for etype in ("IFACE4", "IFACE6")
        for gap in (0.0, 0.002)
        for turn in (False, True)
        for mode in ("force", "displacement", "mixed")
    ]
    cases += [
        run_case("asymmetric", element_type=etype, initial_gap=gap)
        for etype in ("IFACE4", "IFACE6")
        for gap in (0.0, 0.002)
    ]
    return {
        "status": "passed" if all(c["status"] == "passed" for c in cases) else "failed",
        "native_solver": "api.run / StaticSolver",
        "case_count": len(cases),
        "stage_count": sum(c["stage_count"] for c in cases),
        "cases": cases,
        "scope": "Reusable elastic snapshot audit; retained exact references plus an "
        "asymmetric partial-notch test. Not an independent FE solver, physical "
        "backfill placement or general nonlinear excavation validation.",
    }


def audit_saved_project(path):
    """Audit accepted snapshots without running or modifying the solver/model."""
    path = Path(path)
    if path.suffix.lower() == ".h5":
        result = api.load_results(path)
    elif path.suffix.lower() == ".ssproj":
        result = api.load_project(path).results
        if result is None:
            raise ValueError("Project contains no accepted result snapshots")
    else:
        raise ValueError("Expected .ssproj or .h5 accepted-result file")
    return contact_topology_equilibrium_by_stage(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--example", type=Path)
    parser.add_argument(
        "--project",
        type=Path,
        help="Audit stored .ssproj/.h5 results instead of running benchmarks",
    )
    args = parser.parse_args()
    if args.project and args.example:
        parser.error("--example is only available when running the benchmark")
    report = audit_saved_project(args.project) if args.project else run_benchmark()
    payload = json.dumps(report, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    if args.example and report["status"] == "passed":
        model = asymmetric_model(element_type="IFACE6")
        result = api.run(model)
        if contact_topology_equilibrium_by_stage(result)["status"] != "passed":
            raise ValueError("Example audit failed")
        args.example.parent.mkdir(parents=True, exist_ok=True)
        api.save_project(model, args.example, result)
    print(payload)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

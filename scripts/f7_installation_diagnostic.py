"""Controlled installation-stage experiments; no physical acceptance threshold."""

from __future__ import annotations

import argparse
import json
import runpy
from dataclasses import replace
from pathlib import Path

import numpy as np

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.mesh import mapped_mesh
from slipsurface.fe2d.mesh.structures import add_beams, insert_interface
from slipsurface.fe2d.post.pile_installation_budget import pile_installation_budget


def symmetric_case(base, nx, ny, etype=ElemType.T6):
    """Reflection-symmetric rectangular soil mesh with a central 9 m pile.

    Even nx and alternating diagonals pair triangular cells under reflection.
    ny must resolve the pile tip at y=-9 and all half-edge stations exactly.
    The anchor and excavation partitions are absent in this control case.
    """
    if nx < 2 or nx % 2 or ny < 14 or ny % 14:
        raise ValueError("Require even nx and ny a positive multiple of 14")
    if etype not in (ElemType.T6, ElemType.Q8):
        raise ValueError("Symmetry control supports T6 or Q8")
    mesh = mapped_mesh(lambda s, t: (30 * s - 15, 14 * t - 14), nx, ny, etype)
    segments = []
    for y in np.arange(0., -9., -14 / ny):
        points = ((0., y), (0., y - 14 / ny), (0., y - 7 / ny))
        ids = []
        for point in points:
            matches = np.flatnonzero(np.all(np.isclose(mesh.coords, point), axis=1))
            if len(matches) != 1:
                raise ValueError("Structured mesh must resolve the pile path")
            ids.append(int(matches[0]))
        segments.append(ids)
    mesh = replace(mesh, edge_sets={**mesh.edge_sets, "pile": np.array(segments)})
    mesh = add_beams(mesh, "pile", "cad_Pile")
    for name, side in (("cad_Pile_ifL", "left"), ("cad_Pile_ifR", "right")):
        mesh = insert_interface(mesh, "pile", name, side)
    return replace(
        base, mesh=mesh, region_material={1: "sand"}, bolts={},
        fixities=(api.Fixity("bottom", True, True), api.Fixity("left", True, False),
                  api.Fixity("right", True, False)),
        stages=[base.stages[0]],
    )


def peak_location(mesh, stage, tag="cad_Pile"):
    """Retain the actual element end at the absolute moment peak."""
    forces = np.asarray(stage.beams[tag])
    if forces.shape != (mesh.block(tag).ne, 2, 3) or not np.isfinite(forces).all():
        raise ValueError("Expected finite beam end forces matching the mesh")
    values = forces[:, :, 2]
    element, end = np.unravel_index(np.argmax(np.abs(values)), values.shape)
    node = mesh.block(tag).conn[element, end]
    return {
        "moment": float(values[element, end]),
        "xy_m": mesh.coords[node].tolist(),
        "element": int(element), "end": int(end),
    }


def run(sizes):
    helpers = runpy.run_path(str(
        Path(__file__).resolve().parents[1] / "examples/f7_excavation_mesh_audit.py"
    ))
    base = helpers["excavation_model"]()
    rows = []
    for h in sizes:
        model = helpers["build_case"](base, h)
        install = model.stages[0]
        equilibrate = api.Stage("soil equilibration", active_structures=frozenset())
        for variant in (
            "baseline", "weightless_pile", "half_weight_pile", "pre_equilibrated_soil",
        ):
            current = replace(model, stages=[install])
            if variant in ("weightless_pile", "half_weight_pile"):
                factor = 0.0 if variant == "weightless_pile" else 0.5
                current = replace(current, liners={
                    tag: replace(spec, unit_weight=factor * spec.unit_weight)
                    for tag, spec in current.liners.items()
                })
            elif variant == "pre_equilibrated_soil":
                current = replace(current, stages=[equilibrate, install])
            result = api.run(current)
            stage = result.last
            rows.append({
                "h_m": h, "variant": variant,
                "peak": peak_location(current.mesh, stage),
                "maximum_displacement_m": helpers["finite_max_displacement"](stage),
                "signed_profiles": helpers["stage_signed_profiles"](current, stage)[0],
                "last_residual": helpers["stage_metrics"](
                    stage, h, current.mesh.nn, 0
                )["last_accepted_residual"],
                "nodal_budget": pile_installation_budget(current, stage, "cad_Pile"),
            })
    for nx, ny in ((12, 14), (20, 28), (30, 42)):
        for etype in (ElemType.T6, ElemType.Q8):
            current = symmetric_case(base, nx, ny, etype)
            stage = api.run(current).last
            rows.append({
                "variant": "symmetric_" + etype.name, "nx": nx, "ny": ny,
                "peak": peak_location(current.mesh, stage),
                "signed_profiles": helpers["stage_signed_profiles"](current, stage)[0],
                "nodal_budget": pile_installation_budget(current, stage, "cad_Pile"),
            })
    return {
        "results": rows,
        "interpretation": "Controlled diagnostics only; no physical validation or tolerance.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=float, nargs="+", default=[2.5, 1.8, 1.2])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.sizes)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()

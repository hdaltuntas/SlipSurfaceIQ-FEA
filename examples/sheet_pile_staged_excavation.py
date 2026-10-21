"""Two-sided-interface sand excavation with a wished-in-place cantilever sheet pile.

Run from a development checkout: PYTHONPATH=src python examples/sheet_pile_staged_excavation.py
Stages: K0 stress initialization, stress-free wall activation, 5 m excavation.
This is a reproducible coupled model, not a completed S4 validation or a design result.
See docs/phase3-verification.md for assumptions and outstanding independent comparison.
"""

from __future__ import annotations

import numpy as np

from slipsurface.fe2d import api
from slipsurface.fe2d.mesh import DistanceSize, Domain, recombine_mesh, unstructured_mesh
from slipsurface.fe2d.mesh.structures import add_beams, insert_interface


def model(h=0.5, *, mixed=False, gauss_order=None, soil_tension=None, rankine_at_apex=False):
    domain = Domain().add_polygon(
        [(-20, -20), (20, -20), (20, 0), (-20, 0)], 1, edge_names=["bottom", "right", "top", "left"]
    )
    domain.add_polygon([(0, -5), (20, -5), (20, 0), (0, 0)], 2)
    line = np.array([[0, -10.5], [0, 0]])
    domain.add_line(line, name="wall")
    mesh = unstructured_mesh(domain, h=DistanceSize(h, 1.5, 1.3, lines=[line]))
    if mixed:
        mesh = recombine_mesh(mesh, where=lambda x: np.abs(x[:, 0]) < 4)
    mesh = add_beams(mesh, "wall", "pile")
    mesh = insert_interface(mesh, "wall", "pile_left", "left")
    mesh = insert_interface(mesh, "wall", "pile_right", "right")
    soil = api.MaterialSpec.mohr_coulomb(
        "sand",
        3e4,
        0.3,
        0,
        30,
        0,
        sig_t=soil_tension,
        gamma=18,
        rankine_at_apex=rankine_at_apex,
    )
    return api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"sand": soil},
        region_material={1: "sand", 2: "sand"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        initial=api.InitialStress("k0_field", k0=0.5),
        liners={"pile": api.LinerSpec("pile", 2e8, 0, 0.1, 0.001, 0.08)},
        interfaces={
            tag: api.InterfaceSpec.from_soil(tag, soil, R=1, t_v=0.1)
            for tag in ["pile_left", "pile_right"]
        },
        stages=[
            api.Stage("install", active_structures={"pile", "pile_left", "pile_right"}),
            api.Stage(
                "excavate",
                active_regions={1},
                active_structures={"pile", "pile_left", "pile_right"},
            ),
        ],
        settings=api.SolverSettings(
            dlam0=0.1,
            tol_force=1e-4,
            tol_energy=1e-5,
            line_search=True,
            gauss_order=gauss_order or ("high" if mixed else "default"),
        ),
    )


def main():
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=float, default=0.5, help="local mesh size [m]")
    parser.add_argument("--output", type=Path, help="optional .ssproj output path")
    parser.add_argument("--mixed", action="store_true", help="recombine suitable T6 pairs to Q8")
    parser.add_argument("--gauss-order", choices=["default", "high"], default=None)
    parser.add_argument(
        "--soil-tension",
        type=float,
        default=None,
        help="explicit soil tensile strength [kPa]; omitted means no Rankine flow",
    )
    args = parser.parse_args()
    if not np.isfinite(args.size) or args.size <= 0:
        parser.error("--size must be positive")
    if args.soil_tension is not None and (
        not np.isfinite(args.soil_tension) or args.soil_tension < 0
    ):
        parser.error("--soil-tension must be finite and nonnegative")
    m = model(
        args.size, mixed=args.mixed, gauss_order=args.gauss_order, soil_tension=args.soil_tension
    )
    print(f"Nodes: {m.mesh.nn}")
    result = api.run(m)
    moment = np.nanmax(np.abs(result.last.beams["pile"][:, :, 2]))
    displacement = np.nanmax(np.linalg.norm(result.last.u, axis=1))
    print(f"Maximum |M|: {moment:.6f} kN m/m")
    print(f"Maximum |u|: {displacement:.6f} m")
    if args.output:
        api.save_project(m, args.output, results=result)
        print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()

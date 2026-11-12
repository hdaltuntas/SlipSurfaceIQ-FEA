"""Official-validation example models exposed by the desktop Examples menu.

These are interactive, medium-resolution versions of the locked RS2/PLAXIS
benchmark models. Strict release gates still run their documented multi-mesh
benchmark scripts; opening a menu example does not by itself constitute a
benchmark pass.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from .. import api
from ..mesh import DistanceSize, Domain, circle, rectangle, unstructured_mesh
from ..mesh.structures import add_embedded_bonded_bar


@dataclass(frozen=True)
class ValidationExample:
    key: str
    title: str
    description: str
    builder: Callable[[], api.Model]


def rs2_introduction_model() -> api.Model:
    """RS2 Introduction / Surface Excavation, medium benchmark mesh."""
    outer = [
        (-10.0, -8.0),
        (15.0, -8.0),
        (15.0, 4.0),
        (6.5, 4.0),
        (4.5, 4.0),
        (1.0, 4.0),
        (-1.0, 4.0),
        (-10.0, 4.0),
    ]
    outer_edges = [
        "bottom",
        "right",
        "top_right",
        "trench_top",
        "top_middle",
        "surface_load",
        "top_left",
        "left",
    ]
    tunnel = circle(0.0, 0.0, 1.0, 60)
    trench = np.asarray(
        [(4.5, 4.0), (4.5, -1.0), (6.5, -1.0), (6.5, 4.0)],
        dtype=float,
    )
    domain = Domain()
    domain.add_polygon(outer, region=1, name="Till", edge_names=outer_edges)
    domain.add_polygon(tunnel, region=2, name="Tunnel")
    domain.add_polygon(trench, region=3, name="Trench")
    mesh = unstructured_mesh(
        domain,
        h=DistanceSize(
            0.25,
            0.85,
            1.25,
            lines=[np.asarray(tunnel), trench],
            closed=[True, True],
        ),
    )
    till = api.MaterialSpec.elastic("Till", E=50_000.0, nu=0.25, gamma=20.0)
    return api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"Till": till},
        region_material={1: "Till", 2: "Till", 3: "Till"},
        fixities=(
            api.Fixity("bottom", False, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        initial=api.InitialStress("k0_field", k0=0.5, surface_y=4.0),
        stages=[
            api.Stage("Excavate Tunnel", active_regions={1, 3}),
            api.Stage("Excavate Trench", active_regions={1}),
            api.Stage(
                "Surface Load",
                active_regions={1},
                loads=(api.EdgeLoad("surface_load", qn=200.0),),
            ),
        ],
    )


def plaxis_tutorial01a_model() -> api.Model:
    """PLAXIS Tutorial 01A rigid circular footing, medium benchmark mesh."""
    domain = Domain()
    domain.add_polygon(
        [(0.0, 0.0), (5.0, 0.0), (5.0, 4.0), (1.0, 4.0), (0.0, 4.0)],
        region=1,
        name="Sand",
        edge_names=["bottom", "right", "top_free", "footing", "axis"],
    )
    footprint = np.asarray([(0.0, 4.0), (1.0, 4.0)], dtype=float)
    mesh = unstructured_mesh(
        domain,
        h=DistanceSize(0.11, 0.40, 1.25, lines=[footprint], closed=[False]),
    )
    sand = api.MaterialSpec.mohr_coulomb(
        "Sand",
        E=13_000.0,
        nu=0.3,
        c=1.0,
        phi=30.0,
        psi=0.0,
        sig_t=0.0,
        gamma=17.0,
        gamma_sat=20.0,
    )
    water = api.WaterCondition.piezo([(0.0, 2.0)])
    return api.Model(
        analysis=api.Analysis.AXISYMMETRIC,
        mesh=mesh,
        materials={"Sand": sand},
        region_material={1: "Sand"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("right", True, False),
            api.Fixity("axis", True, False),
        ),
        initial=api.InitialStress("k0_field", surface_y=4.0, water=water),
        stages=[
            api.Stage(
                "Rigid footing indentation",
                water=water,
                displacements=(api.Displacement("footing", ux=0.0, uy=-0.05),),
            )
        ],
        settings=api.SolverSettings(
            method="NR",
            max_iter=40,
            tol_force=1e-4,
            tol_energy=1e-5,
            dlam0=0.1,
            dlam_min=1e-4,
            dlam_max=0.25,
            line_search=True,
        ),
    )


def plaxis_phi_c_bishop_model() -> api.Model:
    """PLAXIS phi-c/Bishop validation slope with the 30 kPa surcharge."""
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
        h=DistanceSize(0.32, 0.65, 1.25, lines=focus, closed=[False, False]),
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
        stages=[
            api.Stage(
                "30 kPa crest surcharge",
                loads=(api.EdgeLoad("surcharge", qn=30.0),),
            )
        ],
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


def plaxis_drain_model() -> api.Model:
    """PLAXIS Drain / Dupuit groundwater verification, medium benchmark mesh."""
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
    drain = np.asarray([(25.0, 0.0), (25.0, 10.0)], dtype=float)
    domain.add_line(drain, name="drain")
    mesh = unstructured_mesh(
        domain,
        h=DistanceSize(0.45, 1.35, 1.22, lines=[drain], closed=[False]),
    )
    day_s = 86_400.0
    soil = api.MaterialSpec(
        "soil",
        "elastic",
        {"E": 1.0e4, "nu": 0.3},
        gamma_unsat=0.0,
        gamma_sat=0.0,
        k_sat=(1.0 / day_s, 1.0 / day_s),
        vg=(3.83, 1.3774, 1.0e-8),
    )
    water = api.WaterCondition.seepage(
        {"left_wet": 18.0, "right_wet": 18.0, "drain": 10.0},
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


def rs2_b5_embedded_bond_model() -> api.Model:
    """Bounded B5 candidate: RS2 tieback bonded-tail properties only."""
    total_tieback_length = math.sqrt(8.0**2 + 3.0**2)
    bonded_length = 0.40 * total_tieback_length
    diameter = 0.019
    area = math.pi * diameter**2 / 4.0
    ea = 200_000_000.0 * area
    mesh = rectangle(bonded_length, 1.0, 16, 1, api.ElemType.Q4)
    mesh = add_embedded_bonded_bar(mesh, "bottom", "tieback")
    return api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"host": api.MaterialSpec.elastic("host", 10_000.0, 0.25)},
        region_material={1: "host"},
        fixities=(api.Fixity("bottom", True, True),),
        initial=api.InitialStress("none"),
        stages=[
            api.Stage(
                "Bonded-tail pull",
                active_structures={"tieback"},
                displacements=(api.Displacement("tieback:slip_start", ux=-0.002),),
            )
        ],
        bolts={
            "tieback": api.BoltSpec(
                "tieback",
                EA=ea,
                T_yield=100.0,
                pretension=0.0,
                spacing_out_of_plane=1.0,
            )
        },
        bonds={
            "tieback": api.BondSlipSpec(
                "tieback",
                stiffness=10_000.0,
                strength=5_000.0,
            )
        },
    )



VALIDATION_EXAMPLES = (
    ValidationExample(
        "rs2-introduction",
        "RS2 Introduction — tunnel, trench and surface load",
        "Official RS2 Introduction benchmark model; medium interactive mesh.",
        rs2_introduction_model,
    ),
    ValidationExample(
        "plaxis-tutorial01a",
        "PLAXIS Tutorial 01A — rigid circular footing",
        "Axisymmetric Mohr-Coulomb footing benchmark with 50 mm prescribed settlement.",
        plaxis_tutorial01a_model,
    ),
    ValidationExample(
        "plaxis-phi-c-bishop",
        "PLAXIS φ-c / Bishop — 30 kPa slope",
        (
            "Loaded validation slope. Strict FoS verification is performed by the "
            "SRF benchmark."
        ),
        plaxis_phi_c_bishop_model,
    ),
    ValidationExample(
        "plaxis-drain",
        "PLAXIS Drain / Dupuit — groundwater flow",
        "Steady seepage benchmark with 18 m external head and a 10 m internal drain.",
        plaxis_drain_model,
    ),
    ValidationExample(
        "rs2-b5-embedded-bond",
        "RS2 B5 candidate — embedded tieback bond transfer",
        (
            "Bounded bonded-tail mechanics only; this is not yet the full RS2 "
            "sheet-pile benchmark."
        ),
        rs2_b5_embedded_bond_model,
    ),
)


EXAMPLES_BY_KEY = {item.key: item for item in VALIDATION_EXAMPLES}


def validation_example(key: str) -> ValidationExample:
    try:
        return EXAMPLES_BY_KEY[key]
    except KeyError:
        raise KeyError(f"unknown validation example {key!r}") from None

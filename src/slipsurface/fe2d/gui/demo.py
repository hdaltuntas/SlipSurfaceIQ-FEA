"""Documented four-state tunnel example, also used by the portable smoke check.

The acceptance test separately builds this model through native editor controls.
This is an elastic GUI/API parity case, not an independent constitutive benchmark.
"""

from dataclasses import replace

import numpy as np

from .. import api
from ..cad.geometry import BoundaryRule, Drawing, Entity
from ..cad.supports import SupportAssignment
from ..mesh import Domain, layered_box, unstructured_mesh
from ..mesh.structures import add_bars_along, add_beams


def tunnel_points():
    angles = np.arange(16) * 2 * np.pi / 16
    ring = np.column_stack([3 * np.cos(angles), 3 * np.sin(angles)])
    ring[np.abs(ring) < 1e-12] = 0
    return [(-15.0, -15.0), (15.0, -15.0), (15.0, 15.0), (-15.0, 15.0)], ring.tolist()


def tunnel_model():
    outer, ring = tunnel_points()
    domain = Domain()
    domain.add_polygon(outer, 1, name="Rock", edge_names=[f"Rock:{i}" for i in range(1, 5)])
    domain.add_polygon(ring, 2, name="Tunnel", edge_names=[f"Tunnel:{i}" for i in range(1, 17)])
    domain.add_line([(0.0, 3.0), (0.0, 7.0)], name="CrownBolt")
    domain.add_line([(0.0, 3.0), (0.0, 7.0)], name="CrownBolt:1")
    mesh = unstructured_mesh(domain, h=2.0)
    mesh = add_beams(mesh, "Tunnel", "shotcrete")
    mesh = add_bars_along(mesh, "CrownBolt", "bolt")
    return api.Model(
        api.Analysis.PLANE_STRAIN,
        mesh,
        {"rock": api.MaterialSpec.elastic("rock", 50000.0, 0.25)},
        {1: "rock", 2: "rock"},
        fixities=tuple(api.Fixity(f"Rock:{i}", True, True) for i in range(1, 5)),
        initial=api.InitialStress(
            "field", field=(-300.0, -600.0, -225.0, 0.0), active_structures=frozenset()
        ),
        stages=[
            api.Stage("40% relaxation", active_regions={1}, load_split=0.4),
            api.Stage(
                "Shotcrete · 70%",
                active_regions={1},
                active_structures={"shotcrete"},
                load_split=0.5,
            ),
            api.Stage(
                "Bolt · full excavation",
                active_regions={1},
                active_structures={"shotcrete", "bolt"},
            ),
        ],
        liners={
            "shotcrete": api.LinerSpec("shotcrete", 3e7, 0.2, 0.2, 0.2**3 / 12, 0.2 * 5 / 6, 0)
        },
        bolts={"bolt": api.BoltSpec("bolt", 200000.0, 200.0, 0.0, 1.0)},
    )


def excavation_model():
    """RS2-style staged excavation with a pile wall, anchor, and two excavation lifts."""
    drawing = Drawing(
        entities=(
            Entity(
                "Soil", "region", ((-15.0, -14.0), (15.0, -14.0), (15.0, 0.0), (-15.0, 0.0)), 1
            ),
            Entity("Cut1", "region", ((-15.0, -2.0), (0.0, -2.0), (0.0, 0.0), (-15.0, 0.0)), 2),
            Entity("Cut2", "region", ((-15.0, -4.0), (0.0, -4.0), (0.0, -2.0), (-15.0, -2.0)), 3),
            Entity("Pile", "line", ((0.0, 0.0), (0.0, -9.0)), 1),
            Entity("Anchor1", "line", ((0.0, -1.5), (7.0, -4.5)), 1),
        ),
        rules=(
            BoundaryRule("Soil:1", True, True),
            BoundaryRule("Soil:2", True, False),
            BoundaryRule("Soil:4", True, False),
        ),
        h=1.8,
        E=30000.0,
        nu=0.3,
        supports=(
            SupportAssignment("Pile", "pile"),
            SupportAssignment("Anchor1", "bolt"),
        ),
    )
    base = drawing.build_model()
    pile = frozenset({"cad_Pile", "cad_Pile_ifL", "cad_Pile_ifR"})  # pile + skin interfaces
    sand = api.MaterialSpec.elastic("sand", 30000.0, 0.3, gamma=18.0)
    return replace(
        base,
        materials={"sand": sand},
        region_material={1: "sand", 2: "sand", 3: "sand"},
        initial=api.InitialStress("k0_field", k0=0.5, active_structures=frozenset()),
        stages=[
            api.Stage(
                "1. Pile installation",
                active_regions=None,
                active_structures=pile,
                reset_displacements=True,
            ),
            api.Stage(
                "2. Excavation lift 1 (-2 m)",
                active_regions=frozenset({1, 3}),
                active_structures=pile,
            ),
            api.Stage(
                "3. Anchor + excavation lift 2 (-4 m)",
                active_regions=frozenset({1}),
                active_structures=pile | {"cad_Anchor1"},
            ),
        ],
    )


def footing_model():
    """Half of a strip footing on sand over clay. The left edge is the centre line.

    B/2 = 1.5 m. Stage 1 only equilibrates the K0 field; stage 2 applies 150 kPa.
    The settlement to read is stage 2, not the K0 correction.
    """
    mesh = layered_box(30.0, [0.0, -4.0], -20.0, nx=24, ny_per_layer=[4, 8])
    top_edges = mesh.edges("top")
    footing = top_edges[mesh.coords[top_edges[:, 1], 0] <= 1.5 + 1e-9]
    mesh = api.Mesh(
        mesh.coords, mesh.blocks, mesh.node_sets, {**mesh.edge_sets, "footing": footing}
    )
    return api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={
            "sand": api.MaterialSpec.elastic("sand", E=40000.0, nu=0.30, gamma=19.0),
            "clay": api.MaterialSpec.elastic("clay", E=15000.0, nu=0.35, gamma=18.0),
        },
        region_material={1: "sand", 2: "clay"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        initial=api.InitialStress("k0_field"),
        stages=[
            api.Stage("1. Self-weight", reset_displacements=True),
            api.Stage(
                "2. Strip footing (150 kPa)", loads=(api.EdgeLoad("footing", qn=150.0),)
            ),
        ],
    )

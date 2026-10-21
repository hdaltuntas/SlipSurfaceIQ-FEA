"""Documented four-state tunnel example, also used by the portable smoke check.

The acceptance test separately builds this model through native editor controls.
This is an elastic GUI/API parity case, not an independent constitutive benchmark.
"""

import numpy as np

from .. import api
from ..mesh import Domain, unstructured_mesh
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
            api.Stage("%40 gevşeme", active_regions={1}, load_split=0.4),
            api.Stage(
                "Shotcrete · %70",
                active_regions={1},
                active_structures={"shotcrete"},
                load_split=0.5,
            ),
            api.Stage(
                "Bolt · tam kazı", active_regions={1}, active_structures={"shotcrete", "bolt"}
            ),
        ],
        liners={
            "shotcrete": api.LinerSpec("shotcrete", 3e7, 0.2, 0.2, 0.2**3 / 12, 0.2 * 5 / 6, 0)
        },
        bolts={"bolt": api.BoltSpec("bolt", 200000.0, 200.0, 0.0, 1.0)},
    )

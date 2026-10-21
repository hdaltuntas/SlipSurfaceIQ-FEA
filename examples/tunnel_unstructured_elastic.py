"""Shallow circular tunnel in two layers on an unstructured Delaunay/Ruppert mesh.

Elastic: gravity initial stress with the opening present, then a surface surcharge.
(Excavation by element deactivation arrives with staged construction in Faz 3.)
Run:  python examples/tunnel_unstructured_elastic.py   ->  writes tunnel.vtu
"""

from __future__ import annotations

import numpy as np

from slipsurface.fe2d import api
from slipsurface.fe2d.mesh import DistanceSize, Domain, circle, mesh_quality, unstructured_mesh

R, ZC = 4.0, -15.0  # tunnel radius and axis depth [m]
ring = circle(0.0, ZC, R, 64)

d = Domain()
d.add_polygon(
    [(-40, -50), (40, -50), (40, 0), (-40, 0)],
    region=2,
    edge_names=["bottom", "right", "top", "left"],
)
d.add_polygon([(-40, -6), (40, -6), (40, 0), (-40, 0)], region=1)  # upper layer
d.add_polygon(ring, hole=True, name="tunnel")
d.add_point(0.0, 0.0, "surface_axis")

mesh = unstructured_mesh(d, h=DistanceSize(0.4, 4.0, 1.25, lines=[ring], closed=[True]))
print(f"{mesh.nn} nodes, {mesh.blocks[0].ne} T6 elements")
print(mesh_quality(mesh))

model = api.Model(
    analysis=api.Analysis.PLANE_STRAIN,
    mesh=mesh,
    materials={
        "fill": api.MaterialSpec.elastic("fill", E=2.0e4, nu=0.30, gamma=19.0),
        "rock": api.MaterialSpec.elastic("rock", E=2.0e5, nu=0.25, gamma=22.0),
    },
    region_material={1: "fill", 2: "rock"},
    fixities=(
        api.Fixity("bottom", True, True),
        api.Fixity("left", True, False),
        api.Fixity("right", True, False),
    ),
    initial=api.InitialStress("gravity"),
    stages=[api.Stage("surcharge", loads=(api.EdgeLoad("top", qn=50.0),))],
)

res = api.run(model)
u = res.last.u
crown = int(np.argmin(np.hypot(mesh.coords[:, 0], mesh.coords[:, 1] - (ZC + R))))
surf = int(mesh.nodes("surface_axis")[0])
print(f"crown settlement (surcharge):   {-u[crown, 1] * 1000:.2f} mm")
print(f"surface settlement (surcharge): {-u[surf, 1] * 1000:.2f} mm")
api.export_vtu(res, "tunnel.vtu")
print("wrote tunnel.vtu")

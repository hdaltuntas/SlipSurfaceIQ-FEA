"""Elastic strip footing on two horizontal layers (Faz 1 example).

Run:  python examples/strip_footing_elastic.py   ->  writes strip_footing.vtu
"""

from __future__ import annotations

import numpy as np

from slipsurface.fe2d import api
from slipsurface.fe2d.mesh import layered_box

# 30 m wide half-space model, sand over clay, footing B/2 = 1.5 m on the symmetry axis
mesh = layered_box(30.0, [0.0, -4.0], -20.0, nx=60, ny_per_layer=[8, 24])
top_edges = mesh.edges("top")
footing = top_edges[mesh.coords[top_edges[:, 1], 0] <= 1.5 + 1e-9]
mesh = api.Mesh(mesh.coords, mesh.blocks, mesh.node_sets, {**mesh.edge_sets, "footing": footing})

model = api.Model(
    analysis=api.Analysis.PLANE_STRAIN,
    mesh=mesh,
    materials={
        "sand": api.MaterialSpec.elastic("sand", E=4.0e4, nu=0.30, gamma=19.0),
        "clay": api.MaterialSpec.elastic("clay", E=1.2e4, nu=0.35, gamma=18.0),
    },
    region_material={1: "sand", 2: "clay"},
    fixities=(
        api.Fixity("bottom", True, True),
        api.Fixity("left", True, False),  # symmetry axis
        api.Fixity("right", True, False),
    ),
    initial=api.InitialStress("k0_field"),
    stages=[
        api.Stage("1. Öz ağırlık", reset_displacements=True),
        api.Stage("2. Şerit temel (150 kPa)", loads=(api.EdgeLoad("footing", qn=150.0),)),
    ],
)

res = api.run(model)
u0, u1 = res.stages[0].u, res.stages[1].u
centre = int(np.argmin(np.hypot(*mesh.coords.T)))
print(f"K0 correction at centre: {-u0[centre, 1] * 1000:.2f} mm")
print(f"settlement under footing centre after 150 kPa: {-u1[centre, 1] * 1000:.1f} mm")
print(f"timings: {res.initial.timings | res.last.timings}")
api.export_vtu(res, "strip_footing.vtu")
print("wrote strip_footing.vtu")

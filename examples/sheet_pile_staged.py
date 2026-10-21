"""Staged cantilever sheet pile in sand (Faz 3 example; the S4 verification model).

Stages: K0 initial stress -> wall + interfaces installed (wished in place) -> excavation
lift 1 (2 m) -> lift 2 (4 m). Writes the project with results (wall.ssproj) and a VTU of
the last stage, and prints the wall's maximum bending moment.

Run:  python examples/sheet_pile_staged.py
"""

from __future__ import annotations

import numpy as np

from slipsurface.fe2d import api
from slipsurface.fe2d.mesh import DistanceSize, Domain, unstructured_mesh
from slipsurface.fe2d.mesh.structures import add_beams, insert_interface

H, D = 4.0, 6.0  # retained height, embedment [m]
wall = np.array([[0.0, 0.0], [0.0, -(H + D)]])

d = Domain()
d.add_polygon([(-25, -22), (25, -22), (25, 0), (-25, 0)], 1,
              edge_names=["bottom", "right", "top", "left"])  # fmt: skip
d.add_polygon([(-25, -2), (0, -2), (0, 0), (-25, 0)], 2)  # lift 1
d.add_polygon([(-25, -4), (0, -4), (0, -2), (-25, -2)], 3)  # lift 2
d.add_line(wall, name="wall")
mesh = unstructured_mesh(d, h=DistanceSize(0.5, 2.5, 1.2, lines=[wall]))
mesh = add_beams(mesh, "wall", "wall")  # BEAM2 elements on the wall line
mesh = insert_interface(mesh, "wall", "ifL", side="left")  # joints on both faces
mesh = insert_interface(mesh, "wall", "ifR", side="right")

sand = api.MaterialSpec.mohr_coulomb("sand", E=3e4, nu=0.3, c=1.0, phi=30.0, psi=0.0,
                                     gamma=18.0)  # fmt: skip
E_steel, EI, EA = 2.1e8, 4.2e4, 3.4e6
S = frozenset({"wall", "ifL", "ifR"})
model = api.Model(
    analysis=api.Analysis.PLANE_STRAIN,
    mesh=mesh,
    materials={"sand": sand},
    region_material={1: "sand", 2: "sand", 3: "sand"},
    fixities=(
        api.Fixity("bottom", True, True),
        api.Fixity("left", True, False),
        api.Fixity("right", True, False),
    ),
    # no structure active in the K0 stage: the interfaces are tied (full continuity)
    initial=api.InitialStress("k0_field", active_structures=frozenset()),
    stages=[
        api.Stage("install", active_structures=S),
        api.Stage("lift1", active_regions={1, 3}, active_structures=S),
        api.Stage("lift2", active_regions={1}, active_structures=S),
    ],
    liners={
        "wall": api.LinerSpec("wall", E_steel, 0.0, EA / E_steel, EI / E_steel, 0.5 * EA / E_steel)
    },  # fmt: skip
    interfaces={
        k: api.InterfaceSpec.from_soil(k, sand, R=0.67, R_stiffness=1.0) for k in ("ifL", "ifR")
    },  # fmt: skip
    settings=api.SolverSettings(line_search=True),
)

res = api.run(model)
for st in res.stages:
    print(f"{st.name:8s} steps {st.history.n_steps:3d}  iterations {st.history.n_iterations:4d}")
blk = mesh.block("wall")
M = res.last.beams["wall"][:, :, 2]  # (element, end, [N, V, M])
y = mesh.coords[blk.conn, 1]
i = np.unravel_index(np.abs(M).argmax(), M.shape)
head = blk.conn[int(np.argmax(y[:, 0])), 0]
print(f"M_max = {np.abs(M).max():.1f} kNm/m at y = {y[i]:.2f} m")
print(f"wall head displacement = {res.last.u[head, 0] * 1000:.1f} mm")
api.save_project("wall.ssproj", model, res)
api.export_vtu(res, "wall_lift2.vtu")
print("wrote wall.ssproj, wall_lift2.vtu")

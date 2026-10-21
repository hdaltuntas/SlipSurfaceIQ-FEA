"""P1 — smooth rigid strip footing on undrained clay (phi = 0), Prandtl.

Weightless Tresca soil (Mohr-Coulomb, phi = psi = 0, c = su). Half model, displacement
controlled: the footing nodes are pushed down (ux free = smooth). The mean contact
pressure must reach the plateau q_ult = (2 + pi) su. The mesh is graded towards the
footing edge (stress singularity).

Measured plateau error (T6): h_min = 0.1 → +1.35 %, 0.05 → +0.97 %, 0.025 → +0.53 %
(converging from above). Criterion: < 3 %.
"""

from __future__ import annotations

import numpy as np

from slipsurface.fe2d import api
from slipsurface.fe2d.mesh import DistanceSize, Domain, unstructured_mesh

SU, B2 = 10.0, 1.0


def test_prandtl_bearing_capacity():
    d = Domain().add_polygon(
        [(0, -5), (10, -5), (10, 0), (B2, 0), (0, 0)],
        edge_names=["bottom", "right", "surface", "footing", "axis"],
    )
    mesh = unstructured_mesh(d, h=DistanceSize(0.05, 1.0, 1.2, points=np.array([[B2, 0.0]])))
    deltas = [0.01, 0.02, 0.04, 0.07, 0.1, 0.15, 0.2]
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"clay": api.MaterialSpec.mohr_coulomb("clay", 1e4, 0.3, SU, 0.0, 0.0)},
        region_material={1: "clay"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("right", True, False),
            api.Fixity("axis", True, False),
        ),
        initial=api.InitialStress("none"),
        stages=[
            api.Stage(f"d{i}", displacements=(api.Displacement("footing", uy=-dl),))
            for i, dl in enumerate(deltas)
        ],
    )
    res = api.run(model)
    fn = mesh.nodes("footing")
    q = np.array([-st.reactions[fn, 1].sum() / B2 for st in res.stages])
    q_ult = (2 + np.pi) * SU
    assert np.all(np.diff(q) > -1e-6 * q_ult)  # monotonic load-settlement curve
    assert abs(q[-1] - q_ult) / q_ult < 0.03, f"q/su = {q[-1] / SU:.4f}"
    assert abs(q[-1] - q[-3]) / q_ult < 1e-3  # plateau reached
    # smooth footing: no horizontal reaction (except on the symmetry axis)
    off_axis = fn[mesh.coords[fn, 0] > 1e-9]
    assert np.allclose(res.last.reactions[off_axis, 0], 0.0)

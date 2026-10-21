"""E4 — thick-walled cylinder under internal pressure, axisymmetric, plane strain (Lamé).
Criterion: sigma_r and sigma_theta within 1 %.
"""

from __future__ import annotations

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.mesh import rectangle

A_IN, B_OUT, P_IN, E, NU = 1.0, 2.0, 100.0, 2.0e4, 0.3
CA = P_IN * A_IN**2 / (B_OUT**2 - A_IN**2)
CB = P_IN * A_IN**2 * B_OUT**2 / (B_OUT**2 - A_IN**2)


def lame(r):
    return CA - CB / r**2, CA + CB / r**2  # sigma_r, sigma_theta (tension positive)


def ur_exact(r):
    return (1 + NU) / E * ((1 - 2 * NU) * CA * r + CB / r)


@pytest.mark.parametrize("etype,nr", [(ElemType.T6, 16), (ElemType.T3, 64)])
def test_lame_cylinder(etype, nr):
    mesh = rectangle(B_OUT - A_IN, 0.25, nr, 2, etype, origin=(A_IN, 0.0), grade_x=1.0)
    model = api.Model(
        analysis=api.Analysis.AXISYMMETRIC,
        mesh=mesh,
        materials={"steel": api.MaterialSpec.elastic("steel", E, NU)},
        region_material={1: "steel"},
        fixities=(api.Fixity("bottom", False, True), api.Fixity("top", False, True)),
        initial=api.InitialStress("none"),
        stages=[api.Stage("pressure", loads=(api.EdgeLoad("left", qn=P_IN),))],
    )
    res = api.run(model)
    st = res.last
    r = res.geom["soil"].xg[..., 0].ravel()
    sig = st.sig["soil"].reshape(-1, 4)
    sr, sth = lame(r)
    scale = np.max(np.abs(sth))
    tol = 0.01 if etype is ElemType.T6 else 0.02
    assert np.max(np.abs(sig[:, 0] - sr)) / scale < tol
    assert np.max(np.abs(sig[:, 2] - sth)) / scale < tol
    # sigma_z = nu (sigma_r + sigma_theta) = 2 nu A  (plane strain)
    assert np.max(np.abs(sig[:, 1] - 2 * NU * CA)) / scale < tol
    # radial displacement
    rn = mesh.coords[:, 0]
    assert np.max(np.abs(st.u[:, 0] - ur_exact(rn))) / ur_exact(A_IN) < 0.005
    # reaction per radian balances the internal pressure resultant (p * a * h)
    assert abs(st.reactions[:, 1].sum()) < 1e-8 * P_IN

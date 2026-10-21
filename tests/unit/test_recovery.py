from __future__ import annotations

import numpy as np
import pytest

from slipsurface.fe2d.core.enums import Analysis, ElemType
from slipsurface.fe2d.fem.elements import kernel
from slipsurface.fe2d.mesh import Domain, plate_with_hole, rectangle, unstructured_mesh
from slipsurface.fe2d.post.recovery import boundary_nodes, nodal_average, spr


def _field(x, y, deg):
    if deg == 1:
        return np.stack([1 + 2 * x - 3 * y, 0.5 * x, y, x + y], -1)
    return np.stack([1 + 2 * x - 3 * y + x * x, 0.5 * x * y, y * y - x, x + y * y], -1)


MESHES = {
    "rect": lambda et: rectangle(3.0, 2.0, 9, 6, et),
    "hole": lambda et: plate_with_hole(1.0, 4.0, 6, 12, et),
}


@pytest.mark.parametrize("etype,deg", [(ElemType.T3, 1), (ElemType.Q4, 1), (ElemType.T6, 2),
                                       (ElemType.Q8, 2)])  # fmt: skip
@pytest.mark.parametrize("which", list(MESHES))
def test_spr_reproduces_polynomials_of_element_order(etype, deg, which):
    m = MESHES[which](etype)
    g = kernel(etype).precompute(m.coords, m.blocks[0].conn, Analysis.PLANE_STRAIN)
    v = _field(g.xg[..., 0], g.xg[..., 1], deg)
    r = spr(m, {"soil": v}, {"soil": g.xg}, boundary="spr")
    ex = _field(m.coords[:, 0], m.coords[:, 1], deg)
    assert np.abs(r - ex).max() < 1e-9


def test_spr_unstructured_t6_and_region_patches():
    d = Domain().add_polygon([(0, 0), (3, 0), (3, 2), (0, 2)], 1)
    d.add_polygon([(0, 1), (3, 1), (3, 2), (0, 2)], 2)
    m = unstructured_mesh(d, h=0.3)
    b = m.blocks[0]
    g = kernel(ElemType.T6).precompute(m.coords, b.conn, Analysis.PLANE_STRAIN)
    v = _field(g.xg[..., 0], g.xg[..., 1], 2)
    # a jump between the regions must not be smeared into the interiors
    v = v + (b.region == 2)[:, None, None] * 10.0
    r = spr(m, {"soil": v}, {"soil": g.xg})
    ex = _field(m.coords[:, 0], m.coords[:, 1], 2)
    y = m.coords[:, 1]
    away = np.abs(y - 1.0) > 0.4
    inner = np.setdiff1d(np.flatnonzero(away), boundary_nodes(m))
    jump = (y[inner] > 1.0) * 10.0
    assert np.abs(r[inner] - ex[inner] - jump[:, None]).max() < 1e-8


def test_boundary_nodes():
    m = rectangle(2.0, 1.0, 4, 2, ElemType.T6)
    bn = boundary_nodes(m)
    expected = np.unique(np.concatenate([m.nodes(k) for k in ("left", "right", "top", "bottom")]))
    assert np.array_equal(bn, expected)


def test_spr_not_worse_than_average_on_kirsch_t6():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parents[1] / "verification"))
    import test_e3_kirsch as K

    from slipsurface.fe2d import api
    from slipsurface.fe2d.fem.static import StaticSolver

    mesh = plate_with_hole(K.A_HOLE, 5.0, 12, 24, ElemType.T6, grade=6.0)
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"r": api.MaterialSpec.elastic("r", 1e4, 0.25)},
        region_material={1: "r"},
        fixities=(api.Fixity("x_sym", False, True), api.Fixity("y_sym", True, False)),
        initial=api.InitialStress("none"),
        stages=[api.Stage("remote")],
    )
    res = StaticSolver(
        model, extra_tractions={"remote": (("outer_x", K.traction), ("outer_y", K.traction))}
    ).run()
    ex = np.column_stack(K.kirsch_cart(*mesh.coords.T))
    e_avg = nodal_average(mesh, res.last.sig)[:, [0, 1, 3]] - ex
    e_spr = api.nodal_stress(res)[:, [0, 1, 3]] - ex
    assert np.sqrt((e_spr**2).mean()) < 0.85 * np.sqrt((e_avg**2).mean())
    assert np.abs(e_spr).max() <= np.abs(e_avg).max() + 1e-12

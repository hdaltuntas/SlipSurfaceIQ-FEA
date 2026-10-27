from __future__ import annotations

import numpy as np
import pytest

pv = pytest.importorskip("pyvista", exc_type=ImportError)


def test_to_pyvista_fields():
    from slipsurface.fe2d import api
    from slipsurface.fe2d.gui import to_pyvista
    from slipsurface.fe2d.mesh import rectangle

    for et in (api.ElemType.T6, api.ElemType.Q8):
        mesh = rectangle(2.0, 1.0, 4, 2, et)
        model = api.Model(
            analysis=api.Analysis.PLANE_STRAIN,
            mesh=mesh,
            materials={"m": api.MaterialSpec.mohr_coulomb("m", 1e4, 0.3, 5.0, 20.0)},
            region_material={1: "m"},
            fixities=(api.Fixity("bottom", True, True),),
            initial=api.InitialStress("none"),
            stages=[api.Stage("q", loads=(api.EdgeLoad("top", qn=12.0),))],
        )
        res = api.run(model)
        g = to_pyvista(res, deform=10.0)
        assert g.n_points == mesh.nn and g.n_cells == mesh.blocks[0].ne
        for f in ("u", "s1", "q", "eps_p"):
            assert f in g.point_data
        assert "plastic" in g.cell_data
        assert np.isfinite(g.point_data["s1"]).all()

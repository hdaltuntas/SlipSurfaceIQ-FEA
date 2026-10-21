"""Inactive historical Gauss data must not leak into current-stage results."""

import os
from dataclasses import replace

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.fem.elements import kernel
from slipsurface.fe2d.fem.static import SolveResult, StageResult
from slipsurface.fe2d.mesh import rectangle


def result_with_excavation(family="T6", empty=False):
    mesh = rectangle(4, 2, 8, 4, getattr(api.ElemType, family.split("+")[0]))
    geom, sig, q, flags, active = {}, {}, {}, {}, {}
    used = np.zeros(mesh.nn, dtype=bool)
    for b in mesh.blocks:
        g = kernel(b.etype).precompute(mesh.coords, b.conn, api.Analysis.PLANE_STRAIN)
        geom[b.tag] = g
        mask = mesh.coords[b.conn, 0].mean(axis=1) < 2
        if empty:
            mask[:] = False
        active[b.tag] = mask
        used[b.conn[mask]] = True
        sig[b.tag] = np.broadcast_to([10.0, 20.0, 30.0, 0.0], (b.ne, g.ngp, 4)).copy()
        sig[b.tag][~mask] = 1e6  # retained history of removed elements
        q[b.tag] = np.full((b.ne, g.ngp, 1), 0.01)
        q[b.tag][~mask] = 100
        flags[b.tag] = np.where(mask[:, None], np.zeros((b.ne, g.ngp)), 1).astype(np.uint8)
    u = np.zeros((mesh.nn, 2))
    u[~used] = np.nan
    st = StageResult("excavated", u, sig, np.zeros((mesh.nn, 3)), q=q, plastic=flags, active=active)
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"soil": api.MaterialSpec.elastic("soil", 1e4, 0.3)},
        region_material={1: "soil"},
    )
    return SolveResult(model, geom, st, [st]), used


@pytest.mark.parametrize("family", ["T3", "T6", "Q4", "Q8"])
@pytest.mark.parametrize("method", ["spr", "average"])
def test_recovery_ignores_excavated_history(family, method):
    result, used = result_with_excavation(family)
    originals = {k: v.copy() for k, v in result.last.sig.items()}
    recovered = api.nodal_stress(result, method=method)
    np.testing.assert_allclose(recovered[used], np.tile([10.0, 20.0, 30.0, 0.0], (used.sum(), 1)))
    assert np.isnan(recovered[~used]).all()
    for k, v in originals.items():
        np.testing.assert_array_equal(result.last.sig[k], v)


def test_empty_stage_recovery_has_no_invented_stress():
    result, _ = result_with_excavation(empty=True)
    assert np.isnan(api.nodal_stress(result)).all()
    result.stages = [replace(result.last, sig={}, q={}, plastic={})]
    assert api.nodal_stress(result).shape == (result.model.mesh.nn, 4)
    assert np.isnan(api.nodal_stress(result)).all()


def test_loaded_stages_keep_distinct_active_sets(tmp_path):
    result, used = result_with_excavation()
    full = replace(result.last, name="before", active={})  # legacy default: all active
    result.stages.insert(0, full)
    loaded = api.read_results(api.write_results(result, tmp_path / "stages.h5"), result.model)
    np.testing.assert_allclose(api.nodal_stress(loaded, "excavated")[used, 0], 10)
    assert np.isnan(api.nodal_stress(loaded, 1)[~used]).all()
    assert np.isfinite(api.nodal_stress(loaded, "before")[~used]).all()
    for tag in loaded.last.sig:
        np.testing.assert_array_equal(loaded.last.sig[tag], result.last.sig[tag])


@pytest.mark.parametrize("empty", [False, True])
def test_vtu_contains_only_active_cells_and_preserves_missing_fields(tmp_path, empty):
    import base64
    import xml.etree.ElementTree as ET

    result, used = result_with_excavation(empty=empty)
    p = api.export_vtu(result, tmp_path / "excavated.vtu")
    piece = ET.parse(p).getroot().find("UnstructuredGrid/Piece")
    assert int(piece.get("NumberOfCells")) == sum(a.sum() for a in result.last.active.values())
    for name, val in [("sxx", 10), ("eps_p", 0.01)]:
        node = piece.find(f"PointData/DataArray[@Name='{name}']")
        data = np.frombuffer(base64.b64decode(node.text)[8:], dtype=np.float64)
        np.testing.assert_allclose(data[used], val)
        assert np.isnan(data[~used]).all()


@pytest.mark.parametrize("empty", [False, True])
def test_pyvista_uses_stage_topology_and_fields(empty):
    pytest.importorskip("pyvista")
    from slipsurface.fe2d.gui import to_pyvista

    result, used = result_with_excavation(empty=empty)
    grid = to_pyvista(result)
    assert grid.n_cells == sum(a.sum() for a in result.last.active.values())
    np.testing.assert_allclose(grid.point_data["sxx"][used], 10)
    np.testing.assert_allclose(grid.point_data["eps_p"][used], 0.01)
    assert np.isnan(grid.point_data["sxx"][~used]).all()
    assert np.isnan(grid.point_data["|u|"][~used]).all()
    assert not grid.cell_data["plastic"].any()


@pytest.mark.skipif(
    os.environ.get("SLIPSURFACE_RENDER_TESTS") != "1",
    reason="set SLIPSURFACE_RENDER_TESTS=1 with a working off-screen renderer or Xvfb",
)
def test_show_result_writes_screenshot(tmp_path):
    pytest.importorskip("pyvista")
    from slipsurface.fe2d.gui import show_result

    result, _ = result_with_excavation()
    path = tmp_path / "stage.png"
    assert show_result(result, "sxx", screenshot=str(path)) == str(path)
    assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")

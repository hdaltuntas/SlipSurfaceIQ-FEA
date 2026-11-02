"""Result views must preserve categorical states, node identity and excavation gaps."""

import numpy as np
import pytest

pytest.importorskip("PySide6")

from slipsurface.fe2d import api
from slipsurface.fe2d.fem.elements import kernel
from slipsurface.fe2d.gui.canvas import MeshCanvas, _block_nodal
from slipsurface.fe2d.gui.result_tools import (
    StructureDisplacementDialog,
    StructureForceDialog,
    segment_end_displacements,
    structure_segments,
)
from slipsurface.fe2d.mesh import Domain, rectangle, unstructured_mesh
from slipsurface.fe2d.mesh.structures import add_bar, add_beams, insert_interface
from slipsurface.fe2d.post.inspection import line_profile


@pytest.mark.parametrize(
    "etype", [api.ElemType.T3, api.ElemType.T6, api.ElemType.Q4, api.ElemType.Q8]
)
@pytest.mark.parametrize("flag", [1, 2, 3, "mixed"])
def test_plastic_fraction_counts_yielding_points_without_extrapolating_codes(etype, flag):
    mesh = rectangle(2, 1, 2, 1, etype)
    block = mesh.blocks[0]
    geom = kernel(etype).precompute(mesh.coords, block.conn, api.Analysis.PLANE_STRAIN)
    flags = np.zeros((block.ne, geom.ngp), dtype=np.uint8)
    flags[:] = np.arange(geom.ngp) % 4 if flag == "mixed" else flag
    stage = api.StageResult("test", np.zeros((mesh.nn, 2)), {}, np.zeros((mesh.nn, 3)),
                            plastic={block.tag: flags})
    values = _block_nodal(stage, block, "plastic")
    expected = np.broadcast_to((flags > 0).mean(axis=1)[:, None], values.shape)
    np.testing.assert_allclose(values, expected)
    assert values.min() >= 0 and values.max() <= 1


def interface_result(kind):
    domain = Domain().add_polygon([(0, 0), (2, 0), (2, 2), (0, 2)], 1)
    domain.add_line([(1, 0), (1, 2)], "wall")
    mesh = insert_interface(unstructured_mesh(domain, h=0.8), "wall", "joint", side="left")
    if kind == "beam":
        mesh = add_beams(mesh, "joint:face2", "support")
    else:
        edge = mesh.edges("joint:face2")[0]
        mesh = add_bar(mesh, int(edge[0]), int(edge[1]), "support")
    block = mesh.block("support")
    u = np.zeros((mesh.nn, 2))
    u[np.unique(block.conn), 0] = 0.1  # independent displacement on the duplicated face
    stage = api.StageResult(
        "slip", u, {}, np.zeros((mesh.nn, 3)),
        active={block.tag: np.ones(block.ne, bool)},
        beams={block.tag: np.ones((block.ne, 2, 3))} if kind == "beam" else {},
        bars={block.tag: np.ones(block.ne)} if kind == "bar" else {},
    )
    model = api.Model(api.Analysis.PLANE_STRAIN, mesh,
                      {"s": api.MaterialSpec.elastic("s", 20000, 0.3)}, {1: "s"})
    return api.SolveResult(model, {}, stage, [stage])


@pytest.mark.parametrize("kind", ["beam", "bar"])
def test_structure_displacements_use_connectivity_not_nearest_coordinates(kind):
    result = interface_result(kind)
    _, segments = structure_segments(result, result.last, "support")
    _, magnitude, ux, uy = segment_end_displacements(result, result.last, segments)
    np.testing.assert_allclose(ux, 0.1)
    np.testing.assert_allclose(magnitude, 0.1)
    np.testing.assert_allclose(uy, 0)


@pytest.mark.parametrize("kind", ["beam", "bar"])
def test_force_overlay_follows_the_deformed_structure_face(qt_app, kind):
    result = interface_result(kind)
    canvas = MeshCanvas()
    canvas.show_model(result.model, result.last, "N", deform=10, result=result)
    bands = [item for item in canvas.scene().items()
             if hasattr(item, "polygon") and item.data(0) == ("structure", "support")]
    assert bands
    # The member is originally at x=1; only its own interface face moves to x=2.
    for band in bands:
        assert band.polygon()[0].x() == pytest.approx(2.0)
        assert band.polygon()[-1].x() == pytest.approx(2.0)


@pytest.mark.parametrize("kind", ["beam", "bar"])
def test_structure_dialogs_show_the_matching_face_values(qt_app, tmp_path, kind):
    result = interface_result(kind)
    dialog = StructureForceDialog(result, 1, "support")
    assert dialog._has_forces(1)
    np.testing.assert_allclose(dialog.disp_plots[1].y, 0.1)
    assert dialog.diagram.extremes() is not None
    dialog.show()
    qt_app.processEvents()
    assert dialog.diagram.grab().save(str(tmp_path / "forces.png"))
    dialog.close()
    if kind == "beam":
        displacements = StructureDisplacementDialog(result, 1)
        np.testing.assert_allclose(displacements.plots[1].y, 0.1)
        displacements.close()


@pytest.mark.parametrize("deform", [0, 10])
def test_query_overlay_breaks_across_excavation(qt_app, deform):
    mesh = rectangle(3, 1, 3, 1, api.ElemType.Q4)
    block = mesh.blocks[0]
    model = api.Model(api.Analysis.PLANE_STRAIN, mesh,
                      {"s": api.MaterialSpec.elastic("s", 20000, 0.3)}, {1: "s"})
    stage = api.StageResult(
        "excavation", np.tile([0, 0.1], (mesh.nn, 1)), {}, np.zeros((mesh.nn, 3)),
        active={block.tag: np.array([True, False, True])},
    )
    result = api.SolveResult(model, {}, stage, [stage])
    profile = line_profile(result, (0, 0.5), (3, 0.5), "uy", 13, deform=deform)
    missing = ~np.isfinite(profile.values)
    assert missing.any()
    assert np.isnan(profile.display_xy[missing]).all()
    np.testing.assert_allclose(profile.display_xy[~missing, 1], 0.5 + deform * 0.1)
    canvas = MeshCanvas()
    canvas.show_query_line(profile.display_xy)
    path = canvas.query_item.path()
    assert sum(path.elementAt(i).isMoveTo() for i in range(path.elementCount())) == 2

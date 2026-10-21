"""Native boundaries, interface topology, and stage-aware graphic overlays."""

import os
from dataclasses import replace

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from slipsurface.fe2d import api
from slipsurface.fe2d.gui.boundary_editor import BoundaryDialog
from slipsurface.fe2d.gui.canvas import MeshCanvas
from slipsurface.fe2d.gui.dialogs import sample_model
from slipsurface.fe2d.gui.editing import remove_interface
from slipsurface.fe2d.gui.stage_editor import StageDetailDialog
from slipsurface.fe2d.gui.structure_editor import InterfaceDialog
from slipsurface.fe2d.mesh import Domain, unstructured_mesh
from slipsurface.fe2d.model.boundary import Displacement


def test_boundary_and_stage_displacement_are_transactional(qt_app):
    model = sample_model(nx=1, ny=1)
    form = BoundaryDialog(model)
    form.table.cellWidget(0, 1).setChecked(False)
    form.displacements.add(Displacement("top", uy=-0.01))
    form.apply()
    assert not form.updated.fixities[0].ux and model.fixities[0].ux
    assert form.updated.displacements == (Displacement("top", uy=-0.01),)
    stage = StageDetailDialog(form.updated, 0)
    stage.displacements.add(Displacement("top", uy=-0.02))
    stage.apply()
    assert stage.updated.displacements == (Displacement("top", uy=-0.02),)
    rejected = BoundaryDialog(model)
    rejected.displacements.add(Displacement("top", ux=float("nan")))
    rejected.apply()
    assert rejected.updated is None and rejected.status.text()


def test_interface_editor_and_weld_restore_the_original_solution(qt_app):
    domain = Domain().add_polygon(
        [(0, 0), (2, 0), (2, 2), (0, 2)], 1, edge_names=["bottom", "right", "top", "left"]
    )
    domain.add_line([(1, 0), (1, 2)], "jointline")
    mesh = unstructured_mesh(domain, h=0.6)
    source = replace(sample_model(nx=1, ny=1), mesh=mesh)
    form = InterfaceDialog(source)
    form.edge.setCurrentText("jointline")
    form.apply()
    assert form.updated is not None, form.status.text()
    assert form.updated.mesh.nn > source.mesh.nn
    assert "joint" not in source.interfaces
    edited = InterfaceDialog(form.updated, "joint")
    edited.fields["kn"].setText("2e6")
    edited.apply()
    assert edited.updated.interfaces["joint"].kn == 2e6
    restored = remove_interface(edited.updated, "joint")
    assert not restored.interfaces and not restored.structure_tags()
    a, b = api.run(source), api.run(restored)
    np.testing.assert_allclose(a.last.u, b.last.u[: source.mesh.nn], rtol=1e-10, atol=1e-12)
    assert np.isnan(b.last.u[source.mesh.nn :]).all()


def test_plastic_gp_overlay_uses_active_gauss_points(qt_app):
    result = api.run(sample_model(nx=2, ny=2))
    flags = np.ones_like(result.last.plastic["soil"])
    active = np.ones(len(flags), bool)
    active[0] = False
    stage = replace(result.last, plastic={"soil": flags}, active={"soil": active})
    canvas = MeshCanvas()
    canvas.show_model(result.model, stage, result=result, principal=True, plastic_points=True)
    assert canvas.plastic_count == flags[active].size
    assert canvas.principal_count == 2 * flags[active].size
    canvas.show_model(result.model)
    assert canvas.plastic_count == canvas.principal_count == 0

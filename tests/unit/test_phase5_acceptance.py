"""Gate 5: blank native CAD -> four-state tunnel -> solve, inspect, save/reopen."""

import os
from dataclasses import replace

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("shapely")
pytest.importorskip("ezdxf")
from PySide6.QtCore import Qt

from slipsurface.fe2d import api
from slipsurface.fe2d.gui.app import MainWindow
from slipsurface.fe2d.gui.cad import CadDialog
from slipsurface.fe2d.gui.demo import tunnel_model, tunnel_points
from slipsurface.fe2d.gui.material_editor import MaterialDialog
from slipsurface.fe2d.gui.result_tools import BeamDiagramDialog, QueryDialog
from slipsurface.fe2d.gui.stage_editor import InitialDialog, StageDialog
from slipsurface.fe2d.gui.structure_editor import StructureSpecDialog


def test_four_state_tunnel_from_blank_native_controls(qt_app, tmp_path):
    from test_cad_desktop import finish as finish_mesh
    from test_desktop import finish

    cad = CadDialog()
    outer, ring = tunnel_points()
    for name, kind, region, points in [
        ("Rock", "region", 1, outer),
        ("Tunnel", "region", 2, ring),
        ("CrownBolt", "line", 1, [(0, 3), (0, 7)]),
    ]:
        cad.name.setText(name)
        cad.kind.setCurrentIndex(cad.kind.findData(kind))
        cad.region.setValue(region)
        cad.coordinates.setPlainText("\n".join(f"{x:.17g} {y:.17g}" for x, y in points))
        cad.add_from_text()
    assert len(cad.document.entities) == 3, cad.status.text()
    for i in range(4):
        for j in (1, 2):
            cad.conditions.item(i, j).setCheckState(Qt.CheckState.Checked)
    cad.values["h"].setValue(2.0)
    cad.values["E"].setValue(50000.0)
    cad.values["nu"].setValue(0.25)
    cad.start_mesh()
    finish_mesh(cad, qt_app)
    assert cad.updated is not None, cad.status.text()
    materials = MaterialDialog(cad.updated)
    materials.store_material(replace(cad.updated.materials["soil"], name="rock"), "soil")
    materials.apply()
    model = materials.updated
    for name, kind, edge in [("shotcrete", 0, "Tunnel"), ("bolt", 1, "CrownBolt")]:
        dialog = StructureSpecDialog(model)
        dialog.name.setText(name)
        dialog.kind.setCurrentIndex(kind)
        dialog.edge.setCurrentText(edge)
        if kind == 0:
            dialog.fields["unit_weight"].setText("0")
        dialog.apply()
        assert dialog.updated is not None, dialog.status.text()
        model = dialog.updated
    initial = InitialDialog(model)
    initial.mode.setCurrentIndex(initial.mode.findData("field"))
    for edit, value in zip(initial.stress, [-300.0, -600.0, -225.0, 0.0]):
        edit.setText(str(value))
    initial.structures.setText("")
    initial.apply()
    assert initial.updated is not None, initial.status.text()
    stages = StageDialog(replace(model, initial=initial.updated))
    stages.table.item(0, 0).setText("%40 gevşeme")
    stages.table.item(0, 1).setText(".4")
    stages.table.item(0, 3).setText("1")
    stages.copy_stage()
    stages.table.item(1, 0).setText("Shotcrete · %70")
    stages.table.item(1, 1).setText(".5")
    stages.table.item(1, 4).setText("shotcrete")
    stages.copy_stage()
    stages.table.item(2, 0).setText("Bolt · tam kazı")
    stages.table.item(2, 1).setText("1")
    stages.table.item(2, 4).setText("shotcrete,bolt")
    stages.apply()
    assert stages.updated is not None, stages.status.text()
    assert len(stages.timeline.cards) == 4
    expected_model = tunnel_model()
    np.testing.assert_array_equal(stages.updated.mesh.coords, expected_model.mesh.coords)
    for actual, expected in zip(stages.updated.mesh.blocks, expected_model.mesh.blocks):
        np.testing.assert_array_equal(actual.conn, expected.conn)
    window = MainWindow()
    window.set_model(stages.updated)
    window.start_solve()
    finish(window, qt_app, timeout=60)
    assert window.result is not None, window.log.toPlainText()
    direct = api.run(expected_model)
    for actual, expected in zip(
        [window.result.initial, *window.result.stages], [direct.initial, *direct.stages]
    ):
        np.testing.assert_allclose(actual.u, expected.u, rtol=0, atol=0, equal_nan=True)
        for field in ("sig", "beams", "bars", "pore", "plastic", "active"):
            for tag, values in getattr(expected, field).items():
                np.testing.assert_allclose(
                    getattr(actual, field)[tag], values, rtol=0, atol=0, equal_nan=True
                )
    assert not window.result.stages[0].active["shotcrete"].any()
    assert window.result.stages[1].active["shotcrete"].all()
    assert not window.result.stages[1].active["bolt"].any()
    assert window.result.last.active["bolt"].all()
    assert np.linalg.norm(window.result.last.u[np.isfinite(window.result.last.u)]) > 0
    window.principal.setChecked(True)
    assert window.canvas.principal_count > 0
    query = QueryDialog(window.result, window.result.last)
    query.start.setText("-10, 0")
    query.end.setText("10, 0")
    query.query()
    assert np.isnan(query.profile.values[50])  # excavated core: no fabricated interpolation
    assert np.isfinite(query.profile.values[[0, -1]]).all()
    query.export_path(tmp_path / "query.csv")
    diagram = BeamDiagramDialog(window.result, window.result.last)
    assert diagram.paths and all(plot.y.size for plot in diagram.plots)
    diagram.export_path(tmp_path / "liner.csv")
    window.save_path(tmp_path / "tunnel.ssproj")
    loaded = api.load_project(tmp_path / "tunnel.ssproj")
    np.testing.assert_allclose(loaded.results.last.u, direct.last.u, rtol=0, atol=0, equal_nan=True)
    assert loaded.model.geometry is not None
    window.close()

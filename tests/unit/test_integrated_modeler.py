"""Integrated drawing-to-FEA contracts, including actual support connectivity."""

import json
import time
from dataclasses import replace

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("shapely")
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from slipsurface.fe2d import api
from slipsurface.fe2d.cad.geometry import Drawing, Entity
from slipsurface.fe2d.cad.supports import SupportAssignment
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.core.errors import ModelError
from slipsurface.fe2d.gui.app import MainWindow


def click(canvas, point):
    x, y = point
    QTest.mouseClick(
        canvas.viewport(), Qt.MouseButton.LeftButton, pos=canvas.mapFromScene(QPointF(x, -y))
    )


def draw_supports(window, app):
    cad = window.cad
    cad.commit(replace(Drawing.example(), h=2))
    cad.canvas.fit_drawing()
    app.processEvents()
    for tool, points in [
        ("pile", ((2, 1), (2, 5))),
        ("tunnel", ((8, 3), (9, 3))),
        ("bolt", ((1, 4), (5, 3))),
    ]:
        window.draft_tool(tool)
        for point in points:
            click(cad.canvas, point)
    return cad


def test_embedded_tools_build_real_supports_and_solve(qt_app, tmp_path):
    window = MainWindow()
    window.resize(1400, 950)
    window.show()
    qt_app.processEvents()
    assert window.workspace.currentWidget() is window.cad
    assert not window.cad.isWindow()
    assert window.cad.build_button.isVisible()
    cad = draw_supports(window, qt_app)
    assert [s.kind for s in cad.document.supports] == ["pile", "liner", "bolt"]
    assert len(cad.document.entities[2].points) == 32
    assert cad.mesh_outdated
    cad.start_mesh()
    deadline = time.monotonic() + 30
    while cad.worker is not None and time.monotonic() < deadline:
        qt_app.processEvents()
        QTest.qWait(10)
    assert cad.worker is None, "mesh worker timed out"
    qt_app.processEvents()
    assert window.model is not None, cad.status.text()
    model = window.model
    assert not cad.mesh_outdated
    assert window.workspace.currentWidget() is window.result_page
    assert model.mesh.block("cad_Kazik1").etype == ElemType.BEAM2
    assert model.mesh.block("cad_Tunel1").etype == ElemType.BEAM2
    assert model.mesh.block("cad_Ankraj1").etype == ElemType.BAR2
    assert model.mesh.block("cad_Tunel1").ne >= 32
    pile_skin = {"cad_Kazik1_ifL", "cad_Kazik1_ifR"}
    assert model.stages[0].active_structures == {
        "cad_Kazik1", "cad_Tunel1", "cad_Ankraj1", *pile_skin
    }  # fmt: skip
    continuum_nodes = set(model.mesh.blocks[0].conn.ravel())
    skin_nodes = {n for tag in pile_skin for n in model.mesh.block(tag).conn.ravel()}
    for tag in model.structure_tags():
        # The pile is a structural interface: its own nodes reach the soil via both skins
        # (an anchor crossing the pile is tied to the pile there).
        assert set(model.mesh.block(tag).conn.ravel()) <= continuum_nodes | skin_nodes
    assert set(model.mesh.block("cad_Kazik1").conn.ravel()) <= skin_nodes | continuum_nodes
    result = api.run(model)
    assert np.isfinite(result.last.u).all()
    assert np.max(np.abs(result.last.u)) > 0
    file = tmp_path / "supported.ssproj"
    api.save_project(model, file, result)
    restored = api.load_project(file)
    assert Drawing.from_dict(restored.model.geometry) == cad.document
    assert restored.model.liners == model.liners
    assert restored.model.bolts == model.bolts
    window.edit_geometry()
    assert not cad.isWindow()
    assert len(cad.document.supports) == 3
    assert cad.undo_stack  # meshing must not erase drafting undo
    window.dirty = False
    window.close()


def test_support_properties_rename_delete_undo_and_draft_roundtrip(qt_app, tmp_path):
    window = MainWindow()
    window.show()
    qt_app.processEvents()
    cad = draw_supports(window, qt_app)
    cad.entities.setCurrentRow(1)
    cad.support_panel.fields["E"].setText("40000000")
    cad.apply_support()
    assert (
        next(s for s in cad.document.supports if s.entity == "Kazik1").properties["E"] == 40000000
    )
    cad.name.setText("Kazik_A")
    cad.update_entity()
    assert any(s.entity == "Kazik_A" for s in cad.document.supports)
    cad.entities.setCurrentRow(1)
    cad.delete_entity()
    assert all(s.entity != "Kazik_A" for s in cad.document.supports)
    cad.undo()
    assert any(s.entity == "Kazik_A" for s in cad.document.supports)
    file = tmp_path / "draft.sscad.json"
    file.write_text(json.dumps(cad.current_drawing().to_dict()))
    other = MainWindow()
    other.open_path(file)
    assert other.model is None
    assert other.cad.document == cad.current_drawing()
    assert not other.cad.unsaved
    assert other.cad.mesh_outdated


def test_outdated_mesh_blocks_solve_and_project_save(qt_app, tmp_path):
    window = MainWindow()
    window.set_model(replace(Drawing.example(), h=3).build_model())
    window.edit_geometry()
    window.cad.start_engineering_tool("pile")
    window.cad.add_point((2, 1))
    window.cad.add_point((2, 5))
    window.start_solve()
    assert window.worker is None
    assert "Çizim değişti" in window.status.currentMessage()
    with pytest.raises(ValueError, match="Çizim değişti"):
        window.save_path(tmp_path / "stale.ssproj")
    assert not (tmp_path / "stale.ssproj").exists()


def test_close_does_not_lose_unsaved_drawing(qt_app, monkeypatch):
    window = MainWindow()
    window.show()
    window.cad.start_tool("region")
    window.cad.add_point((0, 0))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel)
    window.close()
    assert window.isVisible()
    assert window.cad.pending == [(0, 0)]
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Discard)
    window.close()
    assert not window.isVisible()


def test_invalid_support_assignment_and_old_drawing_compatibility():
    drawing = Drawing.example()
    old = drawing.to_dict()
    old["version"] = 1
    old.pop("supports")
    assert Drawing.from_dict(old) == drawing
    with pytest.raises(ValueError):
        replace(drawing, supports=(SupportAssignment("missing", "pile"),)).validate()
    with pytest.raises(ValueError):
        replace(drawing, supports=(SupportAssignment("Zemin", "bolt"),)).validate()
    with pytest.raises(ModelError):
        SupportAssignment("line", "pile", {"E": -1})


def test_snap_and_osnap_are_independent(qt_app):
    window = MainWindow()
    window.show()
    qt_app.processEvents()
    c = window.cad.canvas
    window.cad.commit(Drawing(entities=(Entity("line", "line", ((1.13, 1.17), (3, 2))),)))
    c.fit_drawing()
    window.status.toggles["snap"].setChecked(False)
    window.status.toggles["osnap"].setChecked(True)
    point, _ = c.mapped_point(c.mapFromScene(QPointF(1.13, -1.17)))
    assert point == (1.13, 1.17)
    window.status.toggles["osnap"].setChecked(False)
    window.status.toggles["snap"].setChecked(True)
    point, _ = c.mapped_point(c.mapFromScene(QPointF(1.13, -1.17)))
    assert point == (1.0, 1.0)


def test_staged_tunnel_is_a_separate_excavatable_region(qt_app):
    window = MainWindow()
    cad = window.cad
    cad.commit(replace(Drawing.example(), h=2))
    cad.tunnel_excavation.setChecked(True)
    cad.start_engineering_tool("tunnel")
    cad.add_point((8, 3))
    cad.add_point((9, 3))
    assert cad.document.entities[-1].kind == "region"
    assert cad.document.entities[-1].region == 2
    model = cad.document.build_model()
    assert set(model.mesh.regions()) == {1, 2}
    excavated = replace(model.stages[0], active_regions=frozenset({1}))
    result = api.run(replace(model, stages=[excavated]))
    active = result.last.active["soil"]
    nodes = np.unique(model.mesh.blocks[0].conn[active])
    assert np.isfinite(result.last.u[nodes]).all()
    assert not active[model.mesh.blocks[0].region == 2].any()


def test_advanced_property_edits_do_not_restore_old_cad_supports():
    from slipsurface.fe2d.gui.editing import remove_structure, validate_edit

    drawing = replace(
        Drawing.example(),
        h=2,
        entities=(*Drawing.example().entities, Entity("pile", "line", ((2, 1), (2, 5)))),
        supports=(SupportAssignment("pile", "pile"),),
    )
    model = drawing.build_model()
    changed = replace(model.liners["cad_pile"], E=4e7)
    updated = validate_edit(replace(model, liners={"cad_pile": changed}))
    assert Drawing.from_dict(updated.geometry).supports[0].properties["E"] == 4e7
    removed = remove_structure(updated, "cad_pile")
    assert not Drawing.from_dict(removed.geometry).supports


def test_coordinate_enter_does_not_trigger_mesh_or_leave_modeler(qt_app):
    window = MainWindow()
    window.show()
    qt_app.processEvents()
    cad = window.cad
    for text in ("0,0", "8,0", "8,4", "0,4", ""):
        cad.cmd.setFocus()
        cad.cmd.setText(text)
        QTest.keyClick(cad.cmd, Qt.Key.Key_Return)
    assert cad.document.entities[0].points == ((0, 0), (8, 0), (8, 4), (0, 4))
    assert cad.worker is None
    assert window.workspace.currentWidget() is cad
    cad.canvas.setFocus()
    QTest.keyClick(cad.canvas, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert not cad.document.entities

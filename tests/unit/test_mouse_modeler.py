"""Mouse-driven drafting, view centring and Plaxis-style structure force diagrams."""

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
from slipsurface.fe2d.gui.app import MainWindow
from slipsurface.fe2d.gui.demo import excavation_model


@pytest.fixture(autouse=True)
def discard_on_close(monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Discard)


def view_point(canvas, point):
    return canvas.mapFromScene(QPointF(point[0], -point[1]))


def test_cad_has_icon_strip_and_no_side_panel_or_convergence_tab(qt_app):
    window = MainWindow()
    window.show()
    qt_app.processEvents()
    cad = window.cad
    assert not hasattr(window, "plot")
    assert cad.inspector.window() is cad.inspector_window
    assert not cad.inspector_window.isVisible()
    assert {"select", "region", "rect", "pile", "tunnel", "bolt"} <= set(cad.tool_actions)
    window.draft_tool("pile")
    assert cad.tool_actions["pile"].isChecked() and cad.canvas.drawing
    cad.cancel_drawing()
    assert cad.tool_actions["select"].isChecked() and not cad.canvas.drawing
    window.edit_drawing_conditions()
    assert cad.inspector_window.isVisible() and cad.inspector.currentIndex() == 1
    window.close()


def test_mesh_view_is_centred_on_the_mesh_not_on_labels(qt_app):
    window = MainWindow()
    window.resize(1280, 840)
    window.show()
    window.set_model(excavation_model())
    qt_app.processEvents()
    qt_app.processEvents()
    canvas = window.canvas
    coords = window.model.mesh.coords
    lo, hi = coords.min(axis=0), coords.max(axis=0)
    centre = canvas.mapToScene(canvas.viewport().rect().center())
    assert abs(centre.x() - (lo[0] + hi[0]) / 2) < 0.05 * (hi[0] - lo[0])
    assert abs(-centre.y() - (lo[1] + hi[1]) / 2) < 0.05 * (hi[1] - lo[1])
    scale = abs(canvas.transform().m11())
    filled = max(
        (hi[0] - lo[0]) * scale / canvas.viewport().width(),
        (hi[1] - lo[1]) * scale / canvas.viewport().height(),
    )
    assert filled > 0.8  # labels must not shrink the fitted mesh
    window.close()


def test_drag_vertex_moves_shared_corner_and_undo(qt_app):
    window = MainWindow()
    window.resize(1280, 840)
    window.show()
    cad = window.cad
    left = Entity("A", "region", ((0, 0), (4, 0), (4, 4), (0, 4)), 1)
    right = Entity("B", "region", ((4, 0), (8, 0), (8, 4), (4, 4)), 2)
    cad.commit(Drawing(entities=(left, right)))
    cad.canvas.fit_drawing()
    qt_app.processEvents()
    viewport = cad.canvas.viewport()
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=view_point(cad.canvas, (4, 4)))
    QTest.mouseMove(viewport, view_point(cad.canvas, (5, 5)))
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=view_point(cad.canvas, (5, 5)))
    a, b = cad.document.entities
    assert (5.0, 5.0) in a.points and (5.0, 5.0) in b.points
    assert (4, 4) not in a.points and (4, 4) not in b.points
    cad.undo()
    assert cad.document.entities == (left, right)
    window.close()


def test_left_drag_on_empty_space_pans_without_selecting(qt_app):
    window = MainWindow()
    window.resize(1280, 840)
    window.show()
    cad = window.cad
    cad.commit(replace(Drawing.example(), h=3))
    cad.canvas.fit_drawing()
    qt_app.processEvents()
    viewport = cad.canvas.viewport()
    before = cad.canvas.mapToScene(viewport.rect().center())
    start = viewport.rect().topLeft() + viewport.rect().center() / 4
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(viewport, start + start)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=start + start)
    after = cad.canvas.mapToScene(viewport.rect().center())
    assert (before - after).manhattanLength() > 0
    assert cad.entities.currentRow() == -1
    window.close()


def test_edge_condition_from_canvas_menu_helpers(qt_app):
    window = MainWindow()
    window.show()
    cad = window.cad
    cad.commit(Drawing(entities=(Entity("Z", "region", ((0, 0), (6, 0), (6, 3), (0, 3)), 1),)))
    cad.canvas.fit_drawing()
    qt_app.processEvents()
    edge = cad.canvas.hit_edge(view_point(cad.canvas, (3, 0)), 0)
    assert edge == "Z:1"
    cad.set_edge_rule(edge, ux=True, uy=True)
    rule = next(r for r in cad.current_drawing().rules if r.edge == "Z:1")
    assert rule.ux and rule.uy
    cad.set_edge_rule(edge, ux=False, uy=False)
    assert not cad.current_drawing().rules
    window.close()


def test_clicking_pile_and_anchor_opens_section_force_diagrams(qt_app):
    window = MainWindow()
    window.show()
    model = excavation_model()
    result = api.run(model)
    window.set_model(result.model, result)
    qt_app.processEvents()
    window.click_mode.setCurrentIndex(window.click_mode.findData("query"))
    window._on_canvas_structure_clicked("cad_Kazik")
    dialog = window.force_dialog
    assert dialog.kind == "beam" and dialog.segments and dialog.component.count() == 3
    dialog.component.setCurrentIndex(2)
    assert dialog.status.text().startswith("M:")
    values = np.array([f[:, 2] for *_, f in dialog.segments])
    assert np.isfinite(values).all() and np.abs(values).max() > 0
    window.show_structure_forces("cad_Ankraj1")
    assert window.force_dialog.kind == "bar" and window.force_dialog.component.count() == 1
    window.close()

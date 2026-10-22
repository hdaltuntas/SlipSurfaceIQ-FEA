"""UI regressions: real pointer selection, drafting and readable light colours."""

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("shapely")
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QTest

from slipsurface.fe2d.cad.geometry import Drawing
from slipsurface.fe2d.gui.app import MainWindow
from slipsurface.fe2d.gui.cad import CadDialog
from slipsurface.fe2d.gui.dialogs import sample_model
from slipsurface.fe2d.gui.statusbar import CadStatusBar
from slipsurface.fe2d.gui.workflow import WorkflowBar


def click_world(canvas, x, y):
    QTest.mouseClick(
        canvas.viewport(), Qt.MouseButton.LeftButton, pos=canvas.mapFromScene(QPointF(x, -y))
    )


def test_light_theme_overrides_dark_system_menu_and_button_text(qt_app):
    palette = QPalette()
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.Text,
    ):
        palette.setColor(role, QColor("white"))
    qt_app.setPalette(palette)
    qt_app.setProperty("slipsurface_light_theme", False)
    window = MainWindow()
    window.show()
    qt_app.processEvents()
    menu = window.menuBar()
    assert menu.palette().color(QPalette.ColorRole.WindowText).lightness() < 100
    assert menu.palette().color(QPalette.ColorRole.Window).lightness() > 220
    dialog = CadDialog()
    dialog.show()
    qt_app.processEvents()
    button = dialog.build_button
    assert button.palette().color(QPalette.ColorRole.ButtonText).lightness() < 100
    assert button.palette().color(QPalette.ColorRole.Button).lightness() > 220


def test_rectangle_pointer_selection_delete_and_undo(qt_app):
    dialog = CadDialog()
    dialog.show()
    qt_app.processEvents()
    dialog.start_tool("region", rectangle=True)
    click_world(dialog.canvas, 0, 0)
    click_world(dialog.canvas, 8, 4)
    assert dialog.document.entities[0].points == ((0, 0), (8, 0), (8, 4), (0, 4))
    assert not dialog.canvas.drawing
    click_world(dialog.canvas, 4, 2)
    assert dialog.entities.currentRow() == 0
    assert dialog.name.text() == "Bolge1"
    dialog.delete_entity()
    assert not dialog.document.entities
    dialog.undo()
    assert dialog.document.entities[0].name == "Bolge1"
    dialog.start_tool("region", rectangle=True)
    assert dialog.name.text() == "Bolge2"
    click_world(dialog.canvas, 0, 0)
    click_world(dialog.canvas, 0, 2)
    assert len(dialog.document.entities) == 1  # degenerate rectangle remains editable
    assert len(dialog.pending) == 1


def test_pan_during_drawing_preserves_points_and_preview(qt_app):
    dialog = CadDialog()
    dialog.show()
    qt_app.processEvents()
    canvas = dialog.canvas
    dialog.begin_drawing()
    click_world(canvas, 0, 0)
    start = canvas.viewport().rect().center()
    before = canvas.mapToScene(start)
    QTest.mousePress(canvas.viewport(), Qt.MouseButton.MiddleButton, pos=start)
    QTest.mouseMove(canvas.viewport(), start + QPoint(50, 30))
    QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.MiddleButton, pos=start + QPoint(50, 30))
    assert canvas.mapToScene(start) != before
    assert dialog.pending == [(0, 0)]
    QTest.mouseMove(canvas.viewport(), start)
    assert canvas.preview is not None
    assert canvas.drawing


def test_grid_visibility_does_not_destroy_snap_spacing(qt_app):
    dialog = CadDialog()
    status = CadStatusBar(dialog)
    status.attach(dialog.canvas)
    status.toggles["grid"].click()
    assert not dialog.canvas.grid_visible
    assert dialog.canvas.grid == 0.5
    status.toggles["grid"].click()
    status.toggles["snap"].click()
    assert dialog.canvas.grid_visible
    assert not dialog.canvas.snapping
    assert dialog.canvas.grid == 0.5


def test_active_workflow_step_still_opens_editor(qt_app):
    workflow = WorkflowBar(["Geometri", "Malzemeler"])
    workflow.show()
    qt_app.processEvents()
    events = []
    workflow.step_changed.connect(events.append)
    QTest.mouseClick(workflow, Qt.MouseButton.LeftButton, pos=QPoint(30, 15))
    QTest.mouseClick(workflow, Qt.MouseButton.LeftButton, pos=QPoint(30, 15))
    assert events == [0, 0]


def test_result_redraw_keeps_user_zoom(qt_app):
    window = MainWindow()
    window.show()
    qt_app.processEvents()
    window.set_model(sample_model(nx=2, ny=2))
    window.canvas.scale(2, 2)
    transform = window.canvas.transform()
    window.draw()
    assert window.canvas.transform() == transform
    assert "Boş proje" not in window.status.currentMessage()


def test_nonfinite_command_is_rejected_without_losing_draft(qt_app):
    dialog = CadDialog()
    dialog.begin_drawing()
    assert dialog.canvas.command("0,0")
    for command in ("1e999,0", "@1<1e999", "@1e999,0"):
        assert not dialog.canvas.command(command)
    assert dialog.pending == [(0, 0)]


def test_canvas_selection_chooses_nested_hole(qt_app):
    from slipsurface.fe2d.cad.geometry import Entity

    dialog = CadDialog()
    dialog.commit(
        Drawing(
            entities=(
                Entity("outer", "region", ((0, 0), (10, 0), (10, 8), (0, 8))),
                Entity("hole", "hole", ((2, 2), (4, 2), (4, 4), (2, 4))),
            )
        )
    )
    dialog.show()
    qt_app.processEvents()
    click_world(dialog.canvas, 3, 3)
    assert dialog.entities.currentRow() == 1
    click_world(dialog.canvas, 7, 3)
    assert dialog.entities.currentRow() == 0

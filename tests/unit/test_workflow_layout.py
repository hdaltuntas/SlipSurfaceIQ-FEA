"""Guided workflow, adjustable layout, theme contrast and remesh transfer in the window."""

import time
from dataclasses import replace

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("shapely")
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from slipsurface.fe2d import api
from slipsurface.fe2d.cad.geometry import Drawing
from slipsurface.fe2d.gui import statusbar, theme
from slipsurface.fe2d.gui.app import MainWindow
from slipsurface.fe2d.gui.preferences import apply_theme


def contrast(a, b):
    def luminance(color):
        channels = []
        for v in (color.redF(), color.greenF(), color.blueF()):
            channels.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

    hi, lo = sorted((luminance(QColor(a)), luminance(QColor(b))), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.fixture(autouse=True)
def discard_on_close(monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Discard)


def wait_mesh(window, app):
    deadline = time.monotonic() + 30
    while window.cad.worker is not None and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(10)
    assert window.cad.worker is None
    app.processEvents()


def test_light_theme_text_contrast_meets_wcag_aa(qt_app):
    apply_theme()
    palette = QApplication.instance().palette()
    role = QPalette.ColorRole
    for fg, bg in [
        (role.WindowText, role.Window),
        (role.Text, role.Base),
        (role.ButtonText, role.Button),
        (role.HighlightedText, role.Highlight),
        (role.ToolTipText, role.ToolTipBase),
    ]:
        assert contrast(palette.color(fg), palette.color(bg)) >= 4.5, (fg, bg)
    for fg, bg in [
        ("#243746", "#ffffff"),  # menus, buttons, inputs
        ("#124d70", "#dcecf7"),  # selected menu item
        ("#334b5d", "#e6edf3"),  # tabs and headers
        ("#075780", "#d9edf9"),  # checked tool buttons
    ]:
        assert fg in theme.STYLE and bg in theme.STYLE
        assert contrast(fg, bg) >= 4.5, (fg, bg)
    assert contrast("#5b6b78", "#e7eef4") >= 4.5  # SNAP/GRID off
    assert contrast("#ffffff", "#156798") >= 4.5  # SNAP/GRID on
    assert "#5b6b78" in statusbar.TOGGLE_CSS


def test_workflow_guides_from_empty_drawing_to_results(qt_app):
    window = MainWindow()
    window.show()
    qt_app.processEvents()
    assert window.workflow.done == set()
    assert "Geometri menüsünden" in window.guidance.text()
    window.cad.commit(replace(Drawing.example(), h=3))
    assert window.workflow.done == {0, 2}
    assert "Ağı üret" in window.guidance.text()
    window.workflow.step_changed.emit(2)
    assert window.cad.inspector.currentIndex() == 1 and window.workflow.current == 2
    window.workflow.step_changed.emit(3)
    wait_mesh(window, qt_app)
    assert window.model is not None
    assert window.workflow.done == {0, 2, 3, 4, 5}
    assert window.workflow.current == 4
    window.model = replace(window.model, initial=api.InitialStress("none"))
    window.workflow.step_changed.emit(6)
    deadline = time.monotonic() + 60
    while window.worker is not None and time.monotonic() < deadline:
        qt_app.processEvents()
        QTest.qWait(10)
    qt_app.processEvents()
    assert window.result is not None
    assert {6, 7} <= window.workflow.done and window.workflow.current == 7
    assert window.guidance.text().startswith("Sonuçlar hazır")
    window.workflow.step_changed.emit(0)
    assert window.workspace.currentWidget() is window.cad and not window.project_dock.isVisible()
    window.close()


def test_view_menu_panels_and_layout_persist(qt_app):
    window = MainWindow()
    window.resize(1250, 820)
    window.show()
    window.open_tunnel_example()
    qt_app.processEvents()
    assert window.project_dock.isVisible()
    window.dock_action.setChecked(False)
    window.log_action.setChecked(False)
    assert not window.project_dock.isVisible() and not window.log_tabs.isVisible()
    window.edit_geometry()
    window.show_results()
    assert not window.project_dock.isVisible()  # the user's choice survives mode switches
    window.close()

    again = MainWindow()
    again.show()
    again.open_tunnel_example()
    qt_app.processEvents()
    assert not again.dock_action.isChecked() and not again.log_action.isChecked()
    assert not again.project_dock.isVisible() and not again.log_tabs.isVisible()
    again.reset_layout()
    assert again.project_dock.isVisible() and again.log_tabs.isVisible()
    again.close()


def test_remesh_in_window_keeps_user_materials_and_stages(qt_app):
    window = MainWindow()
    window.show()
    window.cad.commit(replace(Drawing.example(), h=3))
    window.build_mesh()
    wait_mesh(window, qt_app)
    clay = api.MaterialSpec.mohr_coulomb("kil", E=3e4, nu=0.3, c=10, phi=28, gamma=19)
    edited = replace(
        window.model,
        materials={**window.model.materials, "kil": clay},
        region_material={1: "kil"},
        stages=[*window.model.stages, api.Stage("Ek yük")],
    )
    window.set_model(edited, dirty=True)
    window.cad.commit(replace(window.cad.current_drawing(), h=2))
    assert window.cad.mesh_outdated
    window.build_mesh()
    wait_mesh(window, qt_app)
    model = window.model
    assert model.mesh.nn != edited.mesh.nn
    assert model.region_material == {1: "kil"} and model.materials["kil"] == clay
    assert [s.name for s in model.stages] == ["CAD yükleme", "Ek yük"]
    assert "aktarıldı" in window.log.toPlainText()
    window.close()

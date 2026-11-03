"""RS2-inspired analysis menu and independent Interpret workflow checks."""

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("shapely")

from PySide6.QtWidgets import QMenu, QTabBar

from slipsurface.fe2d.gui.app import MainWindow
from slipsurface.fe2d.gui.demo import excavation_model


def test_analysis_menu_contains_project_compute_interpret(qt_app):
    window = MainWindow()
    names = {
        action.text(): action.menu()
        for action in window.menuBar().actions()
        if isinstance(action.menu(), QMenu)
    }
    assert "Analysis" in names
    commands = [a.text() for a in names["Analysis"].actions() if not a.isSeparator()]
    assert commands == ["Project Settings…", "Compute", "Interpret…"]
    inspect = names["Inspect results"]
    assert sum(a.text() == "Open Interpret window…" for a in inspect.actions()) == 1
    window.close()


def test_interpret_has_independent_stage_tabs_and_stress_fields(qt_app):
    window = MainWindow()
    window.set_model(excavation_model())
    window.edit_geometry()
    window.open_interpret()
    qt_app.processEvents()
    dlg = window._interpret_window
    assert dlg is not None and dlg.isVisible()
    tabs, fields, canvas, legend, deform, principal = dlg.viewer
    assert isinstance(tabs, QTabBar)
    assert tabs.count() == len(window.model.stages) + 1
    assert "s1" in [fields.itemText(i) for i in range(fields.count())]
    assert "pore" in [fields.itemText(i) for i in range(fields.count())]
    assert window.workspace.currentWidget() is window.cad
    fields.setCurrentText("ux")
    tabs.setCurrentIndex(tabs.count() - 1)
    assert deform.value() == 1.0
    assert not principal.isChecked()
    dlg.close()
    window.close()

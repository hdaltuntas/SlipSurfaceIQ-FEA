"""Project schedules and picked-region changes across CAD, mesh and saved projects."""

from dataclasses import replace

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("shapely")
from PySide6.QtCore import QPoint, QTimer
from PySide6.QtWidgets import QDialog, QMenu, QMessageBox

from slipsurface.fe2d import api
from slipsurface.fe2d.cad.geometry import ConstructionStep, Drawing, Entity
from slipsurface.fe2d.cad.transfer import transfer_model
from slipsurface.fe2d.gui.app import MainWindow
from slipsurface.fe2d.gui.editing import (
    set_project_stages,
    set_region_stage_state,
    stage_region_material,
)
from slipsurface.fe2d.gui.project_properties import ProjectPropertiesDialog, RegionStageDialog


@pytest.fixture(autouse=True)
def discard_on_close(monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Discard)


@pytest.fixture
def staged_model():
    base = Drawing.example()
    drawing = replace(
        base,
        h=3,
        entities=(*base.entities, Entity("Tunnel", "region", ((7, 2), (9, 2), (9, 4), (7, 4)), 2)),
        sequence=(
            ConstructionStep("Excavation", ("Tunnel",), load_split=0.4),
            ConstructionStep("Support"),
        ),
    )
    model = drawing.build_model()
    return replace(
        model,
        materials={
            **model.materials,
            "Softened rock": api.MaterialSpec.elastic("Softened rock", 8000, 0.3, gamma=20),
        },
    )


def test_draft_properties_keep_sequence_and_survive_json_and_mesh(qt_app, tmp_path):
    window = MainWindow()
    drawing = replace(Drawing.example(), h=3, sequence=(ConstructionStep("Blast"),))
    window.cad.commit(drawing)
    updated = drawing.with_stage_names(["In situ", "Blast / relaxation", "Support"])
    window.cad.commit(updated)
    assert window.model_stage_tabs.count() == 4
    assert window.model_stage_tabs.tabText(2) == "2. Blast / relaxation"
    path = tmp_path / "draft.sscad.json"
    import json

    path.write_text(json.dumps(updated.to_dict()))
    other = MainWindow()
    other.open_path(path)
    assert other.cad.document == updated
    assert [s.name for s in updated.build_model().stages] == [
        "In situ",
        "Blast / relaxation",
        "Support",
    ]
    window.cad.undo()
    assert window.model_stage_tabs.tabText(2) == "2. Blast"


def test_project_properties_count_names_validation_and_cancel(qt_app):
    dialog = ProjectPropertiesDialog(["Load", "Excavate"])
    dialog.names.item(1, 0).setText("Relaxation")
    dialog.count.setValue(1)
    dialog.count.setValue(3)
    assert dialog.names.item(1, 0).text() == "Relaxation"
    assert dialog.names.item(2, 0).text() == "Stage 3"
    dialog.names.item(2, 0).setText("  Load ")
    dialog.apply()
    assert dialog.updated is None and "unique" in dialog.status.text()
    dialog.names.item(2, 0).setText("  Support ")
    dialog.apply()
    assert dialog.updated == ["Load", "Relaxation", "Support"]
    cancelled = ProjectPropertiesDialog(dialog.updated)
    cancelled.count.setValue(1)
    cancelled.reject()
    assert cancelled.updated is None


def test_rename_resize_retains_stage_data_and_remesh_does_not_resurrect_steps(
    staged_model, tmp_path
):
    old = set_region_stage_state(staged_model, 2, 1, "Softened rock", propagate=False)
    names = ["Loading", "Relaxation", "Lining", "Finish"]
    changed = set_project_stages(old, names)
    assert changed.stages[1] == replace(old.stages[1], name="Relaxation")
    assert changed.stages[-1] == replace(old.stages[-1], name="Finish", load_split=1)
    assert old.stages[1].name == "Excavation"
    path = tmp_path / "stages.ssproj"
    api.save_project(changed, path)
    restored = api.load_project(path).model
    assert restored.stages == changed.stages
    smaller = set_project_stages(restored, ["Loading", "Relaxation"])
    drawing = Drawing.from_dict(smaller.geometry)
    fresh = replace(drawing, h=2).build_model()
    remeshed, report = transfer_model(smaller, fresh)
    assert report == []
    assert [s.name for s in remeshed.stages] == ["Loading", "Relaxation"]
    assert remeshed.stages[1].material_override == {1: "Softened rock"}
    assert remeshed.stages[1].load_split == 0.4
    assert remeshed.stages[1].active_regions == {1}


def test_advanced_stage_rename_or_delete_is_not_undone_by_remesh(staged_model):
    # Advanced Stage manager may change the schedule without renaming CAD provenance.
    previous = replace(staged_model, stages=[replace(staged_model.stages[0], name="Only stage")])
    fresh = replace(Drawing.from_dict(previous.geometry), h=2).build_model()
    updated, _ = transfer_model(previous, fresh)
    assert [s.name for s in updated.stages] == ["Only stage"]
    # A newly placed tunnel's construction steps must still be appended.
    drawing = Drawing.from_dict(previous.geometry)
    fresh = replace(
        drawing, sequence=(*drawing.sequence, ConstructionStep("New excavation"))
    ).build_model()
    updated, _ = transfer_model(previous, fresh)
    assert [s.name for s in updated.stages] == ["Only stage", "New excavation"]


def test_cad_tabs_sync_stage_list_mesh_tabs_and_material_preview(qt_app, staged_model):
    window = MainWindow()
    window.set_model(staged_model)
    window.show()
    window.edit_geometry()
    qt_app.processEvents()
    assert window.model_stage_tabs.isVisible()
    assert window.model_stage_tabs.count() == 4
    window.model_stage_tabs.setCurrentIndex(2)
    assert window.stage_tabs.currentIndex() == window.stages.currentRow() == 2
    assert window.cad.canvas.stage_materials == {1: "soil", 2: None}
    window.show_results()
    assert window.stage_tabs.currentIndex() == 2
    window.stages.setCurrentRow(0)
    assert window.model_stage_tabs.currentIndex() == 0
    assert window.cad.canvas.stage_materials == {1: "soil", 2: "soil"}


@pytest.mark.parametrize("stage_index", [0, 1, 2])
@pytest.mark.parametrize("propagate", [False, True])
def test_material_assignment_scope_including_initial(qt_app, staged_model, stage_index, propagate):
    dialog = RegionStageDialog(staged_model, stage_index, 1)
    assert not dialog.propagate.isChecked()
    dialog.material.setCurrentIndex(dialog.material.findData("Softened rock"))
    dialog.propagate.setChecked(propagate)
    dialog.apply()
    assert dialog.result() == QDialog.DialogCode.Accepted
    for i in range(4):
        expected = (
            "Softened rock" if i == stage_index or (propagate and i >= stage_index) else "soil"
        )
        assert stage_region_material(dialog.updated, i, 1) == expected
        assert stage_region_material(staged_model, i, 1) == "soil"
    assert dialog.updated.stages[1].active_regions == {1}


@pytest.mark.parametrize("view", ["cad", "mesh"])
def test_context_menu_assignment_preserves_stage_view_and_invalidates_results(
    qt_app, staged_model, monkeypatch, view
):
    from slipsurface.fe2d.gui import project_properties

    window = MainWindow()
    window.set_model(staged_model)
    if view == "cad":
        window.edit_geometry()
    window.model_stage_tabs.setCurrentIndex(2)

    # Exercise the real action and dialog path without entering a modal event loop.
    def accept(dialog):
        dialog.material.setCurrentIndex(dialog.material.findData("Softened rock"))
        dialog.apply()
        return dialog.result()

    monkeypatch.setattr(project_properties.RegionStageDialog, "exec", accept)

    selected = []

    def choose():
        menu = qt_app.activePopupWidget()
        try:
            action = next(a for a in menu.actions() if a.text().startswith("Assign material"))
            selected.append(action.text())
            action.trigger()
        finally:
            menu.close()

    QTimer.singleShot(0, choose)
    window.result = object()  # old results must be discarded before any redraw
    if view == "cad":
        window.cad.canvas_menu(0, "", QPoint())
    else:
        window._on_canvas_context_menu(1, "", QPoint())
    assert selected == ["Assign materials…"]
    assert window.result is None and window.dirty
    assert window.workspace.currentWidget() is (window.cad if view == "cad" else window.result_page)
    assert window.model_stage_tabs.currentIndex() == window.stages.currentRow() == 2
    assert window.cad.canvas.stage_materials[1] == "Softened rock"
    assert not window.cad.mesh_outdated
    window.cad.commit(replace(window.cad.current_drawing(), h=2))
    stale_menu = QMenu()
    window._add_region_stage_action(stale_menu, 1)
    assert stale_menu.actions()[0].isEnabled()


def test_project_properties_apply_from_main_window(qt_app, staged_model, monkeypatch):
    window = MainWindow()
    window.set_model(staged_model)
    window.edit_geometry()
    window.model_stage_tabs.setCurrentIndex(3)

    def accept(dialog):
        dialog.count.setValue(2)
        dialog.names.item(1, 0).setText("Relaxation")
        dialog.apply()
        return dialog.result()

    monkeypatch.setattr(ProjectPropertiesDialog, "exec", accept)
    window.edit_project_properties()
    assert len(window.model.stages) == 2
    assert window.model_stage_tabs.currentIndex() == 2
    assert window.model_stage_tabs.tabText(2) == "2. Relaxation"
    assert window.workspace.currentWidget() is window.cad
    assert window.model.stages[1].load_split == 0.4


def test_void_reactivation_and_cancel_do_not_modify_other_stages(qt_app, staged_model):
    dialog = RegionStageDialog(staged_model, 2, 2)
    assert dialog.material.currentData() is None
    dialog.material.setCurrentIndex(dialog.material.findData("Softened rock"))
    dialog.apply()
    assert stage_region_material(dialog.updated, 2, 2) == "Softened rock"
    assert stage_region_material(dialog.updated, 3, 2) is None
    cancelled = RegionStageDialog(staged_model, 1, 2)
    cancelled.material.setCurrentIndex(0)
    cancelled.reject()
    assert cancelled.updated is None
    assert stage_region_material(staged_model, 1, 2) == "soil"


@pytest.mark.parametrize("view", ["cad", "mesh"])
@pytest.mark.parametrize("stage_index", [0, 1])
@pytest.mark.parametrize("propagate", [False, True])
def test_assign_materials_void_scope_and_geometry(
    qt_app, staged_model, view, stage_index, propagate, monkeypatch
):
    model = replace(
        staged_model, stages=[replace(s, active_regions=None) for s in staged_model.stages]
    )
    window = MainWindow()
    window.set_model(model)
    if view == "cad":
        window.edit_geometry()
    window.model_stage_tabs.setCurrentIndex(stage_index)
    title = "Assign materials…"

    def accept(dialog):
        dialog.material.setCurrentIndex(dialog.material.findData(None))
        dialog.propagate.setChecked(propagate)
        dialog.apply()
        return dialog.result()

    monkeypatch.setattr(RegionStageDialog, "exec", accept)
    selected = []

    def choose():
        menu = qt_app.activePopupWidget()
        try:
            assert [a.text() for a in menu.actions()] == [title]
            action = menu.actions()[0]
            selected.append(action.isEnabled())
            action.trigger()
        finally:
            menu.close()

    QTimer.singleShot(0, choose)
    window.result = object()
    if view == "cad":
        window.cad.canvas_menu(1, "", QPoint())
    else:
        window._on_canvas_context_menu(2, "", QPoint())
    assert selected == [True]
    assert window.result is None and window.dirty
    assert window.stages.currentRow() == stage_index
    assert window.workspace.currentWidget() is (window.cad if view == "cad" else window.result_page)
    assert window.model.mesh is model.mesh
    assert window.model.geometry == model.geometry
    assert window.model.materials == model.materials
    assert window.model.region_material == model.region_material
    for i in range(4):
        excavated = i == stage_index or (propagate and i >= stage_index)
        assert stage_region_material(window.model, i, 2) == (None if excavated else "soil")
        assert stage_region_material(model, i, 2) == "soil"
    assert window.cad.canvas.stage_materials[2] is None
    assert not window.cad.mesh_outdated


def test_assignment_only_menu_and_stale_mesh_guard(qt_app, staged_model):
    window = MainWindow()
    window.set_model(staged_model)
    window.stages.setCurrentRow(2)
    menu = QMenu()
    window._add_region_stage_action(menu, 2)
    assert [a.text() for a in menu.actions()] == ["Assign materials…"]
    assert menu.actions()[0].isEnabled()  # void regions can be assigned a material again
    window.cad.commit(replace(window.cad.current_drawing(), h=2))
    stale_menu = QMenu()
    window._add_region_stage_action(stale_menu, 2)
    assert len(stale_menu.actions()) == 1 and stale_menu.actions()[0].isEnabled()
    before = window.model
    window.excavate_region(2)
    assert window.model is before

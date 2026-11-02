"""Material/excavation authoring without generating a mesh."""
import json
from dataclasses import replace

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QDialog, QMenu

from slipsurface.fe2d import api
from slipsurface.fe2d.cad.geometry import ConstructionStep, Drawing
from slipsurface.fe2d.cad.material_assignment import (
    assign_region,
    material_specs,
    region_state,
    serialize_materials,
)
from slipsurface.fe2d.cad.transfer import transfer_model
from slipsurface.fe2d.gui.app import MainWindow
from slipsurface.fe2d.gui.editing import set_region_stage_state, stage_region_material
from slipsurface.fe2d.gui.project_properties import DraftRegionStageDialog


def draft():
    drawing = replace(Drawing.example(), h=3, sequence=(ConstructionStep("Excavate"),
                                                       ConstructionStep("Support")))
    materials = material_specs(drawing)
    materials["Soft"] = api.MaterialSpec.elastic("Soft", 5000, 0.3)
    return replace(drawing, material_library=serialize_materials(materials))


def test_draft_scope_json_rename_and_mesh():
    drawing = draft()
    entity = drawing.entities[0]
    edited = assign_region(drawing, 2, entity, None)
    edited = assign_region(edited, 3, entity, "Soft")
    edited = Drawing.from_dict(json.loads(json.dumps(edited.to_dict())))
    assert region_state(edited, 1, entity) == "soil"
    assert region_state(edited, 2, entity) is None
    assert region_state(edited, 3, entity) == "Soft"
    renamed = edited.with_stage_names(["Load", "Dig", "Liner"])
    assert renamed.material_assignments[0]["stage"] == "Dig"
    model = renamed.build_model()
    assert stage_region_material(model, 2, 1) is None
    assert stage_region_material(model, 3, 1) == "Soft"
    # A later meshed edit must replace, rather than resurrect, the draft state.
    changed = set_region_stage_state(model, 2, 1, "Soft", propagate=False)
    fresh = Drawing.from_dict(changed.geometry).build_model()
    remeshed, _ = transfer_model(changed, fresh)
    assert stage_region_material(remeshed, 2, 1) == "Soft"


def test_initial_only_and_following_stages():
    drawing = draft()
    entity = drawing.entities[0]
    only = assign_region(drawing, 0, entity, "Soft")
    model = only.build_model()
    assert stage_region_material(model, 0, 1) == "Soft"
    assert stage_region_material(model, 1, 1) == "soil"
    all_stages = assign_region(drawing, 1, entity, None, True).build_model()
    assert stage_region_material(all_stages, 0, 1) == "soil"
    assert all(stage_region_material(all_stages, i, 1) is None for i in range(1, 4))


def test_assign_without_mesh_and_undo(qt_app, monkeypatch):
    window = MainWindow()
    drawing = draft()
    window.cad.commit(drawing)
    window.stages.setCurrentRow(2)
    menu = QMenu()
    window._add_region_stage_action(menu, 1)
    assert menu.actions()[0].isEnabled()

    def accept(dialog):
        dialog.material.setCurrentIndex(dialog.material.findData(None))
        dialog.apply()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(DraftRegionStageDialog, "exec", accept)
    window.edit_region_stage(1)
    assert window.model is None
    assert window.cad.canvas.stage_materials[1] is None
    assert window.stages.currentRow() == 2
    window.cad.undo()
    assert window.cad.document == drawing


def test_stale_mesh_assignment_wins_transfer_and_materials_open_without_mesh(qt_app, monkeypatch):
    from slipsurface.fe2d.gui.project_properties import DraftMaterialDialog
    window = MainWindow()
    original = draft().build_model()
    window.set_model(original)
    window.cad.commit(replace(window.cad.current_drawing(), h=2))
    window.stages.setCurrentRow(2)

    def accept(dialog):
        dialog.material.setCurrentIndex(dialog.material.findData("Soft"))
        dialog.apply()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(DraftRegionStageDialog, "exec", accept)
    window.edit_region_stage(1)
    drawing = window.cad.current_drawing()
    assert window.model is original  # no solve or mesh generation during authoring
    assert window.cad.canvas.stage_materials[1] == "Soft"
    remeshed, _ = transfer_model(original, drawing.build_model())
    assert stage_region_material(remeshed, 2, 1) == "Soft"
    blank = MainWindow()

    def materials(dialog):
        dialog.materials["Rock"] = api.MaterialSpec.mohr_coulomb("Rock", 10000, 0.3, 20, 30)
        dialog.apply()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(DraftMaterialDialog, "exec", materials)
    blank.edit_materials()
    assert blank.model is None
    assert "Rock" in material_specs(blank.cad.current_drawing())

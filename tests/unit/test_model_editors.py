"""Qt forms preserve semantic model state and drive the same staged solver."""

import os
from dataclasses import replace

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QDialog, QPushButton

from slipsurface.fe2d import api
from slipsurface.fe2d.gui.app import MainWindow
from slipsurface.fe2d.gui.condition_editor import LoadEditor, WaterEditor
from slipsurface.fe2d.gui.dialogs import sample_model
from slipsurface.fe2d.gui.editing import put_structure, remove_structure
from slipsurface.fe2d.gui.material_editor import (
    MODELS,
    MaterialDialog,
    MaterialSpecDialog,
    default_material,
)
from slipsurface.fe2d.gui.stage_editor import InitialDialog, StageDetailDialog, StageDialog
from slipsurface.fe2d.gui.structure_editor import StructureDialog, StructureSpecDialog
from slipsurface.fe2d.mesh.structures import add_bar, add_beams
from slipsurface.fe2d.model.boundary import Displacement


@pytest.mark.parametrize("kind", MODELS)
def test_material_forms_build_all_models_and_hydraulics(qt_app, kind):
    spec = replace(default_material(kind, "rock"), k_sat=(1e-6, 2e-7), vg=(0.7, 1.8, 1e-5))
    form = MaterialSpecDialog(spec)
    form.apply()
    assert form.result() == QDialog.DialogCode.Accepted, form.status.text()
    assert form.updated.k_sat == spec.k_sat and form.updated.vg == spec.vg
    assert form.updated.model == kind
    for key, value in spec.params.items():
        assert form.updated.params[key] == value


def test_material_rename_preserves_references_and_cancel_is_atomic(qt_app):
    source = sample_model(nx=1, ny=1)
    source.stages = [replace(source.stages[0], material_override={1: "soil"})]
    form = MaterialDialog(source)
    form.store_material(replace(source.materials["soil"], name="rock"), "soil")
    assert form.model.region_material == {1: "rock"}
    assert form.model.stages[0].material_override == {1: "rock"}
    form.list.setCurrentRow(0)
    form.delete_material()
    assert form.model.materials.keys() == {"rock"}
    assert form.status.text()
    form.store_material(default_material("elastic", "fill"))
    form.assignments.cellWidget(0, 1).setCurrentText("fill")
    form.reject()
    assert form.updated is None
    assert source.region_material == {1: "soil"}
    assert source.stages[0].material_override == {1: "soil"}
    accepted = MaterialDialog(source)
    accepted.store_material(default_material("elastic", "fill"))
    accepted.assignments.cellWidget(0, 1).setCurrentText("fill")
    accepted.apply()
    assert accepted.updated.region_material == {1: "fill"}


def test_rankine_checkbox_and_invalid_input_do_not_replace_spec(qt_app):
    spec = api.MaterialSpec.mohr_coulomb("s", 20000, 0.3, 20, 30, rankine_at_apex=True)
    form = MaterialSpecDialog(spec)
    assert form.fields["rankine_at_apex"].isChecked()
    form.extra["kx"].setText("nan")
    form.apply()
    assert form.updated is None and form.status.text()
    form.extra["kx"].setText("1e-8")
    form.apply()
    assert form.updated.params["rankine_at_apex"] is True


def test_stage_copy_move_delete_preserves_all_fields_and_empty_regions(qt_app):
    model = sample_model(nx=1, ny=1)
    first = replace(
        model.stages[0],
        water=api.WaterCondition.piezo([(0, 2)]),
        material_override={1: "soil"},
        displacements=(Displacement("top", uy=-0.01),),
        active_regions=frozenset(),
        reset_displacements=True,
    )
    model.stages = [first]
    form = StageDialog(model)
    assert form.table.item(0, 3).text() == "-"
    form.table.item(0, 1).setText(".4")
    form.copy_stage()
    form.move_stage(-1)
    form.add_stage()
    form.delete_stage()
    form.apply()
    assert len(form.updated.stages) == 2
    copied = form.updated.stages[0]
    assert copied.name != first.name
    assert copied.active_regions == frozenset()
    assert copied.loads == first.loads and copied.water == first.water
    assert copied.material_override == first.material_override
    assert copied.displacements == first.displacements and copied.reset_displacements
    assert copied.load_split == 0.4
    assert model.stages == [first]
    invalid = StageDialog(model)
    invalid.table.item(0, 4).setText("unknown")
    invalid.apply()
    assert invalid.updated is None and invalid.status.text()


def test_load_row_removal_does_not_leave_stale_kind_callbacks(qt_app):
    model = sample_model(nx=1, ny=1)
    editor = LoadEditor(model.mesh, (api.EdgeLoad("top", 5), api.PointLoad(1, 3, -4)))
    editor.table.removeRow(0)
    editor.table.cellWidget(0, 0).setCurrentIndex(0)
    editor.table.cellWidget(0, 1).setCurrentText("right")
    assert editor.values() == (api.EdgeLoad("right", 3, -4),)
    # Exercise the real clicked(bool) signal, not just direct helper calls.
    next(b for b in editor.findChildren(QPushButton) if b.text() == "Ekle").click()
    assert editor.table.rowCount() == 2


def test_stage_detail_loads_water_override_and_nan_rejection(qt_app):
    model = sample_model(nx=1, ny=1)
    model.materials["rock"] = default_material("elastic", "rock")
    form = StageDetailDialog(model, 0)
    form.loads.add(api.PointLoad(2, 5, -6))
    form.water.mode.setCurrentIndex(form.water.mode.findData("seepage"))
    form.water.heads.add("left", 5)
    form.water.fluxes.add("top", 1e-8)
    form.overrides.cellWidget(0, 1).setCurrentText("rock")
    form.loads.table.cellWidget(1, 2).setText("nan")
    form.apply()
    assert form.updated is None and form.status.text()
    form.loads.table.cellWidget(1, 2).setText("5")
    form.apply()
    assert form.updated.loads[-1] == api.PointLoad(2, 5, -6)
    assert form.updated.material_override == {1: "rock"}
    assert form.updated.water == api.WaterCondition.seepage({"left": 5}, {"top": 1e-8})
    assert model.stages[0].water.mode == "none"


def test_water_roundtrip_and_initial_explicit_empty_activation(qt_app):
    model = sample_model(nx=1, ny=1)
    for water in [
        api.WaterCondition(),
        api.WaterCondition.piezo([(12, 3), (0, 4)]),
        api.WaterCondition.seepage({"left": 2}, {"top": 1e-8}, ["right"]),
    ]:
        assert WaterEditor(model.mesh, water).value() == water
    form = InitialDialog(model)
    form.mode.setCurrentIndex(form.mode.findData("field"))
    for edit, value in zip(form.stress, [-300, -600, -270, 0]):
        edit.setText(str(value))
    form.structures.setText("")
    form.regions.setText("-")
    form.apply()
    assert form.updated.field == (-300, -600, -270, 0)
    assert form.updated.active_regions == frozenset()
    assert form.updated.active_structures == frozenset()
    assert model.initial.mode == "none"
    # Preserve auto interfaces separately from explicitly no structures.
    auto = InitialDialog(model)
    auto.apply()
    assert auto.updated.active_structures is None


def test_structure_creation_edit_and_removal_preserve_source(qt_app):
    model = sample_model(nx=2, ny=2)
    original_blocks = model.mesh.blocks
    with pytest.raises(ValueError, match="Yapı adı"):
        put_structure(model, api.BoltSpec("a,b", 1e5, 100), nodes=(0, 1))
    liner = StructureSpecDialog(model)
    liner.name.setText("shotcrete")
    liner.edge.setCurrentText("top")
    liner.apply()
    assert liner.updated is not None, liner.status.text()
    model2 = liner.updated
    assert model2.mesh.block("shotcrete").ne == 4
    assert model2.stages[0].active_structures == frozenset()
    bolt = StructureSpecDialog(model2)
    bolt.kind.setCurrentIndex(2)
    bolt.name.setText("anchor")
    bolt.nodes[0].setValue(0)
    bolt.nodes[1].setValue(model.mesh.nn - 1)
    bolt.apply()
    assert bolt.updated.mesh.block("anchor").conn.tolist() == [[0, model.mesh.nn - 1]]
    edited = StructureSpecDialog(bolt.updated, "anchor")
    edited.fields["spacing_out_of_plane"].setText("2")
    edited.apply()
    assert edited.updated.bolts["anchor"].spacing_out_of_plane == 2
    assert edited.updated.mesh is bolt.updated.mesh
    active = replace(
        edited.updated,
        initial=replace(model.initial, active_structures={"anchor"}),
        stages=[replace(model.stages[0], active_structures={"shotcrete", "anchor"})],
    )
    removed = remove_structure(active, "anchor")
    assert removed.initial.active_structures == frozenset()
    assert removed.stages[0].active_structures == {"shotcrete"}
    assert "anchor" not in removed.bolts and "anchor" in active.bolts
    manager = StructureDialog(active)
    manager.list.setCurrentRow(manager.tags.index("anchor"))
    manager.delete_structure()
    manager.reject()
    assert manager.updated is None and "anchor" in active.bolts
    assert model.mesh.blocks is original_blocks and not model.liners
    bad = StructureSpecDialog(model)
    bad.kind.setCurrentIndex(2)
    bad.nodes[1].setValue(0)
    bad.apply()
    assert bad.updated is None and bad.status.text()
    bonded = put_structure(model, api.BoltSpec("bonded", 1e5, 100), edge_set="left")
    assert bonded.mesh.block("bonded").ne == 4


def test_authored_staged_model_matches_direct_api_and_saved_results(qt_app, tmp_path):
    """Independent API definition vs actual forms: loads, liner then bolt activation."""
    from test_desktop import finish

    base = sample_model(nx=2, ny=2, load=20)
    liner_spec = api.LinerSpec("liner", 3e7, 0.2, 0.2, 0.2**3 / 12, 0.2 * 5 / 6, 24)
    bolt_spec = api.BoltSpec("bolt", 200000, 200)
    direct_mesh = add_bar(add_beams(base.mesh, "top", "liner"), 0, base.mesh.nn - 1, "bolt")
    direct = replace(
        base,
        mesh=direct_mesh,
        liners={"liner": liner_spec},
        bolts={"bolt": bolt_spec},
        stages=[
            api.Stage("release", loads=(api.EdgeLoad("top", 20),), load_split=0.4),
            api.Stage(
                "liner",
                active_structures={"liner"},
                loads=(api.EdgeLoad("top", 20),),
                load_split=0.5,
            ),
            api.Stage(
                "bolt", active_structures={"liner", "bolt"}, loads=(api.EdgeLoad("top", 20),)
            ),
        ],
    )
    a = StructureSpecDialog(base)
    a.name.setText("liner")
    a.edge.setCurrentText("top")
    a.apply()
    b = StructureSpecDialog(a.updated)
    b.name.setText("bolt")
    b.kind.setCurrentIndex(2)
    b.nodes[1].setValue(base.mesh.nn - 1)
    b.apply()
    stages = StageDialog(b.updated)
    stages.table.item(0, 0).setText("release")
    stages.table.item(0, 1).setText(".4")
    stages.copy_stage()
    stages.table.item(1, 0).setText("liner")
    stages.table.item(1, 1).setText(".5")
    stages.table.item(1, 4).setText("liner")
    stages.copy_stage()
    stages.table.item(2, 0).setText("bolt")
    stages.table.item(2, 1).setText("1")
    stages.table.item(2, 4).setText("liner,bolt")
    stages.apply()
    assert stages.updated is not None, stages.status.text()
    window = MainWindow()
    window.set_model(stages.updated)
    window.start_solve()
    finish(window, qt_app)
    assert window.result is not None, window.log.toPlainText()
    expected = api.run(direct)
    for actual, ref in zip(window.result.stages, expected.stages):
        np.testing.assert_allclose(actual.u, ref.u, rtol=0, atol=0, equal_nan=True)
        np.testing.assert_allclose(actual.sig["soil"], ref.sig["soil"], rtol=0, atol=0)
        np.testing.assert_allclose(actual.beams["liner"], ref.beams["liner"], equal_nan=True)
        np.testing.assert_allclose(actual.bars["bolt"], ref.bars["bolt"], equal_nan=True)
    path = tmp_path / "authored.ssproj"
    window.save_path(path)
    reopened = api.load_project(path)
    assert reopened.model.stages == direct.stages
    np.testing.assert_allclose(reopened.results.last.u, expected.last.u, rtol=0, atol=0)
    window.close()

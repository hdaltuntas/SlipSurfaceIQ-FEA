"""Real Qt interface-law authoring, transactions, persistence and native re-solve."""

import os
import runpy
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from slipsurface.fe2d import api
from slipsurface.fe2d.gui.interface_authoring import apply_interface_spec
from slipsurface.fe2d.gui.structure_editor import InterfaceDialog, StructureDialog
from slipsurface.fe2d.io.project_json import model_to_dict
from slipsurface.fe2d.mesh import rectangle

_BENCH = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts"
                            / "f7_contact_static_benchmark.py"))
build_model = _BENCH["build_model"]


def select(form, law):
    form.law.setCurrentIndex(form.law.findData(law))


@pytest.mark.parametrize("element_type", ["IFACE4", "IFACE6"])
@pytest.mark.parametrize("gap", [0.0, 0.002])
def test_unchanged_contact_dialog_preserves_law_and_clearance(qt_app, element_type, gap):
    model, _ = build_model(element_type=element_type, initial_gap=gap)
    before = model_to_dict(model)
    form = InterfaceDialog(model, "contact")
    assert form.law.currentData() == "unilateral_normal"
    assert form.fields["initial_gap"].isEnabled()
    assert not form.fields["ks"].isEnabled()
    form.apply()
    assert form.updated is not None, form.status.text()
    assert form.updated.interfaces["contact"] == model.interfaces["contact"]
    assert form.updated.mesh is model.mesh
    assert model_to_dict(model) == before


def test_goodman_remains_default_and_roundtrips_unchanged(qt_app):
    model, _ = build_model()
    model.interfaces["contact"] = api.InterfaceSpec("joint", 2000, 1000, 5, 30, 10, 1)
    form = InterfaceDialog(model, "contact")
    assert form.name.text() == "joint"
    assert form.law.currentData() == "goodman"
    assert not form.fields["initial_gap"].isEnabled()
    assert InterfaceDialog(model).law.currentData() == "goodman"
    form.apply()
    assert form.updated.interfaces["contact"] == model.interfaces["contact"]


def test_toggle_preserves_drafts_and_ignores_disabled_fields(qt_app):
    model, _ = build_model()
    model.interfaces["contact"] = api.InterfaceSpec("contact", 2000, 1000, 5, 30, 10, 1)
    form = InterfaceDialog(model, "contact")
    form.fields["ks"].setText("1234")
    select(form, "unilateral_normal")
    form.fields["initial_gap"].setText("0.003")
    assert "NOT tied" in form.law_note.text()
    select(form, "goodman")
    assert form.fields["ks"].text() == "1234"
    select(form, "unilateral_normal")
    assert form.fields["initial_gap"].text() == "0.003"
    form.fields["phi"].setText("invalid but disabled")
    form.apply()
    assert form.updated is not None, form.status.text()
    spec = form.updated.interfaces["contact"]
    assert spec.law == "unilateral_normal" and spec.initial_gap == 0.003
    assert (spec.ks, spec.c, spec.phi, spec.psi, spec.sig_t) == (0, 0, 0, 0, 0)
    assert model.interfaces["contact"].law == "goodman"


def test_explicit_conversion_back_to_goodman_resets_clearance(qt_app):
    model, _ = build_model(initial_gap=0.002)
    form = InterfaceDialog(model, "contact")
    select(form, "goodman")
    form.fields["ks"].setText("1000")
    form.fields["initial_gap"].setText("disabled invalid clearance")
    form.apply()
    assert form.updated is not None, form.status.text()
    spec = form.updated.interfaces["contact"]
    assert spec.law == "goodman" and spec.initial_gap == 0 and spec.ks == 1000
    assert model.interfaces["contact"].law == "unilateral_normal"


@pytest.mark.parametrize("bad", ["gravity", "wet", "undrained", "axisym", "mNR", "seismic"])
def test_unsupported_model_not_silently_repaired(qt_app, bad):
    model, _ = build_model()
    model.interfaces["contact"] = api.InterfaceSpec("contact", 2000, 1000, phi=30)
    if bad == "gravity":
        model.initial = api.InitialStress("gravity")
    elif bad == "wet":
        model.stages[0] = replace(model.stages[0], water=api.WaterCondition(
            mode="piezo_line", piezo_polyline=np.array([[0., 1.], [2., 1.]])))
    elif bad == "undrained":
        model.materials["solid"] = model.materials["solid"].with_drainage(api.Drainage.UNDRAINED_A)
    elif bad == "axisym":
        model.analysis = api.Analysis.AXISYMMETRIC
    elif bad == "mNR":
        model.settings = replace(model.settings, method="mNR")
    else:
        model.stages[0] = replace(model.stages[0], seismic_kh=0.1)
    before = model_to_dict(model)
    form = InterfaceDialog(model, "contact")
    select(form, "unilateral_normal")
    form.apply()
    assert form.updated is None
    assert "unilateral" in form.status.text().lower()
    assert model_to_dict(model) == before


def test_geometric_preflight_rejects_noncoincident_reference_faces(qt_app):
    model, _ = build_model(element_type="IFACE6")
    coords = model.mesh.coords.copy()
    coords[model.mesh.block("contact").conn[0, 2], 1] += 0.01
    model.mesh = replace(model.mesh, coords=coords)
    before = model_to_dict(model)
    form = InterfaceDialog(model, "contact")
    form.apply()
    assert form.updated is None and form.status.text()
    assert model_to_dict(model) == before


def test_new_contact_on_internal_edge_is_transactional(qt_app):
    mesh = rectangle(2., 2., 2, 2, etype=api.ElemType.Q4)
    mid = np.flatnonzero(np.isclose(mesh.coords[:, 1], 1.0))
    mid = mid[np.argsort(mesh.coords[mid, 0])]
    mesh.edge_sets["jointline"] = np.column_stack([mid[:-1], mid[1:]])
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN, mesh=mesh,
        materials={"soil": api.MaterialSpec.elastic("soil", 2000, 0.25)},
        region_material={1: "soil"}, initial=api.InitialStress("none"),
        fixities=(api.Fixity("bottom", True, True),),
    )
    before = model_to_dict(model)
    form = InterfaceDialog(model)
    form.edge.setCurrentText("jointline")
    select(form, "unilateral_normal")
    form.fields["initial_gap"].setText("0.001")
    form.apply()
    assert form.updated is not None, form.status.text()
    assert form.updated.interfaces["joint"].law == "unilateral_normal"
    assert form.updated.interfaces["joint"].initial_gap == 0.001
    assert form.updated.mesh.nn > model.mesh.nn
    assert model_to_dict(model) == before


def test_dialog_edit_persist_and_actual_native_resolve(qt_app, tmp_path):
    model, _ = build_model(initial_gap=0.002)
    form = InterfaceDialog(model, "contact")
    form.fields["kn"].setText("4000")
    form.apply()
    assert form.updated is not None, form.status.text()
    path = tmp_path / "edited-contact.json"
    api.save_model(form.updated, path)
    restored = api.load_model(path)
    assert restored.interfaces["contact"].law == "unilateral_normal"
    assert restored.interfaces["contact"].kn == 4000
    result = api.run(restored)
    for i, opening in enumerate((0.008, 0.007)):
        np.testing.assert_allclose(result.stages[i].contact_gap["contact"], opening, atol=1e-12)
        np.testing.assert_allclose(result.stages[i].interfaces["contact"], 0, atol=1e-9)
    # Closed equilibrium: Eoed/H=2400, top displacement=-0.003 m, clearance=0.002 m.
    bottom = (2400 * -0.003 - 4000 * 0.002) / (2400 + 4000)
    expected_gap = 0.002 + bottom
    np.testing.assert_allclose(result.stages[4].contact_gap["contact"], expected_gap, atol=1e-12)
    np.testing.assert_allclose(result.stages[4].interfaces["contact"][..., 1],
                               4000 * expected_gap, atol=1e-9)


def test_cancel_and_missing_target_never_mutate_source(qt_app):
    model, _ = build_model(initial_gap=0.002)
    before = model_to_dict(model)
    form = InterfaceDialog(model, "contact")
    form.fields["initial_gap"].setText("0.01")
    form.reject()
    assert form.updated is None
    with pytest.raises(ValueError, match="no longer exists"):
        apply_interface_spec(model, model.interfaces["contact"], tag="deleted")
    assert model_to_dict(model) == before


def test_manager_shows_law_and_optional_evidence_image(qt_app):
    model, _ = build_model(initial_gap=0.002)
    manager = StructureDialog(model)
    assert "unilateral_normal" in manager.list.item(0).text()
    form = InterfaceDialog(model, "contact")
    form.show()
    qt_app.processEvents()
    destination = os.environ.get("CONTACT_EDITOR_SCREENSHOT")
    if destination:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        assert form.grab().save(str(path))

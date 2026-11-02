"""Selected-member plots, manual tunnel schedules and model-side bolt patterns."""

from dataclasses import replace

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("shapely")
from PySide6.QtWidgets import QMessageBox

from slipsurface.fe2d import api
from slipsurface.fe2d.cad.geometry import ConstructionStep, Drawing, Entity
from slipsurface.fe2d.cad.tunnel import (
    TunnelDesign,
    TunnelSection,
    bolt_pattern_along,
    bolt_stations,
    place_tunnel,
)
from slipsurface.fe2d.gui.app import MainWindow
from slipsurface.fe2d.gui.canvas import MeshCanvas
from slipsurface.fe2d.gui.result_tools import (
    StructureForceDialog,
    StructureSegment,
    force_diagram_line,
    force_trace,
    structure_chains,
)
from slipsurface.fe2d.gui.tunnel_designer import TunnelDesignerDialog


@pytest.fixture(autouse=True)
def discard_on_close(monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Discard)


def synthetic_result():
    coords = np.array(
        [
            (0, 0),
            (1000, 0),
            (1000, 1000),
            (0, 1000),
            (10, 10),
            (11, 11),
            (12, 10),
            (20, 10),
            (21, 10),
            (10, 12),
        ],
        float,
    )
    mesh = api.Mesh(
        coords,
        (
            api.ElementBlock(api.ElemType.Q4, np.array([[0, 1, 2, 3]]), 1, "soil"),
            api.ElementBlock(
                api.ElemType.BEAM2, np.array([[4, 5], [5, 6], [7, 8]]), [1, 1, 1], "lining"
            ),
            api.ElementBlock(api.ElemType.BAR2, np.array([[4, 9]]), 1, "bolt"),
        ),
    )
    model = api.Model(
        api.Analysis.PLANE_STRAIN,
        mesh,
        {"rock": api.MaterialSpec.elastic("rock", 20000, 0.3)},
        {1: "rock"},
        stages=[api.Stage("Loaded", active_structures={"lining", "bolt"})],
        liners={"lining": api.LinerSpec("lining", 3e7, 0.2, 0.2, 0.001, 0.15)},
        bolts={"bolt": api.BoltSpec("bolt", 200000, 200)},
    )
    stage = api.StageResult(
        "Loaded",
        np.zeros((mesh.nn, 2)),
        {},
        np.zeros((mesh.nn, 3)),
        beams={"lining": np.ones((3, 2, 3))},
        bars={"bolt": np.array([7.0])},
    )
    initial = replace(
        stage,
        name="Initial",
        active={"lining": np.zeros(3, bool), "bolt": np.zeros(1, bool)},
        beams={},
        bars={},
    )
    return api.SolveResult(model, {}, initial, [stage])


def test_curved_normals_join_geometry_but_preserve_force_jumps():
    a = StructureSegment(
        np.array([0.0, 0.0]),
        np.array([1.0, 1.0]),
        np.array([0.0, 1.0]),
        np.array([[2.0], [2.0]]),
        (0, 1),
    )
    b = StructureSegment(
        np.array([1.0, 1.0]),
        np.array([2.0, 0.0]),
        np.array([1.0, 2.0]),
        np.array([[2.0], [2.0]]),
        (1, 2),
    )
    line = force_diagram_line([a, b], 0, 0.1)
    np.testing.assert_allclose(line[1][0], line[2][0])
    b = replace(b, forces=np.array([[4.0], [4.0]]))
    line = force_diagram_line([a, b], 0, 0.1)
    assert line[1][1] == 2 and line[2][1] == 4
    assert np.linalg.norm(line[2][0] - b.a) == pytest.approx(0.4)
    # Coincident coordinates alone must never connect two independent FE chains.
    b = replace(b, nodes=(10, 11))
    assert len(structure_chains([a, b])) == 2
    x, y = force_trace([a, b], 0)
    assert np.isnan(x[2]) and np.isnan(y[2])


def test_nvm_scales_to_member_and_never_bridges_disconnected_chains(qt_app):
    result = synthetic_result()
    canvas = MeshCanvas()
    canvas.show_model(
        result.model, result.last, "V", result=result, selection=("structure", "lining")
    )
    assert canvas.nvm_count == 4  # 3 lines on the two-segment chain, 1 on the other
    assert canvas.diagram_tags == ["lining"]
    # Background domain is 1000 m; member extent is 11 m → max ordinate 1.1 m.
    bands = [
        i
        for i in canvas.scene().items()
        if hasattr(i, "polygon") and i.data(0) == ("structure", "lining")
    ]
    assert len(bands) == 3
    for band in bands:
        poly = band.polygon()
        assert np.hypot(poly[1].x() - poly[0].x(), poly[1].y() - poly[0].y()) == pytest.approx(1.1)
    canvas.show_model(
        result.model,
        result.last,
        "V",
        result=result,
        selection=("structure", "lining"),
        diagram_scale=0.5,
    )
    assert canvas.nvm_count == 4
    canvas.show_model(
        result.model, result.initial, "V", result=result, selection=("structure", "lining")
    )
    assert canvas.nvm_count == 0 and "No active" in canvas.legend


def test_element_list_field_compatibility_and_selected_chart(qt_app, monkeypatch):
    result = synthetic_result()
    window = MainWindow()
    window.set_model(result.model, result)
    objects = window.result_objects
    assert objects.count() == 4  # whole model, rock region, lining, bolt
    assert objects.findData("region:1") >= 0
    objects.setCurrentIndex(objects.findData("structure:lining"))
    window.fields.setCurrentText("M")
    assert window.canvas.diagram_tags == ["lining"] and window.canvas.nvm_count == 4
    assert window.chart_button.isEnabled()
    opened = []
    monkeypatch.setattr(window, "show_structure_forces", opened.append)
    window.chart_button.click()
    assert opened == ["lining"]
    objects.setCurrentIndex(objects.findData("structure:bolt"))
    assert window.fields.currentText() == "|u|"
    assert not window.fields.model().item(window.fields.findText("M")).isEnabled()
    window.fields.setCurrentText("N")
    assert window.canvas.diagram_tags == ["bolt"] and window.canvas.field_unit == "kN"
    objects.setCurrentIndex(0)
    assert window.fields.currentText() == "|u|"
    assert not window.chart_button.isEnabled()
    window.set_model(result.model, result)
    assert objects.count() == 4
    dialog = StructureForceDialog(result, 1, "lining")
    assert np.isnan(dialog.trace.x).sum() == 1
    assert np.isnan(dialog.disp_plots[0].x).sum() == 1
    assert dialog.status.text().startswith("N: min 1 kN/m")
    dialog.show()
    qt_app.processEvents()
    assert not dialog.trace.grab().isNull()
    inactive = StructureForceDialog(result, 0, "lining")
    assert inactive.stage.currentIndex() == 0
    assert not inactive.segments and "inactive" in inactive.status.text()


def test_result_list_includes_interfaces_and_preserves_selection(qt_app):
    from slipsurface.fe2d.gui.demo import excavation_model

    model = excavation_model()
    window = MainWindow()
    window.set_model(model)
    picker = window.result_objects
    assert picker.count() == 1 + len(model.mesh.regions()) + len(model.structure_tags())
    for tag in model.structure_tags():
        assert picker.findData(f"structure:{tag}") >= 0
    interface = next(t for t, k in model.structure_tags().items() if k == "interface")
    picker.setCurrentIndex(picker.findData(f"structure:{interface}"))
    window.set_model(model)
    assert window.result_selection() == ("structure", interface)
    assert not window.fields.model().item(window.fields.findText("N")).isEnabled()
    assert any(i.data(0) == ("structure", interface) for i in window.canvas.scene().items())


def test_tunnel_placement_preserves_user_schedule_and_adds_inactive_supports(qt_app):
    ground = replace(
        Drawing.example(),
        entities=(Entity("Soil", "region", ((0, 0), (40, 0), (40, 30), (0, 30))),),
        sequence=(ConstructionStep("My excavation"), ConstructionStep("My support")),
        h=4,
    )
    design = TunnelDesign(
        TunnelSection(radius=4, wall_radius=7, wall_height=1.5, invert_level=-1.5), bolts=None
    )
    drawing = place_tunnel(ground, design, (20, 15))
    assert drawing.sequence == ground.sequence
    assert drawing.supports and all(not s.active for s in drawing.supports)
    assert [s.name for s in drawing.build_model().stages] == [
        "CAD loading",
        "My excavation",
        "My support",
    ]
    window = MainWindow()
    window.cad.commit(ground)
    window.cad.insert_tunnel(design, (20, 15))
    assert window.cad.document.sequence == ground.sequence
    assert window.model_stage_tabs.count() == 4
    assert "unchanged" in window.cad.status.text()
    designer = TunnelDesignerDialog(design)
    assert not hasattr(designer, "separate")
    assert designer.design().section == design.section


def test_manual_bolt_spacing_and_boundary_rules_are_preserved():
    drawing = Drawing.example()
    # Add bolts inward on the top edge, where the pressure rule must survive splitting.
    out = bolt_pattern_along(
        drawing, "Soil", spacing=2.5, length=1, angle=90, edge_index=2, active=False
    )
    bolts = [e for e in out.entities if e.name.startswith("Bolt_")]
    heads = sorted(b.points[0][0] for b in bolts)
    np.testing.assert_allclose(np.diff(heads), 2.5, atol=1e-7)
    assert all(b.points[1][1] == pytest.approx(5) for b in bolts)
    assert all(not s.active for s in out.supports)
    edges = dict(zip(out.entities[0].edge_names(), out.entities[0].segments()))
    total_pressure = sum(
        r.pressure * np.linalg.norm(np.subtract(*edges[r.edge])) for r in out.rules
    )
    assert total_pressure == pytest.approx(50 * 12)
    assert sum(r.ux for r in out.rules) == 3 and sum(r.uy for r in out.rules) == 1
    assert out.sequence == drawing.sequence
    meshed = out.build_model()
    assert len(meshed.stages) == 1 and not meshed.stages[0].active_structures
    with pytest.raises(ValueError, match="positive"):
        bolt_stations(10, 0)

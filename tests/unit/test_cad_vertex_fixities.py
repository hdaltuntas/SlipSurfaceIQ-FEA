"""CAD vertex fixities survive project serialization and discretization."""

from dataclasses import replace

import pytest

from slipsurface.fe2d.cad.geometry import Drawing, Entity


def base_drawing():
    return Drawing(
        entities=(Entity("Soil", "region", ((0, 0), (8, 0), (8, 5), (0, 5))),),
        h=2.0,
    )


def test_point_fixities_roundtrip_and_map_to_exact_fem_node():
    drawing = replace(base_drawing(), point_fixities=(
        {"x": 0.0, "y": 0.0, "ux": True, "uy": True},
        {"x": 8.0, "y": 5.0, "ux": True, "uy": False},
    ))
    again = Drawing.from_dict(drawing.to_dict())
    assert again.point_fixities == drawing.point_fixities
    model = again.build_model()
    fixes = {f.node_set: f for f in model.fixities}
    assert (fixes["CAD_Point_Fixity_1"].ux, fixes["CAD_Point_Fixity_1"].uy) == (True, True)
    assert (fixes["CAD_Point_Fixity_2"].ux, fixes["CAD_Point_Fixity_2"].uy) == (True, False)
    first = model.mesh.node_sets["CAD_Point_Fixity_1"][0]
    second = model.mesh.node_sets["CAD_Point_Fixity_2"][0]
    assert tuple(model.mesh.coords[first]) == pytest.approx((0.0, 0.0))
    assert tuple(model.mesh.coords[second]) == pytest.approx((8.0, 5.0))


def test_point_fixity_rejects_location_without_cad_vertex():
    drawing = replace(base_drawing(), point_fixities=(
        {"x": 4.0, "y": 2.0, "ux": True, "uy": False},
    ))
    with pytest.raises(ValueError, match="existing CAD vertex"):
        drawing.validate()


@pytest.mark.parametrize("rule", [
    {"x": 0, "y": 0, "ux": 1, "uy": False},
    {"x": 0, "y": 0, "ux": True, "uy": None},
    {"x": float("nan"), "y": 0, "ux": True, "uy": False},
])
def test_point_fixity_invalid_input(rule):
    with pytest.raises(ValueError, match="Invalid point fixity"):
        replace(base_drawing(), point_fixities=(rule,))


def test_two_rules_at_same_vertex_rejected():
    rule = {"x": 0., "y": 0., "ux": True, "uy": True}
    with pytest.raises(ValueError, match="Duplicate point fixity"):
        replace(base_drawing(), point_fixities=(rule, rule))


def test_point_fixities_optional_in_legacy_drawing():
    document = base_drawing().to_dict()
    document.pop("point_fixities")
    document.pop("mesh_refinements")
    loaded = Drawing.from_dict(document)
    assert loaded.point_fixities == ()
    assert loaded.mesh_refinements == ()


def test_gui_vertex_rule_is_undoable(qt_app):
    pytest.importorskip("PySide6")
    pytest.importorskip("shapely")
    from slipsurface.fe2d.gui.app import MainWindow

    window = MainWindow()
    try:
        cad = window.cad
        cad.commit(base_drawing())
        cad.set_vertex_rule(0.0, 0.0, True, False)
        assert cad.document.point_fixities[0]["ux"]
        assert cad.canvas.point_fixities == cad.document.point_fixities
        cad.undo()
        assert cad.document.point_fixities == ()
    finally:
        window.cad.saved_drawing = window.cad.current_drawing()
        window.dirty = False
        window.close()


def test_moving_restrained_vertex_preserves_its_restraint(qt_app):
    pytest.importorskip("PySide6")
    pytest.importorskip("shapely")
    from slipsurface.fe2d.gui.app import MainWindow

    window = MainWindow()
    try:
        cad = window.cad
        cad.commit(base_drawing())
        cad.set_vertex_rule(0.0, 0.0, True, True)
        cad.move_vertex((0, 0), (-1, 0))
        assert cad.document.point_fixities == (
            {"x": -1.0, "y": 0.0, "ux": True, "uy": True},
        )
        cad.undo()
        assert cad.document.point_fixities[0]["x"] == 0.0
    finally:
        window.close()


def test_starting_draw_tool_disables_fixity_pick(qt_app):
    pytest.importorskip("PySide6")
    pytest.importorskip("shapely")
    from slipsurface.fe2d.gui.app import MainWindow

    window = MainWindow()
    try:
        cad = window.cad
        cad.fixity_action.setChecked(True)
        assert cad.canvas.fixity_pick_enabled
        cad.start_tool("region")
        assert not cad.fixity_action.isChecked()
        assert not cad.canvas.fixity_pick_enabled
        cad.cancel_drawing()
    finally:
        window.close()

"""Boundary drag placement and invalid corner moves through the real mouse event path."""

from dataclasses import replace

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("shapely")
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QMessageBox

from slipsurface.fe2d.cad.bolt_path import selected_path
from slipsurface.fe2d.cad.geometry import BoundaryRule, Drawing, Entity
from slipsurface.fe2d.cad.tunnel import BoltPattern, TunnelDesign, bolt_layout, bolt_pattern_along
from slipsurface.fe2d.gui.app import MainWindow
from slipsurface.fe2d.gui.tunnel_designer import BoltPatternDialog, TunnelDesignerDialog


@pytest.fixture
def window(qt_app, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Discard)
    win = MainWindow()
    win.resize(1280, 840)
    win.show()
    base = Drawing.example()
    win.cad.commit(replace(base, entities=(*base.entities, Entity(
        "Opening", "region", ((4, 2), (8, 2), (8, 4), (4, 4)), 2,
    ))))
    win.cad.canvas.fit_drawing()
    qt_app.processEvents()
    yield win
    win.close()


def point(canvas, xy):
    return canvas.mapFromScene(QPointF(xy[0], -xy[1]))


def drag(canvas, path):
    viewport = canvas.viewport()
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=point(canvas, path[0]))
    for xy in path[1:]:
        QTest.mouseMove(viewport, point(canvas, xy))
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=point(canvas, path[-1]))


@pytest.mark.parametrize("reverse", [False, True])
def test_drag_limits_bolts_to_interval_and_previews_exact_result(window, monkeypatch, reverse):
    cad = window.cad
    before = cad.document
    history = len(cad.undo_stack)
    seen = []

    def accept(dialog):
        assert dialog.chain_length == pytest.approx(2, abs=0.08)
        assert dialog.angle.value() == -90
        assert not dialog.active.isChecked()
        dialog.spacing_along.setValue(1)
        dialog.length.setValue(1)
        seen.extend(cad.canvas.bolt_drag.layout)
        assert len(seen) == 2
        assert cad.document == before  # a preview cannot write the drawing
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(BoltPatternDialog, "exec", accept)
    cad.bolt_pattern()
    assert cad.document == before and len(cad.undo_stack) == history
    path = [(5, 4), (6, 4), (7, 4)]
    drag(cad.canvas, path[::-1] if reverse else path)
    bolts = [e for e in cad.document.entities if e.name.startswith("Bolt_")]
    assert len(bolts) == 2
    for bolt, (_, _, head, tail) in zip(bolts, seen):
        assert bolt.points == (head, tail)
        assert 5 < head[0] < 7 and head[1] == 4 and tail[1] == 5
    assert len(cad.undo_stack) == history + 1
    assert not cad.canvas.bolt_drag.enabled
    assert all(not s.active for s in cad.document.supports)
    cad.undo()
    assert cad.document == before


def test_click_escape_off_boundary_and_dialog_cancel_are_noops(window, monkeypatch):
    cad = window.cad
    before, history = cad.document, len(cad.undo_stack)
    calls = []

    def cancel(dialog):
        calls.append(1)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(BoltPatternDialog, "exec", cancel)
    cad.bolt_pattern()
    drag(cad.canvas, [(6, 4)])  # simple click must not plant anything
    drag(cad.canvas, [(6, 4), (6, 5)])  # release off the boundary
    assert not calls
    QTest.keyClick(cad.canvas.viewport(), Qt.Key.Key_Escape)
    assert not cad.canvas.bolt_drag.enabled
    cad.bolt_pattern()
    drag(cad.canvas, [(5, 4), (6, 4), (7, 4)])
    assert calls == [1]
    assert cad.document == before and len(cad.undo_stack) == history
    assert not cad.canvas.bolt_drag.layout


def test_range_crosses_closed_seam_without_remainder_or_duplicate_bolts():
    region = Entity("Opening", "region", ((4, 2), (8, 2), (8, 4), (4, 4)), 2)
    # Total length 12: from the middle of the closing left wall into the bottom edge.
    pattern = BoltPattern(spacing=0.5, length=0.5)
    layout = bolt_layout(region, pattern, -90, selected_range=(11, 13))
    reverse = bolt_layout(region, pattern, -90, selected_range=(13, 11))
    assert layout == reverse and len(layout) == 4
    assert {k for k, *_ in layout} == {0, 3}
    np.testing.assert_allclose(selected_path(region, (11, 13)), [(4, 3), (4, 2), (5, 2)])
    base = Drawing.example()
    drawing = replace(base, entities=(*base.entities, region))
    out = bolt_pattern_along(drawing, "Opening", pattern=pattern,
                             angle=-90, selected_range=(11, 13))
    assert len(out.supports) == 4
    assert len(set(e.points[0] for e in out.entities[2:])) == 4
    with pytest.raises(ValueError, match="interval"):
        bolt_layout(region, pattern, selected_range=(0, 13))


def test_tunnel_placement_and_saved_design_do_not_add_bolts(window):
    design = TunnelDesign()  # includes legacy/API bolt definitions
    designer = TunnelDesignerDialog(design)
    assert designer.design().bolts is None
    designer._load(design.to_dict())
    assert designer.design().bolts is None
    base = replace(Drawing.example(), entities=(Entity(
        "Ground", "region", ((-20, -20), (20, -20), (20, 20), (-20, 20)), 1,
    ),), rules=())
    window.cad.commit(base)
    window.cad.insert_tunnel(design, (0, 0))
    assert not any(s.kind == "bolt" for s in window.cad.document.supports)
    assert window.cad.document.sequence == base.sequence
    designer.deleteLater()


def test_curved_lining_drag_avoids_excavation_divider_and_remeshes(window, qt_app, monkeypatch):
    cad = window.cad
    base = Drawing(entities=(Entity(
        "Ground", "region", ((-15, -15), (15, -15), (15, 15), (-15, 15)), 1,
    ),), rules=(BoundaryRule("Ground:1", True, True),), h=3)
    cad.commit(base)
    cad.insert_tunnel(TunnelDesign(), (0, 0))
    before = cad.document
    liner = next(e for e in before.entities if "SC_Head" in e.name)
    cad.canvas.fit_drawing()
    qt_app.processEvents()
    path = [p for p in liner.points if p[1] >= 2]
    assert len(path) > 5
    seen = []

    def accept(dialog):
        assert cad.canvas.bolt_drag.host.name == liner.name
        dialog.length.setValue(1)
        dialog.spacing_along.setValue(1.5)
        seen.extend(cad.canvas.bolt_drag.layout)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(BoltPatternDialog, "exec", accept)
    cad.bolt_pattern()
    drag(cad.canvas, path)
    assert seen and all(tail[1] > head[1] > 1.9 for _, _, head, tail in seen)
    assert len(cad.document.supports) == len(before.supports) + len(seen)
    model = cad.document.build_model()
    assert model.mesh.nn > 0
    assert not cad.document.sequence


@pytest.mark.parametrize("new", [(6, 1), (8, 2)])
def test_invalid_corner_drag_preserves_geometry_and_history(window, new):
    # Self-intersection and repeated-point collapse both failed before commit's try block.
    cad = window.cad
    cad.entities.setCurrentRow(1)
    before = cad.document
    history, redo = list(cad.undo_stack), list(cad.redo_stack)
    drag(cad.canvas, [(4, 4), new])
    assert cad.document == before
    assert cad.undo_stack == history and cad.redo_stack == redo
    assert "Corner move cancelled" in cad.status.text()
    assert cad.entities.currentRow() == 1

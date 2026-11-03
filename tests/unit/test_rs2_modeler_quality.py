"""RS2-style mesh preflight and native CAD model explorer."""

import numpy as np
import pytest

from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.gui.mesh_quality import mesh_quality_report
from slipsurface.fe2d.model.mesh import ElementBlock, Mesh


def test_triangular_mesh_geometry_quality():
    mesh = Mesh(
        np.array([[0., 0.], [2., 0.], [0., 2.], [2., 2.]]),
        (ElementBlock(ElemType.T3, np.array([[0, 1, 2], [1, 3, 2]]),
                      np.array([1, 1])),),
    )
    result = mesh_quality_report(mesh)
    assert result.elements == 2
    assert result.minimum_area == pytest.approx(2.0)
    assert result.median_area == pytest.approx(2.0)
    assert result.inverted_or_degenerate == 0
    assert result.tiny_elements == 0


def test_area_preflight_handles_quadrilateral():
    mesh = Mesh(
        np.array([[0., 0.], [3., 0.], [3., 2.], [0., 2.]]),
        (ElementBlock(ElemType.Q4, np.array([[0, 1, 2, 3]]),
                      np.array([1])),),
    )
    assert mesh_quality_report(mesh).minimum_area == pytest.approx(6.0)


def test_model_explorer_selects_and_hides_a_region(qt_app):
    pytest.importorskip("PySide6")
    pytest.importorskip("shapely")
    from PySide6.QtCore import Qt

    from slipsurface.fe2d.cad.geometry import Drawing, Entity
    from slipsurface.fe2d.gui.app import MainWindow

    window = MainWindow()
    try:
        window.cad.commit(Drawing(entities=(
            Entity("Ground", "region", ((0, 0), (8, 0), (8, 5), (0, 5)), 1),
        )))
        tree = window.cad.model_tree
        root = tree.topLevelItem(0)
        assert root.childCount() == 1
        entity = root.child(0)
        assert entity.text(0) == "Ground"
        entity.setCheckState(0, Qt.CheckState.Unchecked)
        assert "Ground" in window.cad.canvas.hidden_entities
        entity.setCheckState(0, Qt.CheckState.Checked)
        assert "Ground" not in window.cad.canvas.hidden_entities
    finally:
        window.close()


def test_t6_curved_element_detects_negative_gauss_jacobian():
    """Corners have positive area but a misplaced midside node folds T6 mapping."""
    coords = np.array([
        [0., 0.], [2., 0.], [0., 2.],
        [1., 1.], [1., 1.], [0., 1.],
    ])
    mesh = Mesh(
        coords,
        (ElementBlock(ElemType.T6, np.array([[0, 1, 2, 3, 4, 5]]),
                      np.array([1])),),
    )
    report = mesh_quality_report(mesh, batch_size=1)
    assert report.minimum_area == pytest.approx(2.0)
    assert report.inverted_or_degenerate == 0
    assert report.nonpositive_jacobian_elements == 1
    assert report.minimum_jacobian < 0
    assert report.sampled_gauss_points == 3


def test_straight_t6_and_batch_invariance():
    coords = np.array([
        [0., 0.], [2., 0.], [0., 2.],
        [1., 0.], [1., 1.], [0., 1.],
    ])
    mesh = Mesh(
        coords,
        (ElementBlock(ElemType.T6, np.array([[0, 1, 2, 3, 4, 5]]),
                      np.array([1])),),
    )
    a = mesh_quality_report(mesh, batch_size=1)
    b = mesh_quality_report(mesh, batch_size=2048)
    assert a == b
    assert a.nonpositive_jacobian_elements == 0
    assert a.minimum_jacobian == pytest.approx(4.0)


def test_compute_refuses_folded_t6_before_solver_worker(qt_app, monkeypatch):
    """A positive corner area cannot bypass the high-order mesh preflight."""
    pytest.importorskip("PySide6")
    pytest.importorskip("shapely")
    from PySide6.QtWidgets import QMessageBox

    from slipsurface.fe2d import api
    from slipsurface.fe2d.gui.app import MainWindow

    coords = np.array([
        [0., 0.], [2., 0.], [0., 2.],
        [1., 1.], [1., 1.], [0., 1.],
    ])
    mesh = Mesh(
        coords,
        (ElementBlock(ElemType.T6, np.array([[0, 1, 2, 3, 4, 5]]),
                      np.array([1])),),
    )
    model = api.Model(
        api.Analysis.PLANE_STRAIN, mesh,
        {"soil": api.MaterialSpec.elastic("soil", 20000.0, 0.3)},
        {1: "soil"},
    )
    window = MainWindow()
    warnings = []
    try:
        window.set_model(model)
        monkeypatch.setattr(
            QMessageBox, "warning",
            lambda *args: warnings.append(args[2]),
        )
        window.start_solve()
        assert warnings and "Jacobian" in warnings[0]
        assert window.worker is None
    finally:
        window.close()

"""F7 structural result coverage detects missing/inactive support data."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.model.mesh import ElementBlock, Mesh
from slipsurface.fe2d.post.support_result_coverage import stage_support_result_coverage


def case():
    coords = np.array([
        [0., 0.], [0., -1.],
        [1., 0.], [1., -1.],
        [2., 0.], [2., -1.],
    ])
    blocks = (
        ElementBlock(ElemType.BEAM2, np.array([[0, 1]]), np.array([0]), "pile"),
        ElementBlock(ElemType.BAR2, np.array([[2, 3]]), np.array([0]), "anchor"),
        ElementBlock(
            ElemType.IFACE4, np.array([[0, 1, 4, 5]]), np.array([0]), "skin",
        ),
    )
    mesh = Mesh(coords, blocks)
    model = SimpleNamespace(
        mesh=mesh, liners={"pile": object()}, bolts={"anchor": object()},
        interfaces={"skin": object()},
    )
    stage = SimpleNamespace(
        active={
            "pile": np.array([True]), "anchor": np.array([False]),
            "skin": np.array([True]),
        },
        beams={"pile": np.zeros((1, 2, 3))},
        bars={"anchor": np.full(1, np.nan)},
        interfaces={"skin": np.zeros((1, 2, 2))},
    )
    return model, stage


def test_expected_active_pile_and_interface_with_dormant_anchor_are_covered():
    model, stage = case()
    out = stage_support_result_coverage(model, stage, {"pile", "skin"})
    assert out["status"] == "passed"
    assert out["checked_structures"] == 3
    assert out["failed_structures"] == 0
    assert {row["tag"] for row in out["details"]} == {
        "pile", "skin", "anchor",
    }


def test_missing_anchor_output_cannot_pass():
    model, stage = case()
    del stage.bars["anchor"]
    out = stage_support_result_coverage(model, stage, {"pile", "skin"})
    assert out["status"] == "failed"
    assert out["failed_structures"] == 1
    assert any(row["status"] == "missing" for row in out["details"])


def test_unexpected_active_anchor_cannot_pass():
    model, stage = case()
    stage.active["anchor"][0] = True
    stage.bars["anchor"][0] = 5.
    out = stage_support_result_coverage(model, stage, {"pile", "skin"})
    assert out["status"] == "failed"
    assert any(row["tag"] == "anchor" and row["status"] == "failed"
               for row in out["details"])


def test_nonfinite_active_interface_and_inactive_non_nan_support_fail():
    model, stage = case()
    stage.interfaces["skin"][0, 0, 0] = np.nan
    stage.bars["anchor"][0] = 0.
    out = stage_support_result_coverage(model, stage, {"pile", "skin"})
    assert out["status"] == "failed"
    assert out["failed_structures"] == 2


def test_incorrect_structural_result_shape_is_rejected():
    model, stage = case()
    stage.beams["pile"] = np.zeros((1, 3))
    out = stage_support_result_coverage(model, stage, {"pile", "skin"})
    assert out["status"] == "failed"
    assert out["failed_structures"] == 1


def test_unknown_expected_support_is_rejected():
    import pytest

    model, stage = case()
    with pytest.raises(ValueError, match="not declared"):
        stage_support_result_coverage(model, stage, {"unknown"})

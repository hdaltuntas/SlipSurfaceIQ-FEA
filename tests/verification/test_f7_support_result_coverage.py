"""F7 structural result coverage detects missing/inactive support data."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

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
    model, stage = case()
    with pytest.raises(ValueError, match="not declared"):
        stage_support_result_coverage(model, stage, {"unknown"})


def test_excavation_partially_deactivates_skin_without_failing_coverage():
    model, stage = case()
    # A two-element skin loses one segment because adjacent continuum
    # was excavated; installed joint is still partially active.
    mesh = model.mesh
    original = mesh.block("skin")
    second = original.conn.copy()
    new_block = ElementBlock(
        original.etype,
        np.concatenate((original.conn, second)),
        np.array([0, 0]),
        "skin",
    )
    model.mesh = Mesh(
        mesh.coords,
        tuple(b if b.tag != "skin" else new_block for b in mesh.blocks),
    )
    stage.active["skin"] = np.array([True, False])
    stage.interfaces["skin"] = np.array([
        [[1., -2.], [1., -2.]],
        [[np.nan, np.nan], [np.nan, np.nan]],
    ])
    report = stage_support_result_coverage(model, stage, {"pile", "skin"})
    assert report["status"] == "passed"
    skin = next(x for x in report["details"] if x["tag"] == "skin")
    assert skin["active_elements"] == 1
    assert skin["total_elements"] == 2


def test_partial_skin_with_nonfinite_active_traction_still_fails():
    model, stage = case()
    stage.active["skin"] = np.array([True])
    stage.interfaces["skin"][0, 0, 0] = np.nan
    result = stage_support_result_coverage(model, stage, {"pile", "skin"})
    assert result["status"] == "failed"

"""RS2-like local CAD mesh sizing zones: serialization and mesher integration."""

from dataclasses import replace

import numpy as np
import pytest

from slipsurface.fe2d.cad.geometry import Drawing, Entity


def drawing_with_zone():
    base = Drawing(
        entities=(Entity("Ground", "region", ((0, 0), (8, 0), (8, 6), (0, 6))),),
        h=2.0,
    )
    return replace(base, mesh_refinements=(
        {"x": 4.0, "y": 3.0, "radius": 1.5, "h": 0.7},
    ))


def test_local_sizing_is_vectorized_and_graded():
    drawing = drawing_with_zone()
    fn = drawing.mesh_size_function()
    assert callable(fn)
    x = np.array([4.0, 5.5, 6.25, 7.0, 20.0])
    h = fn(x, np.full_like(x, 3.0))
    assert h == pytest.approx([0.7, 0.7, 1.35, 2.0, 2.0])
    assert drawing.mesh_size_function()(4.0, 3.0) == pytest.approx(0.7)


def test_local_refinement_roundtrips_with_cad_v2():
    drawing = drawing_with_zone()
    again = Drawing.from_dict(drawing.to_dict())
    assert again.mesh_refinements == drawing.mesh_refinements
    assert again.to_dict() == drawing.to_dict()
    legacy = drawing.to_dict()
    del legacy["mesh_refinements"]
    assert Drawing.from_dict(legacy).mesh_refinements == ()


@pytest.mark.parametrize("zone", [
    {"x": 0., "y": 0., "radius": 0., "h": 0.5},
    {"x": 0., "y": 0., "radius": 2., "h": -1.},
    {"x": float("nan"), "y": 0., "radius": 2., "h": 0.5},
])
def test_refinement_validation(zone):
    with pytest.raises(ValueError, match="Mesh refinement"):
        replace(drawing_with_zone(), mesh_refinements=(zone,))


def test_locally_refined_mesh_has_more_nodes():
    base = Drawing(
        entities=(Entity("Ground", "region", ((0, 0), (8, 0), (8, 6), (0, 6))),),
        h=2.0,
    )
    refined = replace(base, mesh_refinements=(
        {"x": 4.0, "y": 3.0, "radius": 2.0, "h": 0.9},
    ))
    coarse_mesh = base.build_model().mesh
    fine_mesh = refined.build_model().mesh
    assert fine_mesh.nn > coarse_mesh.nn
    assert sum(b.ne for b in fine_mesh.continuum_blocks()) > sum(
        b.ne for b in coarse_mesh.continuum_blocks()
    )

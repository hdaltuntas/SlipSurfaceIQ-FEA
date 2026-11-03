"""F7 exact area clipping under a water table that cuts mesh elements."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.mesh import layered_box, rectangle
from slipsurface.fe2d.post.saturated_column_balance import (
    exact_cut_saturated_column_budget_by_stage,
    saturated_column_budget,
)
from slipsurface.fe2d.post.water_table_geometry import (
    area_below_horizontal_head,
    mesh_element_water_areas,
    polygon_area,
)


@pytest.mark.parametrize("head,wet", [
    (-2., 0.), (-1.5, 2.), (0., 8.), (1., 8.),
])
def test_exact_rectangle_clip_for_horizontal_groundwater(head, wet):
    vertices = np.array([[0., -2.], [4., -2.], [4., 0.], [0., 0.]])
    assert polygon_area(vertices) == pytest.approx(8.)
    assert area_below_horizontal_head(vertices, head) == pytest.approx(wet)


@pytest.mark.parametrize("etype", [ElemType.T3, ElemType.T6, ElemType.Q4, ElemType.Q8])
def test_mesh_water_areas_are_conservative_across_four_element_types(etype):
    mesh = rectangle(4., 2., 4, 2, etype=etype, origin=(0., -2.))
    split = mesh_element_water_areas(mesh, -1.5)
    dry, wet = split["soil"]
    assert wet.sum() == pytest.approx(2., abs=1e-10)
    assert dry.sum() == pytest.approx(6., abs=1e-10)
    assert np.all(dry >= 0.)
    assert np.all(wet >= 0.)


def test_exact_cut_reference_retains_unaligned_water_table_as_measured_error():
    mesh = layered_box(2., [0., -4.], -10., nx=2, ny_per_layer=[4, 6])
    material = api.MaterialSpec.elastic(
        "soil", 20000., 0.3, gamma=17., gamma_sat=20.,
    )
    model = api.Model(
        api.Analysis.PLANE_STRAIN, mesh,
        {"soil": material}, {1: "soil", 2: "soil"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        initial=api.InitialStress(
            "gravity", water=api.WaterCondition.piezo([(0., -2.5)])
        ),
    )
    result = api.run(model)
    with pytest.raises(ValueError, match="element edges"):
        saturated_column_budget(model, result)
    exact = saturated_column_budget(model, result, exact_cut=True)
    expected = 2. * (2.5 * 17. + 7.5 * 20.)
    assert exact["expected_ry_kn_per_m"] == pytest.approx(expected, rel=1e-10)
    assert exact["water_table_cut_elements"] > 0
    assert exact["reference_method"] == "exact_polygon_clip"
    assert np.isfinite(exact["relative_residual"])
    rows = exact_cut_saturated_column_budget_by_stage(model, result)
    assert rows[0]["status"] in {"passed", "failed"}
    assert rows[0]["status"] != "unsupported"


def test_quadratic_curved_side_is_not_treated_as_straight_polygon():
    mesh = rectangle(2., 2., 1, 1, etype=ElemType.Q8, origin=(0., -2.))
    coords = mesh.coords.copy()
    block = mesh.continuum_blocks()[0]
    coords[block.conn[0, 4], 1] += 0.1
    curved = replace(mesh, coords=coords)
    with pytest.raises(ValueError, match="Curved quadratic"):
        mesh_element_water_areas(curved, -1.)

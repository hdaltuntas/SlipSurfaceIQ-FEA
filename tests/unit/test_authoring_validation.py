"""Reject invalid authoring data before it reaches assembly or groundwater solves."""

from dataclasses import replace

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.errors import ModelError
from slipsurface.fe2d.mesh import rectangle
from slipsurface.fe2d.model.boundary import Displacement


def model():
    return api.Model(
        api.Analysis.PLANE_STRAIN,
        rectangle(2, 2, 1, 1),
        {"soil": api.MaterialSpec.elastic("soil", 20000, 0.3)},
        {1: "soil"},
        initial=api.InitialStress("none"),
        stages=[api.Stage("load")],
    )


@pytest.mark.parametrize(
    "water",
    [
        lambda: api.WaterCondition.piezo([(0, float("nan"))]),
        lambda: api.WaterCondition.piezo([(1, 2), (1, 3)]),
        lambda: api.WaterCondition.piezo([]),
        lambda: api.WaterCondition.seepage({"left": float("inf")}),
        lambda: api.WaterCondition.seepage({"left": 2}, {"top": float("nan")}),
    ],
)
def test_invalid_water_values_are_rejected(water):
    with pytest.raises(ValueError):
        water()


def test_horizontal_and_unsorted_valid_piezo_lines():
    assert api.WaterCondition.piezo([(2, 3), (0, 5)]).head(np.array([1])) == [4]
    assert api.WaterCondition.piezo([(2, 3)]).head(np.array([-10, 10])).tolist() == [3, 3]


@pytest.mark.parametrize(
    "initial,stage",
    [
        (api.InitialStress("field", field=(1, 2, 3)), None),
        (api.InitialStress("field", field=(1, 2, 3, float("nan"))), None),
        (api.InitialStress("k0_field", k0=float("inf")), None),
        (api.InitialStress("none", active_regions={9}), None),
        (api.InitialStress("none", water=api.WaterCondition.seepage({"missing": 1})), None),
        (None, api.Stage("load", loads=(api.PointLoad(0, float("nan")),))),
        (None, api.Stage("load", loads=(api.EdgeLoad("top", float("inf")),))),
        (None, api.Stage("load", material_override={9: "soil"})),
        (None, api.Stage("load", displacements=(Displacement("top", uy=float("nan")),))),
        (None, api.Stage("load", water=api.WaterCondition.seepage({"missing": 1}))),
    ],
)
def test_invalid_model_edits_fail_early(initial, stage):
    m = model()
    with pytest.raises(ModelError):
        replace(m, initial=initial or m.initial, stages=[stage or m.stages[0]]).validate()


@pytest.mark.parametrize("initial", [True, False])
def test_head_bcs_require_nodes_not_only_edge_name(initial):
    m = model()
    m.mesh = api.Mesh(
        m.mesh.coords,
        m.mesh.blocks,
        {k: v for k, v in m.mesh.node_sets.items() if k != "left"},
        m.mesh.edge_sets,
    )
    water = api.WaterCondition.seepage({"left": 1})
    if initial:
        m.initial = replace(m.initial, water=water)
    else:
        m.stages = [replace(m.stages[0], water=water)]
    with pytest.raises(ModelError, match="head node set"):
        m.validate()


@pytest.mark.parametrize(
    "spec",
    [
        lambda: api.MaterialSpec.elastic("", 1e4, 0.3),
        lambda: api.MaterialSpec.elastic("s", 1e4, 0.3, gamma=-1),
        lambda: api.MaterialSpec.elastic("s", 1e4, 0.3, gamma_sat=float("nan")),
        lambda: api.LinerSpec("wall", 1e6, 0.2, 0.2, 0, 0.1),
        lambda: api.LinerSpec("wall", 1e6, 0.2, 0.2, 0.001, 0.1, float("inf")),
        lambda: api.BoltSpec("bolt", 1e5, 100, spacing_out_of_plane=0),
        lambda: api.BoltSpec("bolt", 1e5, 100, pretension=float("nan")),
    ],
)
def test_invalid_property_values_are_rejected(spec):
    with pytest.raises(ModelError):
        spec()


def test_above_yield_pretension_remains_supported():
    # Existing solver clips installation pretension; S2 verifies its physical response.
    assert api.BoltSpec("bolt", 2e5, 50, pretension=150).pretension == 150

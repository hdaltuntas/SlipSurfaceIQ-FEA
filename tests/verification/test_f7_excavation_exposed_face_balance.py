"""Independent dry excavation reaction budget on newly exposed interior faces."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.mesh import layered_box
from slipsurface.fe2d.post.excavation_balance import excavation_stage_balance

WIDTH = 4.0
GAMMA = 18.0
PRESSURE = 20.0


def make_layered_case(etype):
    mesh = layered_box(
        WIDTH, [0., -3.], -6., nx=4, ny_per_layer=[3, 3],
        etype=etype,
    )
    block = mesh.continuum_blocks()[0]
    # Build the original *internal* soil interface edge set at y=-3.
    # The edge becomes external when the upper soil layer is excavated.
    ncorner = 3 if etype in (ElemType.T3, ElemType.T6) else 4
    edges = []
    for conn, region in zip(block.conn, block.region):
        if region != 2:
            continue
        for i in range(ncorner):
            j = (i + 1) % ncorner
            a, b = int(conn[i]), int(conn[j])
            if np.isclose(mesh.coords[a, 1], -3.) and np.isclose(
                mesh.coords[b, 1], -3.
            ):
                if etype is ElemType.T6:
                    edge = (a, b, int(conn[3 + i]))
                else:
                    edge = (a, b)
                edges.append(edge)
    assert edges
    mesh = replace(mesh, edge_sets={
        **mesh.edge_sets, "new_exposed_top": np.array(edges, dtype=int),
    })
    material = api.MaterialSpec.elastic("soil", 20000., 0.3, gamma=GAMMA)
    return api.Model(
        api.Analysis.PLANE_STRAIN, mesh, {"soil": material},
        {1: "soil", 2: "soil"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        initial=api.InitialStress("gravity"),
        stages=[
            api.Stage("before excavation", active_regions={1, 2}),
            api.Stage(
                "after excavation with top pressure",
                active_regions={2},
                loads=(api.EdgeLoad("new_exposed_top", qn=PRESSURE),),
            ),
        ],
    )


@pytest.mark.parametrize("etype", [ElemType.T3, ElemType.T6])
def test_activated_excavation_face_pressure_and_weight_balance(etype):
    model = make_layered_case(etype)
    result = api.run(model)
    before = excavation_stage_balance(model, result, 0)
    after = excavation_stage_balance(model, result, 1)
    assert before["active_soil_weight_kn_per_m"] == pytest.approx(432.)
    assert before["reaction_fy_kn_per_m"] == pytest.approx(432., rel=1e-7)
    assert before["relative_residual"] < 1e-7
    assert after["active_soil_weight_kn_per_m"] == pytest.approx(216.)
    assert after["external_fy_kn_per_m"] == pytest.approx(
        -PRESSURE * WIDTH,
    )
    assert after["reaction_fy_kn_per_m"] == pytest.approx(
        216. + PRESSURE * WIDTH, rel=1e-7,
    )
    assert after["relative_residual"] < 1e-7


def test_internal_surface_rejected_before_excavation():
    model = make_layered_case(ElemType.T3)
    from slipsurface.fe2d.post.dry_load_balance import independent_stage_loads

    with pytest.raises(ValueError, match="unique external boundary"):
        independent_stage_loads(
            model, model.stages[1],
            active_masks={"soil": np.ones(model.mesh.continuum_blocks()[0].ne, dtype=bool)},
        )


def test_partial_stage_not_falsely_certified():
    model = make_layered_case(ElemType.T3)
    modified = replace(model, stages=[
        model.stages[0],
        replace(model.stages[1], load_split=0.5),
    ])
    solved = api.run(modified)
    with pytest.raises(ValueError, match="Partial load splits"):
        excavation_stage_balance(modified, solved, 1)

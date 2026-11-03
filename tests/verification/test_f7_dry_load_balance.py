"""Independent dry edge/point load and gravity equilibrium across stages."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.mesh import rectangle
from slipsurface.fe2d.post.dry_load_balance import (
    dry_stage_load_balance,
    dry_stage_load_balance_by_stage,
    independent_stage_loads,
)

WIDTH = 4.0
HEIGHT = 6.0
GAMMA = 18.0
Q = 60.0


def base_model(etype=ElemType.T6, *, stages=None):
    mesh = rectangle(WIDTH, HEIGHT, 4, 6, etype=etype, origin=(0., -HEIGHT))
    if stages is None:
        stages = [api.Stage("pressure", loads=(api.EdgeLoad("top", qn=Q),))]
    return api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"soil": api.MaterialSpec.elastic(
            "soil", 25000.0, 0.3, gamma=GAMMA,
        )},
        region_material={1: "soil"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        initial=api.InitialStress("gravity"),
        stages=stages,
    )


@pytest.mark.parametrize("etype", [ElemType.T3, ElemType.T6, ElemType.Q4, ElemType.Q8])
def test_uniform_top_pressure_balances_gravity_and_applied_traction(etype):
    model = base_model(etype)
    result = api.run(model)
    audit = dry_stage_load_balance(model, result, 0)
    assert audit["soil_weight_kn_per_m"] == pytest.approx(
        GAMMA * WIDTH * HEIGHT, rel=1e-10,
    )
    assert audit["applied_external_fy_kn_per_m"] == pytest.approx(
        -Q * WIDTH, rel=1e-10,
    )
    assert audit["expected_ry_kn_per_m"] == pytest.approx(
        (GAMMA * HEIGHT + Q) * WIDTH, rel=1e-10,
    )
    assert audit["relative_imbalance"] < 1e-7


def test_partial_full_and_double_stage_loads_preserve_cumulative_balance():
    stages = [
        api.Stage("partial", loads=(api.EdgeLoad("top", qn=Q),), load_split=0.4),
        api.Stage("full", loads=(api.EdgeLoad("top", qn=Q),)),
        api.Stage("double", loads=(api.EdgeLoad("top", qn=2 * Q),)),
    ]
    model = base_model(stages=stages)
    result = api.run(model)
    weight = GAMMA * WIDTH * HEIGHT
    for index, factor in enumerate((0.4, 1.0, 2.0)):
        audit = dry_stage_load_balance(model, result, index)
        assert audit["applied_external_fy_kn_per_m"] == pytest.approx(
            -Q * WIDTH * factor, rel=1e-10,
        )
        assert audit["reaction_ry_kn_per_m"] == pytest.approx(
            weight + Q * WIDTH * factor, rel=1e-7,
        )
        assert audit["relative_imbalance"] < 1e-7


def test_point_force_and_top_shear_have_independent_vector_resultants():
    base = base_model()
    coords = base.mesh.coords
    point = int(np.argmin(np.linalg.norm(coords - [WIDTH / 2, 0.], axis=1)))
    stages = [
        api.Stage("horizontal", loads=(
            api.PointLoad(point, fx=10., fy=-5.),
            api.EdgeLoad("top", qn=0., qt=3.),
        )),
    ]
    model = replace(base, stages=stages)
    independent = independent_stage_loads(model, stages[0])
    # Top outward normal is +Y, CCW tangent is -X.
    assert independent == pytest.approx([10. - 3. * WIDTH, -5.])
    result = api.run(model)
    audit = dry_stage_load_balance(model, result, 0)
    assert audit["expected_rx_kn_per_m"] == pytest.approx(-independent[0])
    assert audit["expected_ry_kn_per_m"] == pytest.approx(
        GAMMA * WIDTH * HEIGHT + 5.,
    )
    assert audit["relative_imbalance"] < 1e-7


def test_rejected_water_and_changed_geometry_not_misreported_as_pass():
    base = base_model()
    changed = replace(
        base, stages=[api.Stage("excavation", active_regions=frozenset({1}))]
    )
    # Even before model evaluation, a direct declaration of excavated regions
    # is rejected by the restricted loaded-domain force budget.
    output = api.run(changed)
    rows = dry_stage_load_balance_by_stage(changed, output)
    assert rows[0]["status"] == "unsupported"
    assert "excavation" in rows[0]["reason"]

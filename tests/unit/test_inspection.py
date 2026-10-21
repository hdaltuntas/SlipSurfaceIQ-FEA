"""Post-processing must preserve topology, exact fields and beam sign conventions."""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.fem.structural import BeamGroup
from slipsurface.fe2d.mesh import rectangle
from slipsurface.fe2d.mesh.structures import add_beams
from slipsurface.fe2d.post.inspection import beam_paths, line_profile


@pytest.mark.parametrize(
    "etype", [api.ElemType.T3, api.ElemType.T6, api.ElemType.Q4, api.ElemType.Q8]
)
def test_query_constant_stress_and_linear_displacement_patch(etype):
    mesh = rectangle(3, 1, 3, 1, etype)
    model = api.Model(
        api.Analysis.PLANE_STRAIN,
        mesh,
        {"s": api.MaterialSpec.elastic("s", 20000, 0.3)},
        {1: "s"},
        fixities=(
            api.Fixity("bottom", False, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        initial=api.InitialStress("none"),
        stages=[api.Stage("load", loads=(api.EdgeLoad("top", 10),))],
    )
    result = api.run(model)
    profile = line_profile(result, (1.5, 0), (1.5, 1), "uy", 11)
    expected = -10 / (20000 * (1 - 0.3) / ((1 + 0.3) * (1 - 2 * 0.3)))
    np.testing.assert_allclose(profile.values, np.linspace(0, expected, 11), atol=1e-12)
    stress = line_profile(result, (0, 0.5), (3, 0.5), "syy", 13)
    np.testing.assert_allclose(stress.values, -10, atol=1e-9)
    block = mesh.blocks[0]
    centroids = mesh.coords[block.conn].mean(1)
    gap = (centroids[:, 0] > 1) & (centroids[:, 0] < 2)
    stage = replace(result.last, active={block.tag: ~gap})
    broken = line_profile(result, (0, 0.5), (3, 0.5), "syy", 13, stage)
    assert np.isnan(broken.values[5:8]).all()
    assert np.isfinite(broken.values[[0, -1]]).all()
    outside = line_profile(result, (4, 0), (4, 1), "uy")
    assert np.isnan(outside.values).all()


def test_beam_diagram_is_independent_of_element_order_and_direction():
    mesh = add_beams(rectangle(4, 1, 4, 1), "top", "liner")
    original = mesh.block("liner")
    spec = api.LinerSpec("liner", 1e6, 0.2, 0.1, 0.001, 0)  # valid Euler-Bernoulli option

    def solution(block):
        group = BeamGroup(block, mesh.coords, spec, api.Analysis.PLANE_STRAIN)
        X = mesh.coords[block.conn]
        disp = np.stack([0.001 * X[..., 0], 0.002 * X[..., 0] ** 2, 0.004 * X[..., 0]], axis=-1)
        f = np.einsum("eij,ej->ei", group.Kg, disp.reshape(block.ne, 6))
        stage = SimpleNamespace(
            beams={"liner": group.end_forces(f)}, active={"liner": np.ones(block.ne, bool)}
        )
        return SimpleNamespace(
            model=SimpleNamespace(mesh=replace(mesh, blocks=(block,))), last=stage
        )

    conn = original.conn.copy()
    conn[::2] = conn[::2, ::-1]
    shuffled = replace(original, conn=conn[::-1], region=original.region[::-1])
    before, after = beam_paths(solution(original), "liner"), beam_paths(solution(shuffled), "liner")
    assert len(before) == len(after) == 1
    np.testing.assert_allclose(before[0].distance, after[0].distance)
    np.testing.assert_allclose(before[0].forces, after[0].forces, atol=1e-10)
    np.testing.assert_array_equal(before[0].nodes, after[0].nodes)
    # No smoothing at shared ends; each element contributes two endpoint samples.
    assert before[0].forces.shape == (original.ne, 2, 3)

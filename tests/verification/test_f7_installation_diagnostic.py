"""Peak diagnostics must retain actual mesh end identities and signs."""

from __future__ import annotations

import runpy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

diagnostic = runpy.run_path(str(
    Path(__file__).resolve().parents[2] / "scripts/f7_installation_diagnostic.py"
))
peak_location = diagnostic["peak_location"]


def case():
    block = SimpleNamespace(ne=2, conn=np.array([[2, 0], [0, 1]]))
    mesh = SimpleNamespace(
        coords=np.array([[0., -1.], [0., -2.], [0., 0.]]),
        block=lambda tag: block,
    )
    forces = np.zeros((2, 2, 3))
    forces[1, 1, 2] = -4.
    forces[0, 0, 2] = 3.
    return mesh, SimpleNamespace(beams={"cad_Pile": forces})


def test_peak_uses_absolute_magnitude_but_retains_signed_actual_endpoint():
    mesh, stage = case()
    assert peak_location(mesh, stage) == {
        "moment": -4., "xy_m": [0., -2.], "element": 1, "end": 1,
    }


def test_nonfinite_force_is_rejected_instead_of_producing_false_peak():
    mesh, stage = case()
    stage.beams["cad_Pile"][0, 0, 2] = np.nan
    with pytest.raises(ValueError, match="finite"):
        peak_location(mesh, stage)


@pytest.mark.parametrize("element_type", ["T6", "Q8"])
def test_symmetric_control_closes_isolated_nodes_and_has_no_bending(element_type):
    pytest.importorskip("shapely")
    from slipsurface.fe2d import api
    from slipsurface.fe2d.core.enums import ElemType
    from slipsurface.fe2d.gui.demo import excavation_model
    from slipsurface.fe2d.post.pile_installation_budget import pile_installation_budget

    model = diagnostic["symmetric_case"](
        excavation_model(), 4, 14, ElemType[element_type],
    )
    # Verify reflected continuum topology, rather than just a symmetric point cloud.
    cells = []
    reflected = []
    for block in model.mesh.continuum_blocks():
        for conn in block.conn:
            xy = model.mesh.coords[conn]
            cells.append(tuple(sorted(map(tuple, np.round(xy, 10)))))
            mirror = xy * [-1, 1]
            reflected.append(tuple(sorted(map(tuple, np.round(mirror, 10)))))
    assert sorted(cells) == sorted(reflected)
    stage = api.run(model).last
    assert abs(peak_location(model.mesh, stage)["moment"]) < 1e-8
    budget = pile_installation_budget(model, stage, "cad_Pile")
    isolated = [n for n in budget["nodes"] if not n["shared_continuum"]]
    shared = [n for n in budget["nodes"] if n["shared_continuum"]]
    assert isolated
    assert [n["xy_m"] for n in shared] == [[0., -9.]]
    assert np.max(np.abs([n["residual_without_continuum"] for n in isolated])) < 1e-8
    assert abs(shared[0]["residual_without_continuum"][1]) > 1.
    assert budget["max_complete_force_residual"] < 1e-8
    assert budget["max_complete_moment_residual"] < 1e-8
    assert np.max(np.abs(shared[0]["complete_residual"])) < 1e-8
    # Corrupt a tip-adjacent continuum stress; the completed tip budget must detect it.
    soil = model.mesh.continuum_blocks()[0]
    tip = shared[0]["node"]
    cell = np.flatnonzero(np.any(soil.conn == tip, axis=1))[0]
    original = stage.sig[soil.tag][cell].copy()
    stage.sig[soil.tag][cell, :, 1] += 100.
    changed = pile_installation_budget(model, stage, "cad_Pile")
    tip_budget = next(n for n in changed["nodes"] if n["node"] == tip)
    assert abs(tip_budget["complete_residual"][1]) > 1.
    stage.sig[soil.tag][cell] = original
    # A corrupted beam output must be visible in the reconstructed force budget.
    stage.beams["cad_Pile"][0, 0, 1] += 1.
    corrupted = pile_installation_budget(model, stage, "cad_Pile")
    assert max(abs(n["residual_without_continuum"][0])
               for n in corrupted["nodes"]) > 0.9
    loaded = replace(model, stages=[replace(model.stages[0], seismic_kh=0.1)])
    with pytest.raises(ValueError, match="separate terms"):
        pile_installation_budget(loaded, stage, "cad_Pile")


def test_constant_stress_square_has_analytical_soil_force_body_and_reaction_terms():
    from slipsurface.fe2d import api
    from slipsurface.fe2d.core.enums import ElemType
    from slipsurface.fe2d.model.mesh import ElementBlock, Mesh
    from slipsurface.fe2d.post.pile_installation_budget import pile_installation_budget

    mesh = Mesh(np.array([[0., 0.], [1., 0.], [1., 1.], [0., 1.]]), (
        ElementBlock(ElemType.Q4, np.array([[0, 1, 2, 3]]), np.array([1]), "soil"),
        ElementBlock(ElemType.BEAM2, np.array([[2, 3]]), np.array([0]), "pile"),
    ))
    step = api.Stage("installation", active_structures={"pile"})
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN, mesh=mesh,
        materials={"soil": api.MaterialSpec.elastic("soil", E=1e4, nu=0.3, gamma=20.)},
        region_material={1: "soil"}, stages=[step],
        liners={"pile": api.LinerSpec("pile", E=1e6, nu=0.2, A=0.1, I=0.01, As=0.1)},
        initial=api.InitialStress("gravity"),
    )
    # Integrating constant traction on the unit square gives these nodal vectors.
    internal = np.array([[-3., -3.5], [-1., 0.5], [3., 3.5], [1., -0.5]])
    reactions = np.zeros((4, 3))
    reactions[:, :2] = internal + [0., 5.]
    stage = SimpleNamespace(
        name=step.name, lam=1., active={"soil": np.array([True]), "pile": np.array([True])},
        beams={"pile": np.zeros((1, 2, 3))}, interfaces={},
        sig={"soil": np.tile([2., 3., 0., 4.], (1, 4, 1))},
        pore={}, excess_pore={}, reactions=reactions,
    )
    result = pile_installation_budget(model, stage, "pile")
    for node in result["nodes"]:
        np.testing.assert_allclose(node["soil_internal"][:2], internal[node["node"]])
        np.testing.assert_allclose(node["soil_body"], [0., -5., 0.])
        np.testing.assert_allclose(node["complete_residual"], 0., atol=1e-12)
    # Missing continuum data must fail closed.
    stage.sig["soil"][0, 0, 1] = np.nan
    with pytest.raises(ValueError, match="continuum stresses"):
        pile_installation_budget(model, stage, "pile")

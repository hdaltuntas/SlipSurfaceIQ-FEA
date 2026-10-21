"""Mixed-order-matched T3/Q4 and T6/Q8 patches, stages and persistence."""

from __future__ import annotations

import numpy as np
import pytest
from conftest import distort, per_node_displacements

from slipsurface.fe2d import api
from slipsurface.fe2d.fem.materials import isotropic_D
from slipsurface.fe2d.mesh import mesh_quality, recombine_mesh, rectangle


@pytest.mark.parametrize("etype", [api.ElemType.T3, api.ElemType.T6])
@pytest.mark.parametrize("order", ["default", "high"])
@pytest.mark.parametrize("axisymmetric", [False, True])
def test_mixed_displacement_patch(etype, order, axisymmetric):
    source = distort(rectangle(2, 1, 6, 4, etype, origin=(1, 0)), 0.04, seed=7)
    mesh = recombine_mesh(source, where=lambda x: x[:, 0] < 2)
    assert mesh_quality(mesh).n_quads > 0 and mesh_quality(mesh).n_triangles > 0
    A = np.array([[1e-3, 2e-4], [-5e-4, -2e-3]])
    if axisymmetric:

        def field(x, y):
            return np.array([1e-3 * x, -2e-3 * y])

        eps = np.array([1e-3, -2e-3, 1e-3, 0])
    else:

        def field(x, y):
            return A @ np.array([x, y]) + [0.001, -0.002]

        eps = np.array([A[0, 0], A[1, 1], 0, A[0, 1] + A[1, 0]])
    boundary = np.unique(
        np.concatenate([mesh.nodes(s) for s in ["left", "right", "top", "bottom"]])
    )
    mesh, bcs = per_node_displacements(mesh, boundary, field)
    model = api.Model(
        analysis=api.Analysis.AXISYMMETRIC if axisymmetric else api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"m": api.MaterialSpec.elastic("m", 1e4, 0.3)},
        region_material={1: "m"},
        displacements=bcs,
        initial=api.InitialStress("none"),
        stages=[api.Stage("patch")],
        settings=api.SolverSettings(gauss_order=order),
    )
    result = api.run(model)
    np.testing.assert_allclose(
        result.last.u, np.array([field(*x) for x in mesh.coords]), rtol=1e-10, atol=1e-13
    )
    exact = isotropic_D(1e4, 0.3) @ eps
    for sig in result.last.sig.values():
        np.testing.assert_allclose(sig, np.broadcast_to(exact, sig.shape), rtol=1e-10, atol=1e-10)
    np.testing.assert_allclose(api.nodal_stress(result), np.tile(exact, (mesh.nn, 1)), atol=1e-9)


@pytest.mark.parametrize("etype", [api.ElemType.T3, api.ElemType.T6])
@pytest.mark.parametrize("order", ["default", "high"])
def test_mixed_traction_patch(etype, order):
    mesh = recombine_mesh(rectangle(2, 1, 6, 4, etype), where=lambda x: x[:, 0] < 1)
    mesh.node_sets["origin"] = np.array([0])
    mesh.node_sets["corner"] = np.array([np.argmin(np.linalg.norm(mesh.coords - [2, 0], axis=1))])
    sx, sy, txy = 30.0, -50.0, 12.0
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"m": api.MaterialSpec.elastic("m", 1e4, 0.3)},
        region_material={1: "m"},
        fixities=(api.Fixity("origin", True, True), api.Fixity("corner", False, True)),
        initial=api.InitialStress("none"),
        settings=api.SolverSettings(gauss_order=order),
        stages=[
            api.Stage(
                "traction",
                loads=(
                    api.EdgeLoad("right", -sx, txy),
                    api.EdgeLoad("left", -sx, txy),
                    api.EdgeLoad("top", -sy, -txy),
                    api.EdgeLoad("bottom", -sy, -txy),
                ),
            )
        ],
    )
    r = api.run(model)
    exact = np.array([sx, sy, 0.3 * (sx + sy), txy])
    for sig in r.last.sig.values():
        np.testing.assert_allclose(sig, np.broadcast_to(exact, sig.shape), atol=1e-9)
    np.testing.assert_allclose(r.last.reactions.sum(axis=0), 0, atol=1e-9)


@pytest.mark.parametrize("etype", [api.ElemType.T3, api.ElemType.T6])
def test_mixed_plastic_driver_excavation_and_roundtrip(etype, tmp_path):
    source = rectangle(2, 1, 4, 2, etype)
    b = source.blocks[0]
    region = np.where(source.coords[b.conn[:, :3], 0].mean(axis=1) < 1, 1, 2)
    source = api.Mesh(
        source.coords,
        (api.ElementBlock(b.etype, b.conn, region, b.tag),),
        source.node_sets,
        source.edge_sets,
    )
    mesh = recombine_mesh(source, where=lambda x: x[:, 0] < 1)
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"m": api.MaterialSpec.mohr_coulomb("m", 1e4, 0.3, 1000, 0, gamma=18)},
        region_material={1: "m", 2: "m"},
        fixities=(api.Fixity("bottom", True, True),),
        stages=[
            api.Stage("left", active_regions={1}),
            api.Stage("right", active_regions={2}),
            api.Stage("fill"),
        ],
        settings=api.SolverSettings(gauss_order="high"),
    )
    r = api.run(model)
    loaded = api.load_project(api.save_project(model, tmp_path / "mixed.ssproj", r)).results
    for a, b in zip(r.stages, loaded.stages):
        np.testing.assert_array_equal(a.u, b.u)
        for tag in a.sig:
            np.testing.assert_array_equal(a.sig[tag], b.sig[tag])
    api.export_vtu(loaded, tmp_path / "mixed.vtu")
    assert set(b.etype for b in loaded.model.mesh.blocks) == set(b.etype for b in mesh.blocks)


@pytest.mark.parametrize("etype", [api.ElemType.T3, api.ElemType.T6])
def test_mixed_plastic_compression_matches_tresca_closed_form(etype):
    mesh = recombine_mesh(rectangle(2, 1, 4, 3, etype), where=lambda x: x[:, 0] < 1)
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"m": api.MaterialSpec.mohr_coulomb("m", 2e4, 0.3, 10, 0)},
        region_material={1: "m"},
        initial=api.InitialStress("none"),
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        stages=[api.Stage("compress", displacements=(api.Displacement("top", uy=-0.01),))],
        settings=api.SolverSettings(gauss_order="high", tol_force=1e-6, tol_energy=1e-8),
    )
    result = api.run(model)
    # Isochoric Tresca flow preserves mean stress and caps principal difference at 2c.
    mean = 2e4 / (3 * (1 - 2 * 0.3)) * (-0.01)
    exact = np.array([mean + 20 / 3, mean - 40 / 3, mean + 20 / 3, 0])
    for tag, sig in result.last.sig.items():
        np.testing.assert_allclose(sig, np.broadcast_to(exact, sig.shape), atol=1e-6)
        assert np.all(result.last.plastic[tag] > 0)
    assert result.last.reactions[mesh.nodes("top"), 1].sum() == pytest.approx(
        2 * exact[1], rel=1e-7
    )


@pytest.mark.parametrize("etype", [api.ElemType.T3, api.ElemType.T6])
def test_mixed_two_sided_liner_and_results(etype, tmp_path):
    from slipsurface.fe2d.mesh.structures import add_beams, insert_interface

    source = rectangle(2, 1, 4, 2, etype)
    ids = np.flatnonzero(abs(source.coords[:, 0] - 1) < 1e-12)
    ids = ids[np.argsort(source.coords[ids, 1])]
    source.edge_sets["wall"] = (
        np.column_stack([ids[:-1], ids[1:]])
        if etype == api.ElemType.T3
        else np.column_stack([ids[:-2:2], ids[2::2], ids[1::2]])
    )
    mesh = recombine_mesh(source, where=lambda x: x[:, 0] < 1.5)
    mesh = add_beams(mesh, "wall", "liner")
    mesh = insert_interface(mesh, "wall", "left_joint", "left")
    mesh = insert_interface(mesh, "wall", "right_joint", "right")
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"m": api.MaterialSpec.elastic("m", 1e4, 0.3)},
        region_material={1: "m"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        initial=api.InitialStress("none"),
        liners={"liner": api.LinerSpec("liner", 1e6, 0.2, 0.1, 0.001, 0.08)},
        interfaces={
            tag: api.InterfaceSpec(tag, 1e6, 1e6, c=1e6, sig_t=1e6)
            for tag in ["left_joint", "right_joint"]
        },
        settings=api.SolverSettings(gauss_order="high"),
        stages=[
            api.Stage(
                "load",
                active_structures={"liner", "left_joint", "right_joint"},
                loads=(api.EdgeLoad("top", 10),),
            )
        ],
    )
    result = api.run(model)
    assert np.isfinite(result.last.beams["liner"]).all()
    assert result.last.reactions[:, 1].sum() == pytest.approx(20, rel=1e-8)
    loaded = api.load_results(api.save_results(result, tmp_path / "mixed-structures.h5"))
    np.testing.assert_array_equal(result.last.beams["liner"], loaded.last.beams["liner"])
    api.export_vtu(loaded, tmp_path / "mixed-structures.vtu")


@pytest.mark.parametrize("etype", [api.ElemType.T3, api.ElemType.T6])
def test_mixed_hydrostatic_pressure_and_reactions(etype):
    from slipsurface.fe2d.core.units import GAMMA_W

    mesh = recombine_mesh(rectangle(2, 2, 4, 8, etype, origin=(0, -2)), where=lambda x: x[:, 0] < 1)
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"m": api.MaterialSpec.elastic("m", 2e4, 0.3, gamma=17, gamma_sat=20)},
        region_material={1: "m"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        initial=api.InitialStress("gravity", water=api.WaterCondition.piezo([[0, 0]])),
        settings=api.SolverSettings(gauss_order="high"),
    )
    result = api.run(model)
    for tag, geom in result.geom.items():
        depth = -geom.xg[..., 1]
        np.testing.assert_allclose(result.initial.pore[tag], GAMMA_W * depth, atol=1e-10)
        if etype == api.ElemType.T6:
            np.testing.assert_allclose(
                result.initial.sig[tag][..., 1], -(20 - GAMMA_W) * depth, atol=1e-8
            )
    assert result.initial.reactions[mesh.nodes("bottom"), 1].sum() == pytest.approx(80, rel=1e-10)

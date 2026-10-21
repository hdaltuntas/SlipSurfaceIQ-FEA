"""E1 — patch tests (T3, T6, Q4 with B-bar, Q8): constant strain must be reproduced
exactly (error < 1e-10) on distorted meshes."""

from __future__ import annotations

import numpy as np
import pytest
from conftest import distort, per_node_displacements

from slipsurface.fe2d import api
from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.fem.materials import isotropic_D
from slipsurface.fe2d.mesh import rectangle

E, NU = 1.0e4, 0.3
A = np.array([[1.0e-3, 2.0e-4], [-5.0e-4, -2.0e-3]])  # du_i/dx_j
U0 = np.array([1.0e-3, -2.0e-3])


def linear_field(x, y):
    return U0 + A @ np.array([x, y])


def _model(mesh, analysis, bcs=(), fix=(), loads=()):
    return api.Model(
        analysis=analysis,
        mesh=mesh,
        materials={"m": api.MaterialSpec.elastic("m", E, NU)},
        region_material={1: "m"},
        fixities=fix,
        displacements=bcs,
        initial=api.InitialStress("none"),
        stages=[api.Stage("patch", loads=loads)],
    )


ALL = [ElemType.T3, ElemType.T6, ElemType.Q4, ElemType.Q8]


@pytest.mark.parametrize("etype", ALL)
@pytest.mark.parametrize("seed", [0, 1])
def test_displacement_patch_plane_strain(etype, seed):
    mesh = distort(rectangle(2.0, 1.0, 4, 3, etype, pattern="alternate"), 0.12, seed)
    boundary = np.unique(
        np.concatenate([mesh.nodes(s) for s in ("left", "right", "top", "bottom")])
    )
    mesh, bcs = per_node_displacements(mesh, boundary, linear_field)
    res = api.run(_model(mesh, api.Analysis.PLANE_STRAIN, bcs))
    st = res.last

    exact_u = np.array([linear_field(*p) for p in mesh.coords])
    assert np.max(np.abs(st.u - exact_u)) < 1e-10 * np.max(np.abs(exact_u))

    eps = np.array([A[0, 0], A[1, 1], 0.0, A[0, 1] + A[1, 0]])
    sig_exact = isotropic_D(E, NU) @ eps
    sig = st.sig["soil"].reshape(-1, 4)
    assert np.max(np.abs(sig - sig_exact)) < 1e-10 * np.max(np.abs(sig_exact))


@pytest.mark.parametrize("etype", ALL)
def test_traction_patch_plane_strain(etype):
    """Constant stress via boundary tractions with only rigid-body constraints."""
    sx, sy, txy = 30.0, -50.0, 12.0
    mesh = distort(rectangle(2.0, 1.0, 4, 3, etype), 0.1, seed=3)
    # node sets for minimal constraints
    ns = dict(mesh.node_sets)
    ns["origin"] = np.array([int(np.argmin(np.hypot(*mesh.coords.T)))])
    ns["corner_x"] = np.array(
        [int(np.argmin(np.hypot(mesh.coords[:, 0] - 2.0, mesh.coords[:, 1])))]
    )
    mesh = api.Mesh(mesh.coords, mesh.blocks, ns, mesh.edge_sets)
    # outward normals: right (+x), left (-x), top (+y), bottom (-y); t = sigma . n
    # EdgeLoad: t = -qn n + qt s, s = n rotated +90deg
    loads = (
        api.EdgeLoad("right", qn=-sx, qt=txy),  # n=(1,0), s=(0,1): t=(sx, txy)
        api.EdgeLoad("left", qn=-sx, qt=txy),  # n=(-1,0), s=(0,-1): t=(-sx,-txy)
        api.EdgeLoad("top", qn=-sy, qt=-txy),  # n=(0,1), s=(-1,0): t=(txy, sy)
        api.EdgeLoad("bottom", qn=-sy, qt=-txy),  # n=(0,-1), s=(1,0): t=(-txy,-sy)
    )
    fix = (api.Fixity("origin", True, True), api.Fixity("corner_x", False, True))
    res = api.run(_model(mesh, api.Analysis.PLANE_STRAIN, fix=fix, loads=loads))
    sig = res.last.sig["soil"].reshape(-1, 4)
    szz = NU * (sx + sy)
    exact = np.array([sx, sy, szz, txy])
    assert np.max(np.abs(sig - exact)) < 1e-9 * np.max(np.abs(exact))


@pytest.mark.parametrize("etype", ALL)
def test_displacement_patch_axisymmetric(etype):
    """u_r = c r, u_z = d z gives constant strain [c, d, c, 0] in axisymmetry."""
    c, d = 2.0e-4, -1.0e-3
    mesh = distort(rectangle(2.0, 1.0, 4, 3, etype, origin=(1.0, 0.0)), 0.1, seed=5)
    boundary = np.unique(
        np.concatenate([mesh.nodes(s) for s in ("left", "right", "top", "bottom")])
    )
    mesh, bcs = per_node_displacements(mesh, boundary, lambda r, z: (c * r, d * z))
    res = api.run(_model(mesh, api.Analysis.AXISYMMETRIC, bcs))
    sig_exact = isotropic_D(E, NU) @ np.array([c, d, c, 0.0])
    sig = res.last.sig["soil"].reshape(-1, 4)
    assert np.max(np.abs(sig - sig_exact)) < 1e-10 * np.max(np.abs(sig_exact))
    ur = res.last.u[:, 0]
    assert np.max(np.abs(ur - c * mesh.coords[:, 0])) < 1e-10 * c * 3.0


@pytest.mark.parametrize("etype", [ElemType.T3, ElemType.T6])
def test_displacement_patch_unstructured(etype):
    """Constant strain on a Delaunay/Ruppert mesh with an embedded line and a hole."""
    from slipsurface.fe2d.mesh import Domain, circle, unstructured_mesh

    d = Domain().add_polygon([(0, 0), (3, 0), (3, 2), (0, 2)], name="outer")
    d.add_polygon(circle(1.2, 1.0, 0.4, 16), hole=True, name="hole")
    d.add_line([(2.2, 0.3), (2.7, 1.7)], name="line")
    mesh = unstructured_mesh(d, etype=etype, h=0.35)
    boundary = np.unique(np.concatenate([mesh.nodes("outer"), mesh.nodes("hole")]))
    mesh, bcs = per_node_displacements(mesh, boundary, linear_field)
    st = api.run(_model(mesh, api.Analysis.PLANE_STRAIN, bcs)).last
    exact_u = np.array([linear_field(*p) for p in mesh.coords])
    assert np.max(np.abs(st.u - exact_u)) < 1e-10 * np.max(np.abs(exact_u))
    eps = np.array([A[0, 0], A[1, 1], 0.0, A[0, 1] + A[1, 0]])
    sig_exact = isotropic_D(E, NU) @ eps
    sig = st.sig["soil"].reshape(-1, 4)
    assert np.max(np.abs(sig - sig_exact)) < 1e-10 * np.max(np.abs(sig_exact))

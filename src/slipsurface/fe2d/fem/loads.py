"""External load vectors: self-weight, edge tractions, point loads, initial K0 field."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray

from ..core.enums import Analysis
from ..core.errors import MeshError
from ..model.boundary import EdgeLoad, PointLoad
from ..model.mesh import Mesh
from .elements.base import GeomCache
from .elements.quadrature import gauss_legendre

TractionFn = Callable[[NDArray[np.float64], NDArray[np.float64]], NDArray[np.float64]]
"""``traction(x (npt,2), n_out (npt,2)) -> t (npt,2)`` in global axes [kPa]."""


# ----------------------------------------------------------------------- self-weight
def gravity_element_forces(geom: GeomCache, gamma: NDArray[np.float64]) -> NDArray[np.float64]:
    """Consistent nodal forces of body force b = (0, -gamma) per element: (ne, 2*nen)."""
    ne = geom.ne
    nen = geom.N.shape[1]
    fe = np.zeros((ne, 2 * nen))
    fe[:, 1::2] = -gamma[:, None] * (geom.wdet @ geom.N)
    return fe


# ---------------------------------------------------------------------- edge tractions
def _edge_shape(npe: int, xi: NDArray[np.float64]) -> tuple[NDArray, NDArray]:
    if npe == 2:
        N = np.column_stack([(1 - xi) / 2, (1 + xi) / 2])
        dN = np.column_stack([-0.5 * np.ones_like(xi), 0.5 * np.ones_like(xi)])
    elif npe == 3:  # [end_a, end_b, mid]
        N = np.column_stack([xi * (xi - 1) / 2, xi * (xi + 1) / 2, 1 - xi**2])
        dN = np.column_stack([xi - 0.5, xi + 0.5, -2 * xi])
    else:
        raise MeshError(f"edges with {npe} nodes are not supported")
    return N, dN


def _interior_points(mesh: Mesh, edges: NDArray[np.int64]) -> NDArray[np.float64]:
    """Centroid of the continuum element adjacent to each edge (to orient normals)."""
    nn = mesh.nn
    keys, cents = [], []
    for b in mesh.continuum_blocks():
        nc = 3 if b.etype.name.startswith("T") else 4
        corners = b.conn[:, :nc]
        cen = mesh.coords[corners].mean(axis=1)
        for i in range(nc):
            a, c = corners[:, i], corners[:, (i + 1) % nc]
            keys.append(np.minimum(a, c) * nn + np.maximum(a, c))
            cents.append(cen)
    k = np.concatenate(keys)
    cc = np.concatenate(cents)
    order = np.argsort(k)
    k, cc = k[order], cc[order]
    q = np.minimum(edges[:, 0], edges[:, 1]) * nn + np.maximum(edges[:, 0], edges[:, 1])
    pos = np.searchsorted(k, q)
    pos = np.clip(pos, 0, k.size - 1)
    if np.any(k[pos] != q):
        raise MeshError("edge set contains edges that do not belong to any element")
    return cc[pos]


def edge_traction_forces(
    mesh: Mesh,
    edges: NDArray[np.int64],
    traction: TractionFn,
    analysis: Analysis,
    ngauss: int = 4,
) -> tuple[NDArray[np.int64], NDArray[np.float64]]:
    """Consistent nodal forces of a traction field on ``edges``.

    Returns ``(nodes (n_edge, npe), forces (n_edge, npe, 2))``.
    """
    edges = np.atleast_2d(edges)
    npe = edges.shape[1]
    xi, w = gauss_legendre(ngauss)
    N, dN = _edge_shape(npe, xi)  # (g, npe)
    X = mesh.coords[edges]  # (e, npe, 2)
    xg = np.einsum("gn,enj->egj", N, X)
    T = np.einsum("gn,enj->egj", dN, X)  # dx/dxi
    jac = np.linalg.norm(T, axis=2)  # (e, g)
    n = np.stack([T[..., 1], -T[..., 0]], axis=2) / jac[..., None]
    # orient outward: away from the adjacent element centroid
    mid = X[:, :2].mean(axis=1)
    inner = _interior_points(mesh, edges)
    s = np.sign(np.einsum("ej,ej->e", np.mean(n, axis=1), mid - inner))
    s[s == 0] = 1.0
    n *= s[:, None, None]
    t = traction(xg.reshape(-1, 2), n.reshape(-1, 2)).reshape(xg.shape)
    wt = jac * w[None, :]
    if analysis is Analysis.AXISYMMETRIC:
        wt = wt * xg[..., 0]
    f = np.einsum("gn,egj,eg->enj", N, t, wt)
    return edges, f


def edge_load_traction(load: EdgeLoad) -> TractionFn:
    qn, qt = load.qn, load.qt

    def fn(x: NDArray[np.float64], n: NDArray[np.float64]) -> NDArray[np.float64]:
        s = np.column_stack([-n[:, 1], n[:, 0]])
        return -qn * n + qt * s

    return fn


def assemble_nodal_loads(
    mesh: Mesh,
    node_dofs: NDArray[np.int64],
    ndof: int,
    loads: tuple[EdgeLoad | PointLoad, ...],
    analysis: Analysis,
    extra_tractions: tuple[tuple[str, TractionFn], ...] = (),
) -> NDArray[np.float64]:
    f = np.zeros(ndof)

    def add(nodes: NDArray[np.int64], fn: NDArray[np.float64]) -> None:
        for c in (0, 1):
            d = node_dofs[nodes.ravel(), c]
            if np.any(d < 0):
                raise MeshError("load applied to a node without degrees of freedom (inactive?)")
            np.add.at(f, d, fn[..., c].ravel())

    for ld in loads:
        if isinstance(ld, EdgeLoad):
            nodes, fn = edge_traction_forces(
                mesh, mesh.edges(ld.edge_set), edge_load_traction(ld), analysis
            )
            add(nodes, fn)
        elif isinstance(ld, PointLoad):
            add(np.array([ld.node]), np.array([[[ld.fx, ld.fy]]]))
    for name, fn_t in extra_tractions:
        nodes, fn = edge_traction_forces(mesh, mesh.edges(name), fn_t, analysis)
        add(nodes, fn)
    return f


# --------------------------------------------------------------------- K0 stress field
def unit_weight_profile(
    yrange_list: list[NDArray[np.float64]],
    gamma_list: list[NDArray[np.float64]],
    surface_y: float,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Piecewise-constant gamma(z) from element vertical extents, integrated exactly.

    ``yrange_list[b]`` is (ne, 2) [ymin, ymax] per element. Breakpoints are all element
    extents; each interval takes the mean unit weight of the elements spanning it (exact
    for horizontal layering). Returns breakpoints ``z`` (descending, starting at
    ``surface_y``) and ``sv(z) = -integral_z^surface gamma`` at those points.
    """
    yr = np.vstack(yrange_list)
    g = np.concatenate(gamma_list)
    z = np.unique(np.concatenate([yr.ravel(), [surface_y]]))  # ascending
    z = z[z <= surface_y + 1e-12 * max(1.0, abs(surface_y))]
    lo = np.searchsorted(z, yr[:, 0])
    hi = np.searchsorted(z, yr[:, 1])  # element spans intervals lo .. hi-1
    nint = z.size - 1
    acc = np.zeros(nint + 1)
    cnt = np.zeros(nint + 1)
    hi = np.minimum(hi, nint)
    np.add.at(acc, lo, g)
    np.add.at(acc, hi, -g)
    np.add.at(cnt, lo, 1.0)
    np.add.at(cnt, hi, -1.0)
    acc, cnt = np.cumsum(acc)[:nint], np.cumsum(cnt)[:nint]
    gam = np.divide(acc, cnt, out=np.zeros(nint), where=cnt > 0)
    dz = np.diff(z)
    # integrate from the top down
    sv_desc = -np.concatenate([[0.0], np.cumsum((gam * dz)[::-1])])
    return z[::-1], sv_desc


def k0_stress_field(
    xg_list: list[NDArray[np.float64]],
    yrange_list: list[NDArray[np.float64]],
    gamma_list: list[NDArray[np.float64]],
    k0_list: list[NDArray[np.float64]],
    surface_y: float,
) -> list[NDArray[np.float64]]:
    """Geostatic stresses for horizontally layered ground (tension positive).

    ``sv(y) = -integral_y^surface gamma(z) dz``; ``sh = szz = K0 sv`` with the K0 of the
    element containing the Gauss point. Exact when material boundaries are horizontal;
    for sloping ground use the ``gravity`` mode instead (the solver warns).
    """
    z_desc, sv_desc = unit_weight_profile(yrange_list, gamma_list, surface_y)
    out = []
    for xg, k0 in zip(xg_list, k0_list):
        y = xg[..., 1]
        sv = np.interp(-y, -z_desc, sv_desc)
        sv = np.where(y > surface_y, 0.0, sv)
        sig = np.zeros((*y.shape, 4))
        sig[..., 1] = sv
        sig[..., 0] = k0[:, None] * sv
        sig[..., 2] = k0[:, None] * sv
        out.append(sig)
    return out

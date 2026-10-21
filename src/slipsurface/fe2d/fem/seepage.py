"""Steady-state saturated / unsaturated seepage (L3).

Unknown: total hydraulic head ``h`` at every node of the active continuum mesh (same mesh
and element order as the mechanics). Darcy's law ``v = -k_r(psi) K_sat grad h`` with
pressure head ``psi = h - y``; continuity ``div v = 0`` gives

    K_h h = f,     K_h = sum_e int grad N^T (k_r K_sat) grad N dOmega

* **Unsaturated zone**: van Genuchten-Mualem relative conductivity
  ``k_r = Se^(1/2) [1 - (1 - Se^(1/m))^m]^2``, ``Se = [1 + (alpha |psi|)^n]^-m``,
  ``m = 1 - 1/n`` for ``psi < 0`` (``k_r = 1`` below the phreatic surface), with a floor
  ``k_r,min``. The free surface is the ``p = 0`` iso-line; the mesh is not deformed.
* **Picard iteration** on ``k_r`` with 0.5 damping.
* **Boundary conditions**: prescribed head on node sets, prescribed normal inflow on edge
  sets (``q > 0`` into the domain, m/s), impermeable elsewhere (natural BC). Seepage
  faces: nodes start with ``p = 0`` (``h = y``); a node through which water would enter
  is released, a released node with ``p > 0`` is constrained again (iterative switching).
* **Discharge**: the nodal "reactions" ``K_h h - f`` at constrained nodes are the inflow
  through them (consistent with the discrete solution, m3/s per m, per radian in
  axisymmetry).

Interface elements are impermeable (a sheet pile is modelled by duplicating the nodes of
its line with :func:`~slipsurface.fe2d.mesh.structures.insert_interface`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
from numpy.typing import NDArray

from ..core.enums import Analysis, ElemType
from ..core.errors import ModelError, SolverError
from ..core.log import get_logger
from ..core.units import GAMMA_W
from ..model.mesh import Mesh
from .elements import kernel
from .elements.base import IsoElement
from .elements.quadrature import gauss_legendre
from .loads import _edge_shape

log = get_logger("seepage")
_CONT = (ElemType.T3, ElemType.T6, ElemType.Q4, ElemType.Q8)


@dataclass(frozen=True)
class VanGenuchten:
    """Hydraulic functions of one material: alpha [1/m], n [-], k_r floor."""

    alpha: float = 1.0
    n: float = 2.0
    kr_min: float = 1e-4

    def __post_init__(self) -> None:
        if self.alpha <= 0 or self.n <= 1 or not 0 < self.kr_min <= 1:
            raise ModelError("van Genuchten: need alpha > 0, n > 1, 0 < kr_min <= 1")

    def kr(self, psi: NDArray[np.float64]) -> NDArray[np.float64]:
        return relative_conductivity(psi, self.alpha, self.n, self.kr_min)


def relative_conductivity(
    psi: NDArray[np.float64], alpha: NDArray | float, n: NDArray | float, kr_min: NDArray | float
) -> NDArray[np.float64]:
    """van Genuchten-Mualem k_r(psi) (vectorised; parameters broadcast with ``psi``)."""
    psi = np.asarray(psi, dtype=float)
    alpha, n, kr_min = (np.broadcast_to(np.asarray(v, dtype=float), psi.shape) for v in
                        (alpha, n, kr_min))  # fmt: skip
    m = 1.0 - 1.0 / n
    neg = psi < 0
    Se = np.ones_like(psi)
    Se[neg] = (1.0 + (alpha[neg] * -psi[neg]) ** n[neg]) ** (-m[neg])
    kr = np.ones_like(psi)
    mm = m[neg]
    kr[neg] = np.sqrt(Se[neg]) * (1.0 - (1.0 - Se[neg] ** (1.0 / mm)) ** mm) ** 2
    return np.maximum(kr, kr_min)


@dataclass
class SeepageBlock:
    """Hydraulic data of one continuum block (active elements only)."""

    tag: str
    conn: NDArray[np.int64]  # (ne, nen)
    etype: ElemType
    k: NDArray[np.float64]  # (ne, 2) kx, ky [m/s]
    vg: NDArray[np.float64]  # (ne, 3) alpha, n, kr_min


@dataclass
class SeepageResult:
    head: NDArray[np.float64]  # (nn,) total head [m] (NaN on inactive nodes)
    pressure: NDArray[np.float64]  # (nn,) pore pressure gamma_w (h - y) [kPa] (suction < 0)
    gp_head: dict[str, NDArray[np.float64]]  # tag -> (ne_active, ngp)
    gp_xy: dict[str, NDArray[np.float64]]  # tag -> (ne_active, ngp, 2)
    gp_kr: dict[str, NDArray[np.float64]]  # tag -> (ne_active, ngp)
    inflow: dict[str, float]  # head BC / seepage face name -> inflow [m3/s/m] (< 0: out)
    nodal_flux: NDArray[np.float64]  # (nn,) inflow at constrained nodes
    seepage_nodes: NDArray[np.int64]  # seepage-face nodes finally at p = 0
    iterations: int
    converged: bool
    velocity: dict[str, NDArray[np.float64]] = field(default_factory=dict)  # (ne, ngp, 2)

    def gp_pressure(self, tag: str) -> NDArray[np.float64]:
        """Pore pressure at the Gauss points (compression positive, suction < 0)."""
        return GAMMA_W * (self.gp_head[tag] - self.gp_xy[tag][..., 1])


def _gradients(etype: ElemType, coords: NDArray, conn: NDArray, analysis: Analysis):
    kern = kernel(etype)
    g = IsoElement.precompute(kern, coords, conn, analysis)  # plain (no B-bar) gradients
    dNx = g.B[:, :, 0, 0::2]  # (ne, ngp, nen)
    dNy = g.B[:, :, 1, 1::2]
    return dNx, dNy, g.wdet, g.N, g.xg


def solve_seepage(
    mesh: Mesh,
    blocks: list[SeepageBlock],
    head_bcs: list[tuple[str, NDArray[np.int64], NDArray[np.float64]]],
    flux_bcs: list[tuple[NDArray[np.int64], float]] = (),  # type: ignore[assignment]
    seepage_faces: list[tuple[str, NDArray[np.int64]]] = (),  # type: ignore[assignment]
    analysis: Analysis = Analysis.PLANE_STRAIN,
    tol: float = 1e-7,
    max_iter: int = 200,
    damping: float = 0.5,
) -> SeepageResult:
    """Solve steady seepage on ``blocks``.

    ``head_bcs``: ``(name, nodes, head)`` with ``head`` a scalar or per-node array.
    ``flux_bcs``: ``(edges, q)`` normal inflow [m/s] on edges ``(m, 2|3)``.
    ``seepage_faces``: ``(name, nodes)`` potential seepage nodes.
    """
    X = mesh.coords
    nn = mesh.nn
    used = np.zeros(nn, dtype=bool)
    for b in blocks:
        used[b.conn.ravel()] = True
    if not used.any():
        raise ModelError("seepage: no active element")
    dof = -np.ones(nn, dtype=np.int64)
    dof[used] = np.arange(int(used.sum()))
    ndof = int(used.sum())

    # ---- element geometry
    geo = []
    for b in blocks:
        dNx, dNy, wdet, N, xg = _gradients(b.etype, X, b.conn, analysis)
        geo.append((dNx, dNy, wdet, N, xg))
    # ---- sparse pattern (scalar dofs)
    rows, cols = [], []
    for b in blocks:
        ed = dof[b.conn]
        nen = ed.shape[1]
        rows.append(np.repeat(ed, nen, axis=1).ravel())
        cols.append(np.tile(ed, (1, nen)).ravel())
    r_all, c_all = np.concatenate(rows), np.concatenate(cols)
    key = r_all * ndof + c_all
    uk, inv = np.unique(key, return_inverse=True)
    inv = inv.ravel()
    Ki, Kj = uk // ndof, uk % ndof
    offs = np.cumsum([0] + [r.size for r in rows])

    def assemble(kr_list: list[NDArray[np.float64]]) -> sp.csr_matrix:
        data = np.zeros(uk.size)
        for i, (b, (dNx, dNy, wdet, _, _), kr) in enumerate(zip(blocks, geo, kr_list)):
            w = wdet * kr  # (ne, ngp)
            kx, ky = b.k[:, 0][:, None], b.k[:, 1][:, None]
            Ke = np.einsum("eg,egi,egj->eij", w * kx, dNx, dNx) + np.einsum(
                "eg,egi,egj->eij", w * ky, dNy, dNy
            )
            data += np.bincount(inv[offs[i] : offs[i + 1]], Ke.ravel(), minlength=uk.size)
        return sp.csr_matrix((data, (Ki, Kj)), shape=(ndof, ndof))

    # ---- flux BCs (constant normal inflow)
    f = np.zeros(ndof)
    for edges, q in flux_bcs:
        edges = np.atleast_2d(edges)
        if np.any(dof[edges] < 0):
            edges = edges[(dof[edges] >= 0).all(axis=1)]
        if edges.size == 0:
            continue
        xi, w = gauss_legendre(4)
        Ne, dNe = _edge_shape(edges.shape[1], xi)
        Xe = X[edges]
        T = np.einsum("gn,enj->egj", dNe, Xe)
        jac = np.linalg.norm(T, axis=2) * w[None, :]
        if analysis is Analysis.AXISYMMETRIC:
            jac = jac * np.einsum("gn,en->eg", Ne, Xe[..., 0])
        fe = q * np.einsum("gn,eg->en", Ne, jac)
        np.add.at(f, dof[edges].ravel(), fe.ravel())

    # ---- prescribed heads
    h_fix = np.full(nn, np.nan)
    owner: dict[int, str] = {}
    for name, nodes, val in head_bcs:
        nodes = np.asarray(nodes, dtype=np.int64)
        vals = np.broadcast_to(np.asarray(val, dtype=float), nodes.shape)
        m = used[nodes]
        h_fix[nodes[m]] = vals[m]
        for n_ in nodes[m].tolist():
            owner[n_] = name
    sf_nodes = np.unique(np.concatenate([np.asarray(n) for _, n in seepage_faces])) if (
        seepage_faces) else np.empty(0, np.int64)  # fmt: skip
    sf_nodes = sf_nodes[used[sf_nodes] & np.isnan(h_fix[sf_nodes])]
    sf_on = np.ones(sf_nodes.size, dtype=bool)  # start with p = 0 on every face node
    if not np.isfinite(h_fix).any() and sf_nodes.size == 0:
        raise ModelError("seepage needs at least one prescribed head or seepage face")

    kr_list = [np.ones(g[2].shape) for g in geo]
    h_nodal = np.zeros(nn)
    converged = False
    it = 0
    for it in range(1, max_iter + 1):
        K = assemble(kr_list)
        fixed = np.isfinite(h_fix)
        hv = h_fix.copy()
        if sf_nodes.size:
            fixed[sf_nodes[sf_on]] = True
            hv[sf_nodes[sf_on]] = X[sf_nodes[sf_on], 1]
        fd = dof[fixed & used]
        fv = hv[fixed & used]
        is_free = np.ones(ndof, dtype=bool)
        is_free[fd] = False
        fr = np.flatnonzero(is_free)
        h = np.zeros(ndof)
        h[fd] = fv
        if fr.size:
            Kff = K[fr][:, fr].tocsc()
            rhs = f[fr] - K[fr][:, fd] @ fv
            try:
                h[fr] = spla.spsolve(Kff, rhs)
            except RuntimeError as exc:  # pragma: no cover
                raise SolverError("seepage system is singular (isolated region?)") from exc
        h_new = np.full(nn, np.nan)
        h_new[used] = h[dof[used]]
        r = K @ h - f  # inflow at constrained dofs
        # ---- seepage face switching
        changed = False
        if sf_nodes.size:
            d_sf = dof[sf_nodes]
            p_sf = h[d_sf] - X[sf_nodes, 1]
            scale = max(np.abs(r).max(), 1e-300)
            inflow = sf_on & (r[d_sf] > 1e-9 * scale)
            reenter = ~sf_on & (p_sf > 1e-9 * max(np.ptp(X[:, 1]), 1.0))
            if inflow.any() or reenter.any():
                sf_on = (sf_on & ~inflow) | reenter
                changed = True
        # ---- relative conductivity update (Picard, damped)
        kr_new = []
        dh = np.nanmax(np.abs(h_new - h_nodal)) if it > 1 else np.inf
        for b, (_, _, _, N, xg), kr_old in zip(blocks, geo, kr_list):
            hg = np.einsum("gn,en->eg", N, h_new[b.conn])
            psi = hg - xg[..., 1]
            target = relative_conductivity(psi, b.vg[:, 0][:, None], b.vg[:, 1][:, None],
                                           b.vg[:, 2][:, None])  # fmt: skip
            kr_new.append((1 - damping) * kr_old + damping * target)
        dkr = max(np.abs(a - b_).max() for a, b_ in zip(kr_new, kr_list))
        h_nodal = h_new
        kr_list = kr_new
        href = max(np.nanmax(np.abs(h_new)), 1.0)
        if not changed and dh < tol * href and dkr < 1e3 * tol:
            converged = True
            break
    if not converged:
        log.warning("seepage: Picard did not converge in %d iterations", max_iter)

    # final solve with the converged conductivities is h_nodal / r of the last iteration
    nodal_flux = np.zeros(nn)
    nodal_flux[used] = r[dof[used]]
    nodal_flux[~(np.isfinite(h_fix) | np.isin(np.arange(nn), sf_nodes[sf_on]))] = 0.0
    inflow_by: dict[str, float] = {}
    for name, nodes, _ in head_bcs:
        nodes = np.asarray(nodes, dtype=np.int64)
        own = [n_ for n_ in np.unique(nodes).tolist() if owner.get(n_) == name]
        inflow_by[name] = float(nodal_flux[own].sum())
    for name, nodes in seepage_faces:
        nodes = np.intersect1d(np.asarray(nodes), sf_nodes[sf_on])
        inflow_by[name] = float(nodal_flux[nodes].sum())

    gp_head, gp_xy, gp_kr, vel = {}, {}, {}, {}
    for b, (dNx, dNy, _, N, xg), kr in zip(blocks, geo, kr_list):
        he = h_nodal[b.conn]
        gp_head[b.tag] = np.einsum("gn,en->eg", N, he)
        gp_xy[b.tag] = xg
        gp_kr[b.tag] = kr
        gx = np.einsum("egn,en->eg", dNx, he)
        gy = np.einsum("egn,en->eg", dNy, he)
        vel[b.tag] = -np.stack([b.k[:, 0][:, None] * kr * gx, b.k[:, 1][:, None] * kr * gy], -1)
    pressure = GAMMA_W * (h_nodal - X[:, 1])
    return SeepageResult(
        head=h_nodal,
        pressure=pressure,
        gp_head=gp_head,
        gp_xy=gp_xy,
        gp_kr=gp_kr,
        inflow=inflow_by,
        nodal_flux=nodal_flux,
        seepage_nodes=sf_nodes[sf_on],
        iterations=it,
        converged=converged,
        velocity=vel,
    )

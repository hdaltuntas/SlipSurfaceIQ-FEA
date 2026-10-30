"""Pore pressure on the active mesh. Not the Newton iteration.

Effective stress stays in the element residual. Water enters as an external force
(``int B^T m p``, joint pressure, pressure on the exposed boundary) and, for undrained
A/B, as the volumetric stiffness ``Kw/n``.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from ..core.enums import ElemType
from ..core.errors import ModelError
from ..core.units import GAMMA_W
from ..model.boundary import WaterCondition
from ..model.materials import MaterialSpec
from .assembly import internal_force
from .loads import pressure_edge_forces

_M = np.array([1.0, 1.0, 1.0, 0.0])
WT_TOL = 1e-9  # [m] a Gauss point on the water table (round-off) counts as dry


def water_stiffness(spec: MaterialSpec, De: NDArray[np.float64]) -> float:
    """Kw/n of an undrained A/B material: ``params['Kw_n']`` or 100 K'."""
    if "Kw_n" in spec.params:
        return float(spec.params["Kw_n"])
    K = (De[0, 0] + 2.0 * De[0, 1]) / 3.0
    return 100.0 * float(K)


def continuum_pore(xg, gamma, gamma_sat, total, water: WaterCondition, seep, tag: str):
    """``(p, gamma_gp)`` at the Gauss points of one active continuum block.

    ``p`` is compression-positive pore pressure [kPa]. Unit weight switches to saturated
    below the water table. Undrained-C elements (``total``) carry no pore pressure.
    """
    if seep is not None:
        p = (
            np.maximum(seep.gp_pressure(tag), 0.0)
            if tag in seep.gp_head
            else np.zeros(xg.shape[:2])
        )
        below = p > GAMMA_W * WT_TOL
    else:
        h = water.head(xg[..., 0])
        p = GAMMA_W * np.maximum(h - xg[..., 1], 0.0)
        below = h - xg[..., 1] > WT_TOL
    gam = np.where(below, gamma_sat[:, None], gamma[:, None])
    if total is not None and total.any():
        p = np.where(total[:, None], 0.0, p)
    return p, gam


def joint_pressure(xi, face_nodes, p_nodal, water: WaterCondition):
    """Interface joint water pressure [kPa], compression positive, suction discarded."""
    if p_nodal is not None:
        return p_nodal[face_nodes]
    return GAMMA_W * np.maximum(water.head(xi[..., 0]) - xi[..., 1], 0.0)


def exposed_edges(coords, blocks, sysm, iface_face_keys):
    """Boundary edges of the active continuum, excluding interface faces."""
    keys, rows, cents = [], [], []
    nn = coords.shape[0]
    for c, b in zip(sysm.cont, blocks):
        if c.ids.size == 0:
            continue
        conn = b.conn[c.ids]
        nc = 4 if b.etype in (ElemType.Q4, ElemType.Q8) else 3
        quad = b.etype in (ElemType.T6, ElemType.Q8)
        cen = coords[conn[:, :nc]].mean(axis=1)
        for i in range(nc):
            a, e = conn[:, i], conn[:, (i + 1) % nc]
            r = np.column_stack([a, e, conn[:, nc + i]]) if quad else np.column_stack([a, e])
            keys.append(np.minimum(a, e) * nn + np.maximum(a, e))
            rows.append(r)
            cents.append(cen)
    if not keys:
        return np.empty((0, 2), np.int64), np.empty((0, 2))
    k = np.concatenate(keys)
    width = max(r.shape[1] for r in rows)
    if any(r.shape[1] != width for r in rows):
        raise ModelError("mixed linear/quadratic continuum blocks are not supported")
    R = np.vstack(rows)
    C = np.vstack(cents)
    _u, inv, cnt = np.unique(k, return_inverse=True, return_counts=True)
    once = cnt[inv.ravel()] == 1
    if iface_face_keys:
        fk = np.array([a * nn + b for a, b in iface_face_keys])
        once &= ~np.isin(k, fk)
    return R[once], C[once]


def water_forces(sysm, water: WaterCondition, coords, blocks, iface_face_keys, analysis):
    """External nodal force from pore pressure on the active system."""
    dm = sysm.dm
    nd = dm.ndof
    f = np.zeros(nd)
    # int B^T m p (moves to the external side in the effective-stress formulation)
    for c in sysm.cont:
        if c.ids.size and np.any(c.p > 0):
            fe = internal_force(c.geom, c.p[..., None] * _M)
            f += np.bincount(c.edofs.ravel(), fe.ravel(), minlength=nd)
    for s in sysm.struct:
        if s.p is not None and np.any(s.p > 0):
            f += np.bincount(
                s.edofs.ravel(), s.group.pore_force(s.ids, s.p).ravel(), minlength=nd
            )
    edges, inner = exposed_edges(coords, blocks, sysm, iface_face_keys)
    if edges.size:
        if sysm.p_nodal is not None:
            sel = (sysm.p_nodal[edges] > 0).any(axis=1)
        else:
            hmax = water.head(coords[edges[:, :2], 0]).max(axis=1)
            sel = hmax > coords[edges[:, :2], 1].min(axis=1)
        if np.any(sel):

            def pfun(x: NDArray[np.float64]) -> NDArray[np.float64]:
                return GAMMA_W * np.maximum(water.head(x[:, 0]) - x[:, 1], 0.0)

            pn = None if sysm.p_nodal is None else sysm.p_nodal[edges[sel]]
            fe = pressure_edge_forces(
                coords, edges[sel], inner[sel], pfun, analysis, p_nodal=pn
            )
            ed = dm.node_dofs[edges[sel]][:, :, :2]
            ok = ed >= 0
            fw = np.bincount(ed[ok], fe[ok], minlength=nd)
            # on prescribed DOFs the boundary water load only shifts the reaction;
            # leaving it out makes reported reactions total (effective + water)
            fw[dm.prescribed] = 0.0
            f += fw
    return f

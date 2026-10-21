"""Gauss point -> node stress recovery and derived stress fields (L4).

Phase 1 uses element-wise linear extrapolation to corner nodes followed by nodal
averaging (mid-side nodes take the mean of their two corners). SPR follows in Faz 2.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from ..core.enums import ElemType
from ..model.mesh import ElementBlock, Mesh


def _extrapolation(etype: ElemType, ngp: int) -> NDArray[np.float64]:
    """(ncorner, ngp) linear extrapolation matrix for the rules used by the solver."""
    if etype is ElemType.T3:
        return np.full((3, ngp), 1.0 / ngp)
    if etype is ElemType.T6:
        from ..fem.elements.quadrature import tri_rule
        from ..fem.elements.tri6 import Tri6

        return Tri6.corner_extrapolation(tri_rule(ngp))
    if etype in (ElemType.Q4, ElemType.Q8):
        from ..fem.elements.quad import quad_corner_extrapolation
        from ..fem.elements.quadrature import quad_rule

        return quad_corner_extrapolation(quad_rule(int(round(np.sqrt(ngp)))))
    raise NotImplementedError(etype.name)


def element_nodal_values(
    block: ElementBlock, gp_values: NDArray[np.float64]
) -> NDArray[np.float64]:
    """Per-element nodal values (ne, nen, ncomp) from Gauss values (ne, ngp, ncomp)."""
    E = _extrapolation(block.etype, gp_values.shape[1])
    corner = np.einsum("cg,egk->eck", E, gp_values)
    if block.etype is ElemType.T6:
        mids = 0.5 * (corner[:, [0, 1, 2]] + corner[:, [1, 2, 0]])
        return np.concatenate([corner, mids], axis=1)
    if block.etype is ElemType.Q8:
        mids = 0.5 * (corner[:, [0, 1, 2, 3]] + corner[:, [1, 2, 3, 0]])
        return np.concatenate([corner, mids], axis=1)
    return corner


def nodal_average(mesh: Mesh, gp_values: dict[str, NDArray[np.float64]]) -> NDArray[np.float64]:
    """Average extrapolated element values at shared nodes -> (nn, ncomp); NaN if unused."""
    ncomp = next(iter(gp_values.values())).shape[-1]
    acc = np.zeros((mesh.nn, ncomp))
    cnt = np.zeros(mesh.nn)
    for b in mesh.continuum_blocks():
        if b.tag not in gp_values:
            continue
        ev = element_nodal_values(b, gp_values[b.tag])
        for k in range(ncomp):
            acc[:, k] += np.bincount(b.conn.ravel(), ev[..., k].ravel(), minlength=mesh.nn)
        cnt += np.bincount(b.conn.ravel(), minlength=mesh.nn)
    out = np.full((mesh.nn, ncomp), np.nan)
    m = cnt > 0
    out[m] = acc[m] / cnt[m, None]
    return out


def principal_stresses(sig: NDArray[np.float64]) -> dict[str, NDArray[np.float64]]:
    """In-plane principal stresses (tension positive) plus the out-of-plane component.

    Returns ``s1 >= s3`` in-plane, ``s2`` sorted among all three, and the angle of s1
    from the x axis in degrees. Works on any leading shape (..., 4).
    """
    sxx, syy, szz, txy = (sig[..., i] for i in range(4))
    c = 0.5 * (sxx + syy)
    r = np.sqrt((0.5 * (sxx - syy)) ** 2 + txy**2)
    sa, sb = c + r, c - r
    allp = np.sort(np.stack([sa, sb, szz], axis=-1), axis=-1)[..., ::-1]
    theta = 0.5 * np.degrees(np.arctan2(2 * txy, sxx - syy))
    return {
        "s1": allp[..., 0],
        "s2": allp[..., 1],
        "s3": allp[..., 2],
        "s1_inplane": sa,
        "s3_inplane": sb,
        "angle_s1": theta,
        "mean": (sxx + syy + szz) / 3.0,
        "q": np.sqrt(0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2) + 3 * txy**2),
    }

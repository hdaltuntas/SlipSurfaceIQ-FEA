"""Gauss point -> node stress recovery and derived stress fields (L4).

Two methods: element-wise linear extrapolation to the corners followed by nodal
averaging (:func:`nodal_average`) and superconvergent patch recovery (:func:`spr`,
default for results/exports, extrapolation kept on the outer boundary).
"""

from __future__ import annotations

from dataclasses import replace

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


def nodal_average(
    mesh: Mesh,
    gp_values: dict[str, NDArray[np.float64]],
    *,
    active: dict[str, NDArray[np.bool_]] | None = None,
) -> NDArray[np.float64]:
    """Average extrapolated values; NaN on unused nodes.

    ``active`` excludes removed elements, including their retained history. Omitted
    masks retain the legacy all-active behavior; stored arrays are never modified.
    """
    ncomp = next(iter(gp_values.values())).shape[-1]
    mesh, gp_values, _ = _active_fields(mesh, gp_values, active)
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


# ------------------------------------------------------------------------------ SPR
def _basis(d: NDArray[np.float64], degree: int) -> NDArray[np.float64]:
    x, y = d[..., 0], d[..., 1]
    cols = [np.ones_like(x), x, y]
    if degree == 2:
        cols += [x * x, x * y, y * y]
    elif degree == 11:  # bilinear (Q4)
        cols += [x * y]
    return np.stack(cols, axis=-1)


_SPR_DEGREE = {ElemType.T3: 1, ElemType.Q4: 11, ElemType.T6: 2, ElemType.Q8: 2}


def boundary_nodes(mesh: Mesh) -> NDArray[np.int64]:
    """Nodes on the outer boundary of the continuum mesh (edges used by one element)."""
    keys, mids = [], []
    nn = mesh.nn
    for b in mesh.continuum_blocks():
        nc = 4 if b.etype in (ElemType.Q4, ElemType.Q8) else 3
        quad = b.etype in (ElemType.T6, ElemType.Q8)
        for i in range(nc):
            a, c = b.conn[:, i], b.conn[:, (i + 1) % nc]
            keys.append(np.minimum(a, c) * nn + np.maximum(a, c))
            mids.append(b.conn[:, nc + i] if quad else np.full(b.ne, -1))
    k = np.concatenate(keys)
    m = np.concatenate(mids)
    u, inv, cnt = np.unique(k, return_inverse=True, return_counts=True)
    once = cnt[inv.ravel()] == 1
    nodes = np.concatenate([k[once] // nn, k[once] % nn, m[once][m[once] >= 0]])
    return np.unique(nodes)


def spr(
    mesh: Mesh,
    gp_values: dict[str, NDArray[np.float64]],
    gp_coords: dict[str, NDArray[np.float64]],
    boundary: str = "extrapolate",
    *,
    active: dict[str, NDArray[np.bool_]] | None = None,
) -> NDArray[np.float64]:
    """Superconvergent patch recovery (Zienkiewicz & Zhu) -> nodal values (nn, ncomp).

    For every corner node a polynomial of the element's order (T3: linear, Q4: bilinear,
    T6/Q8: quadratic) is fitted by least squares to the Gauss-point values of the
    elements around it. Patches are built per material region, so stress jumps across
    region boundaries are not smeared; nodes on a boundary between regions take the mean
    of the per-region values. Mid-side nodes average the patch polynomials of their two
    end corners. Corners whose own patch is too small (typically on the boundary) use
    the polynomials of valid neighbouring corners; if none exists they fall back to the
    extrapolation average of :func:`nodal_average`.

    ``boundary="extrapolate"`` (default) keeps the extrapolation average on the outer
    mesh boundary, where patch recovery is known to be least accurate (on the Kirsch
    problem it is up to 2x worse there, while 2-3x better inside for T6/Q8);
    ``boundary="spr"`` uses the patch values everywhere.
    ``active`` restricts patches and boundary detection to the selected stage.
    """
    ncomp = next(iter(gp_values.values())).shape[-1]
    mesh, gp_values, gp_coords = _active_fields(mesh, gp_values, active, gp_coords)
    if not gp_values:
        return np.full((mesh.nn, ncomp), np.nan)
    nn = mesh.nn
    acc = np.zeros((nn, ncomp))
    cnt = np.zeros(nn)
    fallback = nodal_average(mesh, gp_values)
    for b in mesh.continuum_blocks():
        if b.tag not in gp_values:
            continue
        deg = _SPR_DEGREE[b.etype]
        nc = 4 if b.etype in (ElemType.Q4, ElemType.Q8) else 3
        V = gp_values[b.tag]  # (ne, ngp, k)
        XG = gp_coords[b.tag]  # (ne, ngp, 2)
        for reg in np.unique(b.region):
            e_ids = np.flatnonzero(b.region == reg)
            conn = b.conn[e_ids]
            corners = conn[:, :nc]
            v_ids, inv = np.unique(corners, return_inverse=True)
            inv = inv.reshape(corners.shape)  # local vertex index per (element, corner)
            nv = v_ids.size
            xv = mesh.coords[v_ids]
            xg, vals = XG[e_ids], V[e_ids]
            ngp = xg.shape[1]
            # patch scale: max vertex-GP distance in the patch
            d_all = xg[:, None, :, :] - xv[inv][:, :, None, :]  # (e, c, g, 2)
            hv = np.zeros(nv)
            np.maximum.at(hv, inv.ravel(), np.linalg.norm(d_all, axis=-1).max(axis=-1).ravel())
            hv = np.maximum(hv, 1e-300)
            d = d_all / hv[inv][:, :, None, None]
            P = _basis(d, deg)  # (e, c, g, np)
            npb = P.shape[-1]
            idx = np.repeat(inv.ravel(), ngp)  # (e*c*g,)
            Pf = P.reshape(-1, npb)
            Vf = np.broadcast_to(vals[:, None], (*inv.shape, ngp, ncomp)).reshape(-1, ncomp)
            A = np.zeros((nv, npb, npb))
            rhs = np.zeros((nv, npb, ncomp))
            np.add.at(A, idx, Pf[:, :, None] * Pf[:, None, :])
            np.add.at(rhs, idx, Pf[:, :, None] * Vf[:, None, :])
            npts = np.bincount(idx, minlength=nv)
            ok = npts >= int(1.5 * npb)
            with np.errstate(all="ignore"):
                cond = np.linalg.cond(A)
            ok &= np.isfinite(cond) & (cond < 1e8)
            coef = np.zeros((nv, npb, ncomp))
            if np.any(ok):
                coef[ok] = np.linalg.solve(A[ok], rhs[ok])
            # corner values; corners without a valid patch (boundary) take the mean of
            # the polynomials of valid neighbouring corners evaluated at their position
            vals_c = np.where(ok[:, None], coef[:, 0, :], np.nan)
            bad = ~ok
            if np.any(bad) and np.any(ok):
                nb_acc = np.zeros((nv, ncomp))
                nb_cnt = np.zeros(nv)
                for i in range(nc):
                    for j in range(nc):
                        if i == j:
                            continue
                        vi, vj = inv[:, i], inv[:, j]
                        sel = ok[vi] & bad[vj]
                        if not np.any(sel):
                            continue
                        dd = (xv[vj[sel]] - xv[vi[sel]]) / hv[vi[sel]][:, None]
                        val = np.einsum("ep,epk->ek", _basis(dd, deg), coef[vi[sel]])
                        np.add.at(nb_acc, vj[sel], val)
                        np.add.at(nb_cnt, vj[sel], 1.0)
                fix = bad & (nb_cnt > 0)
                vals_c[fix] = nb_acc[fix] / nb_cnt[fix, None]
            # mid-side nodes: polynomials of the edge's end corners (weight 1) or, if
            # neither has a valid patch, of any valid corner of the element (weight 1e-3)
            if b.etype in (ElemType.T6, ElemType.Q8):
                pairs = [(0, 1), (1, 2), (2, 0)] if nc == 3 else [(0, 1), (1, 2), (2, 3), (3, 0)]
                mids = conn[:, nc:]
                xm = mesh.coords[mids]  # (e, nmid, 2)
                num = np.zeros((*mids.shape, ncomp))
                den = np.zeros(mids.shape)
                for c in range(nc):
                    iv = inv[:, c]
                    good_c = ok[iv]
                    if not np.any(good_c):
                        continue
                    dd = (xm - xv[iv][:, None, :]) / hv[iv][:, None, None]
                    val = np.einsum("emp,epk->emk", _basis(dd, deg), coef[iv])
                    w = (
                        np.array([1.0 if c in pr else 1e-3 for pr in pairs])[None, :]
                        * good_c[:, None]
                    )
                    num += val * w[..., None]
                    den += w
                good = den > 0
                m_ids = mids[good]
                m_vals = num[good] / den[good][:, None]
                um, first = np.unique(m_ids, return_index=True)
                np.add.at(acc, um, m_vals[first])
                np.add.at(cnt, um, 1.0)
            gv = np.all(np.isfinite(vals_c), axis=-1)
            np.add.at(acc, v_ids[gv], vals_c[gv])
            np.add.at(cnt, v_ids[gv], 1.0)
    out = fallback.copy()
    m = cnt > 0
    out[m] = acc[m] / cnt[m, None]
    if boundary == "extrapolate":
        bn = boundary_nodes(mesh)
        out[bn] = fallback[bn]
    elif boundary != "spr":
        raise ValueError("boundary must be 'extrapolate' or 'spr'")
    return out


def _active_fields(mesh, gp_values, active, gp_coords=None):
    """Subset element rows without changing the stored stage history or node IDs."""
    if not active:
        return mesh, gp_values, gp_coords
    blocks, values, coords = [], {}, {}
    for b in mesh.continuum_blocks():
        mask = np.asarray(active.get(b.tag, np.ones(b.ne, dtype=bool)), dtype=bool)
        if mask.shape != (b.ne,):
            raise ValueError(f"active mask for '{b.tag}' must have shape ({b.ne},)")
        if not mask.any():
            continue
        blocks.append(replace(b, conn=b.conn[mask], region=b.region[mask]))
        if b.tag in gp_values:
            values[b.tag] = gp_values[b.tag][mask]
            if gp_coords is not None:
                coords[b.tag] = gp_coords[b.tag][mask]
    return replace(mesh, blocks=tuple(blocks)), values, coords

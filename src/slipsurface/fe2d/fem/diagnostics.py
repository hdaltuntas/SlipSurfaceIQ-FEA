"""Opt-in geometry, stiffness and spatial-stress diagnostics; never alter a solve."""

from __future__ import annotations

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import LinearOperator, norm, onenormest, splu

from .elements import kernel


def jacobian_report(mesh, order="high") -> dict:
    """Sample actual isoparametric J at the chosen Gauss rule, including midnodes.

    detJ has units of length squared; its reduction with h is normal. Scaled J
    and cond_2(J) measure shape. Sampling does not certify every point of a curved cell.
    """
    out = {}
    for block in mesh.continuum_blocks():
        if not block.ne:
            continue
        elem = kernel(block.etype)
        rule = elem.rule(order)
        _, dN = elem.shape(rule.points)
        J = np.einsum("gni,enj->egij", dN, mesh.coords[block.conn], optimize=True)
        if not np.isfinite(J).all():
            raise ValueError("Jacobian diagnostic requires finite geometry")
        det = np.linalg.det(J)
        sv = np.linalg.svd(J, compute_uv=False)
        singular = sv[..., -1] == 0
        cond = np.full(det.shape, np.inf)
        np.divide(sv[..., 0], sv[..., -1], out=cond, where=~singular)
        denominator = np.linalg.norm(J[..., 0, :], axis=-1) * np.linalg.norm(J[..., 1, :], axis=-1)
        scaled = np.zeros_like(det)
        np.divide(det, denominator, out=scaled, where=denominator > 0)
        worst = np.unravel_index(np.argmax(cond), cond.shape)
        out[block.tag] = {
            "elements": block.ne,
            "gauss_order": order,
            "min_detJ": float(det.min()),
            "max_detJ": float(det.max()),
            "nonpositive_detJ_gp": int(np.count_nonzero(det <= 0)),
            "singular_J_gp": int(np.count_nonzero(singular)),
            "min_scaled_J": float(scaled.min()),
            "max_condition_2_J": None if singular.any() else float(cond.max()),
            "worst_condition_element": int(worst[0]),
            "worst_condition_gp": int(worst[1]),
        }
    return out


def _matrix_report(A):
    n = A.shape[0]
    norm1 = float(norm(A, 1))
    base = {"ndof": n, "nnz": A.nnz, "norm_1": norm1}
    try:
        lu = splu(A, permc_spec="COLAMD")
    except RuntimeError as exc:
        return {
            **base,
            "status": "factorization_failed",
            "detail": str(exc),
            "condition_1_estimate": None,
        }
    inverse = LinearOperator(
        A.shape,
        matvec=lu.solve,
        matmat=lu.solve,
        rmatvec=lambda x: lu.solve(x, trans="T"),
        rmatmat=lambda x: lu.solve(x, trans="T"),
        dtype=float,
    )
    # t=1 is deterministic and does not consume NumPy's global random state.
    estimate = norm1 * float(onenormest(inverse, t=1))
    return {
        **base,
        "status": "factored",
        "condition_1_estimate": estimate if np.isfinite(estimate) else None,
        "condition_estimate_finite": bool(np.isfinite(estimate)),
        "min_abs_U_pivot": float(np.abs(lu.U.diagonal()).min()),
        "U_growth": float(np.abs(lu.U.data).max() / np.abs(A.data).max()),
    }


def stiffness_report(K) -> dict:
    """One-norm condition estimates of K_ff, raw and diagonally scaled.

    Deterministic t=1 estimates are lower bounds, not an SPD or collapse test. Raw values
    depend on units/DOF scaling (notably translations versus beam rotations).
    Sparse LU is independent of the solve's factorization and does not modify K.
    """
    A = sp.csc_matrix(K, dtype=float, copy=True)
    if A.shape[0] == 0 or A.shape[0] != A.shape[1] or not np.isfinite(A.data).all():
        raise ValueError("need a finite, nonempty square stiffness matrix")
    raw = _matrix_report(A)
    diagonal = A.diagonal()
    scaled = None
    if np.all(diagonal != 0):
        S = sp.diags(1 / np.sqrt(np.abs(diagonal)), format="csc")
        scaled = _matrix_report((S @ A @ S).tocsc())
    return {
        "raw": raw,
        "diagonal_congruence": scaled,
        "nonpositive_diagonal": int(np.count_nonzero(diagonal <= 0)),
        "relative_asymmetry_1": float(norm(A - A.T, 1) / max(raw["norm_1"], 1e-300)),
    }


def spatial_stress_report(xg, sig, weights, points, radius=0.75, annulus=(0.5, 1.0)) -> dict:
    """Fixed physical neighborhoods; tensor Frobenius norm, not peak extrapolation.

    Compare only the same stage, load factor, material and quadrature. Closest-GP
    peaks can change sampling distance; a few mesh sizes cannot prove a singularity.
    """
    xg, sig, weights = np.asarray(xg), np.asarray(sig), np.asarray(weights)
    if (
        xg.ndim != 2
        or xg.shape[1] != 2
        or sig.shape != (len(xg), 4)
        or weights.shape != (len(xg),)
        or not len(xg)
        or not np.isfinite(xg).all()
        or not np.isfinite(sig).all()
        or not np.isfinite(weights).all()
        or np.any(weights <= 0)
        or not np.isfinite(radius)
        or not np.isfinite(annulus).all()
        or not 0 < radius
        or not 0 <= annulus[0] < annulus[1]
    ):
        raise ValueError("need finite GP arrays, positive weights and valid neighborhoods")
    magnitude = np.sqrt(np.sum(sig[:, :3] ** 2, axis=1) + 2 * sig[:, 3] ** 2)
    out = {}
    for name, point in points.items():
        point = np.asarray(point, dtype=float)
        if point.shape != (2,) or not np.isfinite(point).all():
            raise ValueError("probe points must have two finite coordinates")
        distance = np.linalg.norm(xg - point, axis=1)
        nearest = int(np.argmin(distance))
        inside = distance <= radius
        band = (distance >= annulus[0]) & (distance <= annulus[1])
        out[name] = {
            "xy": list(point),
            "nearest_gp_distance": float(distance[nearest]),
            "nearest_gp_stress_norm": float(magnitude[nearest]),
            "radius": radius,
            "gp_in_radius": int(inside.sum()),
            "max_stress_norm_in_radius": float(magnitude[inside].max()) if inside.any() else None,
            "annulus": list(annulus),
            "gp_in_annulus": int(band.sum()),
            "annulus_mean_stress_norm": float(np.average(magnitude[band], weights=weights[band]))
            if band.any()
            else None,
        }
    return out

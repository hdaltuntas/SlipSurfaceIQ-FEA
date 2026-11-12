"""Scalar axial grout bond-slip constitutive update for B5 tieback work.

The law acts on shear force per unit bonded length q [kN/m] and relative axial slip s [m]:

    q_trial = q_n + k_b * Delta s
    q_{n+1} = clamp(q_trial, -q_max, q_max)

where k_b [kN/m2] is bond shear stiffness and q_max [kN/m] is bond strength.
This module is deliberately independent of mesh/assembly. It is the constitutive
primitive that a later embedded BOND4 transfer element will call.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from ..model.materials import BondSlipSpec

Arr = NDArray[np.float64]


def bond_slip_return(
    committed_shear: float | Arr,
    slip_increment: float | Arr,
    spec: BondSlipSpec,
) -> tuple[Arr, Arr, NDArray[np.bool_]]:
    """Return-map a symmetric elastic-perfectly-plastic axial bond law.

    Returns (shear, tangent, yielded) with broadcast shape. tangent is the exact
    algorithmic derivative dq/d(Delta s): k_b in the elastic branch and zero on
    an outward plastic correction.
    """
    q0, ds = np.broadcast_arrays(
        np.asarray(committed_shear, dtype=float),
        np.asarray(slip_increment, dtype=float),
    )
    if not np.isfinite(q0).all() or not np.isfinite(ds).all():
        raise ValueError("Bond shear state and slip increment must be finite")

    limit = float(spec.strength)
    tol = 1e-12 * max(1.0, limit)
    if np.any(np.abs(q0) > limit + tol):
        raise ValueError("Committed bond shear exceeds the configured bond strength")

    trial = q0 + float(spec.stiffness) * ds
    yielded = np.abs(trial) > limit
    shear = np.clip(trial, -limit, limit)
    tangent = np.where(yielded, 0.0, float(spec.stiffness))
    return shear, tangent, yielded


__all__ = ["bond_slip_return"]

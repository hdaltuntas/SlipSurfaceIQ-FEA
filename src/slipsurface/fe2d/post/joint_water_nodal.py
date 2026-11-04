"""F7 independent nodal force check for straight vertical joint water pressure.

The IFACE4/IFACE6 external water load is assembled onto original mesh nodes.
An independent Newton-Cotes tributary formula checks each face-node force,
not merely the two equal and opposite face resultants. A separate closed-form
hydrostatic reference detects integration error at a water-table kink.
"""

from __future__ import annotations

import math

import numpy as np

from slipsurface.fe2d.core.enums import Analysis, ElemType
from slipsurface.fe2d.core.units import GAMMA_W
from slipsurface.fe2d.fem.structural import InterfaceGroup
from slipsurface.fe2d.post.balance_acceptance import classify_balance
from slipsurface.fe2d.post.joint_water_reference import vertical_joint_water_transfer


def nodal_force_comparison(actual, expected, *, tolerance=1e-10):
    """Compare signed in-plane nodal forces, retaining the residual vector."""
    actual = np.asarray(actual, dtype=float)
    expected = np.asarray(expected, dtype=float)
    if actual.shape != expected.shape or actual.ndim != 2 or actual.shape[1] != 2:
        raise ValueError("Nodal force arrays must have identical (nodes, 2) shape")
    if not np.isfinite(actual).all() or not np.isfinite(expected).all():
        raise ValueError("Nodal force arrays must be finite")
    error = actual - expected
    scale = max(float(np.linalg.norm(expected)), 1.0)
    result = {
        "max_abs_nodal_error_kn_per_m": float(np.max(np.abs(error))),
        "rms_nodal_error_kn_per_m": float(np.sqrt(np.mean(error**2))),
        "global_residual_fx_kn_per_m": float(error[:, 0].sum()),
        "global_residual_fy_kn_per_m": float(error[:, 1].sum()),
        "relative_residual": float(np.linalg.norm(error) / scale),
    }
    return classify_balance(result, "relative_residual", tolerance=tolerance)


def vertical_joint_nodal_water_audit(
    mesh, tag, spec, head, *, gamma_w=GAMMA_W, tolerance=1e-10
):
    """Independently check every face-node load and exact hydrostatic resultant.

    The nodal reference uses trapezoidal (IFACE4) or Simpson (IFACE6)
    tributary lengths. It requires a straight vertical joint with a
    consistent normal direction; the analytical benchmark validates that
    scope before any nodal comparison.
    """
    if not math.isfinite(float(head)) or not math.isfinite(float(gamma_w)):
        raise ValueError("Water head and unit weight must be finite")
    hydro = vertical_joint_water_transfer(
        mesh, tag, spec, head, gamma_w=gamma_w,
    )
    block = mesh.block(tag)
    group = InterfaceGroup(block, mesh.coords, spec, Analysis.PLANE_STRAIN)
    if block.etype is ElemType.IFACE4:
        fractions = np.array([0.5, 0.5])
    elif block.etype is ElemType.IFACE6:
        fractions = np.array([1.0 / 6, 1.0 / 6, 2.0 / 3])
    else:
        raise ValueError("Only IFACE4 and IFACE6 are supported")

    pressure = gamma_w * np.maximum(head - group.xip[..., 1], 0.0)
    ids = np.arange(block.ne, dtype=np.int64)
    force = group.pore_force(ids, pressure).reshape(block.ne, 2 * group.npe, 2)
    actual = np.zeros((mesh.nn, 2), dtype=float)
    np.add.at(actual, block.conn.ravel(), force.reshape(-1, 2))

    ends = mesh.coords[block.conn[:, :2]]
    length = np.abs(ends[:, 1, 1] - ends[:, 0, 1])
    normal_x = -np.sign(ends[:, 1, 1] - ends[:, 0, 1])
    if np.any(length <= 0):
        raise ValueError("Degenerate interface segment")
    face2_fx = normal_x[:, None] * pressure * length[:, None] * fractions[None, :]
    expected_face2 = np.stack(
        [face2_fx, np.zeros_like(face2_fx)], axis=-1
    )
    expected_element = np.concatenate([-expected_face2, expected_face2], axis=1)
    expected = np.zeros_like(actual)
    np.add.at(expected, block.conn.ravel(), expected_element.reshape(-1, 2))

    nodal = nodal_force_comparison(actual, expected, tolerance=tolerance)
    return {
        "interface": tag,
        "element_type": block.etype.name,
        "head_m": float(head),
        "node_count": mesh.nn,
        "nodal": nodal,
        "hydrostatic": hydro,
        "both_passed": (
            nodal["status"] == "passed" and hydro["status"] == "passed"
        ),
    }

"""Independent hydrostatic pressure-centre and moment check for vertical joints.

A face can carry the correct integrated water force but the wrong moment
because nodal load integration moves its line of action. This benchmark
compares the actual IFACE4/IFACE6 external pore-load vector to the exact
first moment of the piecewise hydrostatic pressure distribution.
"""

from __future__ import annotations

import math

import numpy as np

from slipsurface.fe2d.core.enums import Analysis, ElemType
from slipsurface.fe2d.core.units import GAMMA_W
from slipsurface.fe2d.fem.structural import InterfaceGroup
from slipsurface.fe2d.post.balance_acceptance import classify_balance
from slipsurface.fe2d.post.joint_water_reference import vertical_joint_water_transfer


def _wet_integrals(low, high, head):
    """Exact integrals of (head-y) and y*(head-y) along a wet segment."""
    upper = min(high, head)
    if upper <= low:
        return 0.0, 0.0
    force = head * (upper - low) - 0.5 * (upper**2 - low**2)
    first_moment = (
        0.5 * head * (upper**2 - low**2)
        - (upper**3 - low**3) / 3.0
    )
    return force, first_moment


def vertical_joint_water_moment(
    mesh, tag, spec, head, *, gamma_w=GAMMA_W, tolerance=1e-6
):
    """Check exact force, moment and pressure centre from real FEM node forces.

    Only straight vertical consistently oriented plane-strain interfaces
    are supported. The existing force audit validates that geometry.
    The moment is about (0,0), with Mz = x*Fy - y*Fx in kN m/m.
    """
    if not math.isfinite(float(head)) or not math.isfinite(float(gamma_w)):
        raise ValueError("Water parameters must be finite")
    force_audit = vertical_joint_water_transfer(
        mesh, tag, spec, head, gamma_w=gamma_w, tolerance=tolerance
    )
    block = mesh.block(tag)
    if block.etype not in (ElemType.IFACE4, ElemType.IFACE6):
        raise ValueError("Only IFACE4/IFACE6 supported")
    group = InterfaceGroup(block, mesh.coords, spec, Analysis.PLANE_STRAIN)
    ends = mesh.coords[block.conn[:, :2]]
    direction = float(np.sign(group.R[0, 0, 0, 1]))
    expected_force = 0.0
    expected_y_force = 0.0
    for first, second in ends:
        low, high = sorted((float(first[1]), float(second[1])))
        area, first_moment = _wet_integrals(low, high, float(head))
        expected_force += direction * gamma_w * area
        expected_y_force += direction * gamma_w * first_moment
    expected_moment = -expected_y_force
    pressure = gamma_w * np.maximum(head - group.xip[..., 1], 0.0)
    ids = np.arange(block.ne, dtype=np.int64)
    element_force = group.pore_force(ids, pressure).reshape(
        block.ne, 2 * group.npe, 2
    )
    actual_face2 = element_force[:, group.npe:, :]
    face2_coords = mesh.coords[block.conn[:, group.npe:]]
    assembled_force = float(actual_face2[..., 0].sum())
    actual_moment = float(np.sum(
        face2_coords[..., 0] * actual_face2[..., 1]
        - face2_coords[..., 1] * actual_face2[..., 0]
    ))
    scale = max(abs(expected_moment), 1.0)
    result = {
        "interface": tag,
        "element_type": block.etype.name,
        "head_m": float(head),
        "reference_force_kn_per_m": float(expected_force),
        "assembled_force_kn_per_m": assembled_force,
        "reference_moment_knm_per_m": float(expected_moment),
        "assembled_moment_knm_per_m": actual_moment,
        "reference_pressure_center_y_m": (
            float(expected_y_force / expected_force)
            if abs(expected_force) > 1e-12 else None
        ),
        "assembled_pressure_center_y_m": (
            float(-actual_moment / assembled_force)
            if abs(assembled_force) > 1e-12 else None
        ),
        "moment_error_knm_per_m": actual_moment - expected_moment,
        "relative_residual": abs(actual_moment - expected_moment) / scale,
    }
    moment_audit = classify_balance(
        result, "relative_residual", tolerance=tolerance
    )
    return {
        **moment_audit,
        "force_status": force_audit["status"],
        "force_relative_residual": force_audit["relative_residual"],
        "both_passed": (
            moment_audit["status"] == "passed"
            and force_audit["status"] == "passed"
        ),
    }

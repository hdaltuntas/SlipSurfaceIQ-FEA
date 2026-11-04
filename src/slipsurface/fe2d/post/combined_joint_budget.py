"""F7 combined effective interface traction and hydrostatic water moment audit.

Effective joint tractions are INTERNAL, while hydrostatic pore loads enter
as an EXTERNAL loading term. They must not be silently conflated. The
effective-traction benchmark is an assembly consistency check; the water
pressure has a separately derived closed-form physical force and moment.
"""

from __future__ import annotations

import numpy as np

from slipsurface.fe2d.core.enums import Analysis, ElemType
from slipsurface.fe2d.core.units import GAMMA_W
from slipsurface.fe2d.fem.structural import InterfaceGroup
from slipsurface.fe2d.post.balance_acceptance import classify_balance
from slipsurface.fe2d.post.joint_water_moment import vertical_joint_water_moment


def _face_moment(coords, forces):
    """Signed out-of-plane moment around global origin, kN m/m."""
    return float(np.sum(coords[..., 0] * forces[..., 1]
                        - coords[..., 1] * forces[..., 0]))


def combined_joint_force_moment(
    mesh, tag, spec, effective_tractions, water_head, *,
    gamma_w=GAMMA_W, tolerance=1e-6,
):
    """Check the assembled two-face interface traction + water load.

    Only straight vertical, fully active IFACE4/IFACE6 plane-strain joints.
    The mechanical reference reproduces the discrete effective traction
    quadrature; only the separate hydrostatic term is independently
    referenced to continuous mechanics.
    """
    water = vertical_joint_water_moment(
        mesh, tag, spec, water_head, gamma_w=gamma_w, tolerance=tolerance,
    )
    block = mesh.block(tag)
    if block.etype not in (ElemType.IFACE4, ElemType.IFACE6):
        raise ValueError("Only IFACE4/IFACE6 supported")
    group = InterfaceGroup(block, mesh.coords, spec, Analysis.PLANE_STRAIN)
    t = np.asarray(effective_tractions, dtype=float)
    if t.shape != (block.ne, group.npe, 2) or not np.isfinite(t).all():
        raise ValueError("All interface effective tractions must be finite and active")
    ids = np.arange(block.ne, dtype=np.int64)
    tangent = np.zeros((block.ne, group.npe, 2, 2))
    mechanical, _ = group._assemble(ids, t, tangent)
    water_pressure = gamma_w * np.maximum(
        float(water_head) - group.xip[..., 1], 0.0
    )
    hydraulic = group.pore_force(ids, water_pressure)
    n = group.npe
    effective_forces = mechanical.reshape(block.ne, 2 * n, 2)
    water_forces = hydraulic.reshape(block.ne, 2 * n, 2)
    combined = effective_forces + water_forces
    x = mesh.coords[block.conn]
    actual_face2 = combined[:, n:]
    actual_face1 = combined[:, :n]
    effective_reference = np.einsum(
        "epij,epj,ep->epi", group.R, t, group.w,
    )
    expected_effective_force = effective_reference.sum(axis=(0, 1))
    expected_effective_moment = _face_moment(group.xip, effective_reference)
    expected_water_force = np.array([
        water["reference_force_kn_per_m"], 0.0,
    ])
    expected_total_force = expected_effective_force + expected_water_force
    expected_total_moment = (
        expected_effective_moment + water["reference_moment_knm_per_m"]
    )
    force2 = actual_face2.sum(axis=(0, 1))
    moment2 = _face_moment(x[:, n:], actual_face2)
    force1 = actual_face1.sum(axis=(0, 1))
    moment1 = _face_moment(x[:, :n], actual_face1)
    reference_scale = max(
        float(np.linalg.norm(expected_total_force)),
        abs(expected_total_moment), 1.0,
    )
    force_error = float(np.linalg.norm(force2 - expected_total_force))
    moment_error = abs(moment2 - expected_total_moment)
    pair_force = float(np.linalg.norm(force1 + force2))
    pair_moment = abs(moment1 + moment2)
    result = {
        "interface": tag,
        "element_type": block.etype.name,
        "head_m": float(water_head),
        "effective_reference_force_fx_kn_per_m": float(expected_effective_force[0]),
        "effective_reference_force_fy_kn_per_m": float(expected_effective_force[1]),
        "effective_reference_moment_knm_per_m": expected_effective_moment,
        "water_reference_force_kn_per_m": float(expected_water_force[0]),
        "water_reference_moment_knm_per_m": float(water["reference_moment_knm_per_m"]),
        "expected_face2_fx_kn_per_m": float(expected_total_force[0]),
        "expected_face2_fy_kn_per_m": float(expected_total_force[1]),
        "expected_face2_moment_knm_per_m": float(expected_total_moment),
        "assembled_face2_fx_kn_per_m": float(force2[0]),
        "assembled_face2_fy_kn_per_m": float(force2[1]),
        "assembled_face2_moment_knm_per_m": moment2,
        "opposite_face_force_residual_kn_per_m": pair_force,
        "opposite_face_moment_residual_knm_per_m": pair_moment,
        "force_error_kn_per_m": force_error,
        "moment_error_knm_per_m": moment_error,
        "relative_residual": max(
            force_error, moment_error, pair_force, pair_moment
        ) / reference_scale,
    }
    classified = classify_balance(
        result, "relative_residual", tolerance=tolerance,
    )
    classified["hydrostatic_force_status"] = water["force_status"]
    classified["hydrostatic_moment_status"] = water["status"]
    classified["all_passed"] = (
        classified["status"] == "passed"
        and water["force_status"] == "passed"
        and water["status"] == "passed"
    )
    return classified

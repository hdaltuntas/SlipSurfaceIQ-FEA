"""F7 effective interface force and moment transfer for actual stage outputs.

Unlike an external analytical soil-structure benchmark, this is a strict
assembly-consistency audit. The local traction is independently rotated
and integrated into each face reference, then checked against the FEM
interface's nodal internal-force assembly and signed first moments.
"""

from __future__ import annotations

import numpy as np

from slipsurface.fe2d.core.enums import Analysis, ElemType
from slipsurface.fe2d.fem.structural import InterfaceGroup
from slipsurface.fe2d.post.balance_acceptance import classify_balance


def _moment(x, f):
    """Out-of-plane moment x*Fy-y*Fx about (0,0), kN m/m."""
    return float(np.sum(x[..., 0] * f[..., 1] - x[..., 1] * f[..., 0]))


def effective_interface_moment_audit(
    mesh, tag, tractions, spec, *, analysis=Analysis.PLANE_STRAIN,
    tolerance=1e-8,
):
    """Verify both signed face resultants and their physical moments.

    Entirely inactive NaN elements are excluded; nonfinite partially
    active tractions are rejected. Geometrically separated faces are
    reported as failed moment reciprocity, never silently collapsed.
    """
    block = mesh.block(tag)
    if block.etype not in (ElemType.IFACE4, ElemType.IFACE6):
        raise ValueError("Expected IFACE4/IFACE6 interface")
    if analysis is not Analysis.PLANE_STRAIN:
        raise ValueError("Plane-strain interface moment audit only")
    group = InterfaceGroup(block, mesh.coords, spec, analysis)
    t = np.asarray(tractions, dtype=float)
    if t.shape != (block.ne, group.npe, 2):
        raise ValueError("Invalid effective interface traction shape")
    inactive = np.all(np.isnan(t), axis=(1, 2))
    active = ~inactive
    if not np.isfinite(t[active]).all():
        raise ValueError("Nonfinite active interface traction")
    ids = np.flatnonzero(active)
    if ids.size == 0:
        return {
            "interface": tag, "active_elements": 0, "status": "unsupported",
            "reason": "No active interface traction to audit",
        }
    tangent = np.zeros((ids.size, group.npe, 2, 2), dtype=float)
    assembled, _ = group._assemble(ids, t[ids], tangent)
    nodal = assembled.reshape(ids.size, 2 * group.npe, 2)
    face1 = nodal[:, :group.npe]
    face2 = nodal[:, group.npe:]
    points1 = mesh.coords[block.conn[ids, :group.npe]]
    points2 = mesh.coords[block.conn[ids, group.npe:]]
    # Independent integration of local [shear, normal] into global force.
    reference = np.einsum(
        "epij,epj,ep->epi", group.R[ids], t[ids], group.w[ids]
    )
    ref_force = reference.sum(axis=(0, 1))
    f1, f2 = face1.sum(axis=(0, 1)), face2.sum(axis=(0, 1))
    m1, m2 = _moment(points1, face1), _moment(points2, face2)
    mr1, mr2 = -_moment(points1, reference), _moment(points2, reference)
    pair_force = float(np.linalg.norm(f1 + f2))
    pair_moment = abs(m1 + m2)
    face_error = max(
        float(np.linalg.norm(f1 + ref_force)),
        float(np.linalg.norm(f2 - ref_force)),
    )
    moment_error = max(abs(m1 - mr1), abs(m2 - mr2))
    scale_force = max(float(np.linalg.norm(ref_force)), 1.0)
    scale_moment = max(abs(mr1), abs(mr2), 1.0)
    residual = max(
        pair_force / scale_force, face_error / scale_force,
        pair_moment / scale_moment, moment_error / scale_moment,
    )
    result = {
        "interface": tag,
        "active_elements": int(ids.size),
        "face1_fx_kn_per_m": float(f1[0]),
        "face1_fy_kn_per_m": float(f1[1]),
        "face2_fx_kn_per_m": float(f2[0]),
        "face2_fy_kn_per_m": float(f2[1]),
        "face1_moment_knm_per_m": m1,
        "face2_moment_knm_per_m": m2,
        "face1_reference_moment_knm_per_m": mr1,
        "face2_reference_moment_knm_per_m": mr2,
        "action_reaction_force_error_kn_per_m": pair_force,
        "action_reaction_moment_error_knm_per_m": pair_moment,
        "reference_force_error_kn_per_m": face_error,
        "reference_moment_error_knm_per_m": moment_error,
        "relative_residual": residual,
    }
    return classify_balance(result, "relative_residual", tolerance=tolerance)


def stage_effective_interface_moment_audit(model, stage, *, tolerance=1e-8):
    """JSON-safe audit of every reported effective interface traction block."""
    results = {}
    for tag, t in sorted(stage.interfaces.items()):
        if tag not in model.interfaces:
            raise ValueError(f"Missing interface properties for '{tag}'")
        results[tag] = effective_interface_moment_audit(
            model.mesh, tag, t, model.interfaces[tag],
            analysis=model.analysis, tolerance=tolerance,
        )
    return results

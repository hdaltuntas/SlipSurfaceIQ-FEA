"""F7 independent hydrostatic joint-water action/reaction benchmark.

The constitutive effective-stress interface traction and externally applied
joint-water pressure are different terms. This audit tests only the latter:
global forces assembled by InterfaceGroup.pore_force on a vertical joint
against the analytical integral of p(y) = gamma_w*max(head-y, 0).

It does not claim coupled groundwater equilibrium in a staged excavation.
"""

from __future__ import annotations

import math

import numpy as np

from slipsurface.fe2d.core.enums import Analysis, ElemType
from slipsurface.fe2d.core.units import GAMMA_W
from slipsurface.fe2d.fem.structural import InterfaceGroup
from slipsurface.fe2d.post.balance_acceptance import classify_balance


def vertical_joint_water_transfer(
    mesh, tag, spec, head, *, analysis=Analysis.PLANE_STRAIN,
    gamma_w=GAMMA_W, tolerance=1e-6,
):
    """Compare face-assembled joint water forces to closed-form hydrostatics.

    Straight, vertical, consistently oriented IFACE4/IFACE6 elements only.
    The reported error includes quadrature error at a water table kink
    inside an element: it is never silently set to zero.
    """
    if analysis is not Analysis.PLANE_STRAIN:
        raise ValueError("Only plane strain is supported")
    if not math.isfinite(float(head)) or not math.isfinite(float(gamma_w)):
        raise ValueError("Water head and unit weight must be finite")
    if gamma_w <= 0:
        raise ValueError("Water unit weight must be positive")
    block = mesh.block(tag)
    if block.etype not in (ElemType.IFACE4, ElemType.IFACE6):
        raise ValueError("Expected IFACE4 or IFACE6 element block")
    group = InterfaceGroup(block, mesh.coords, spec, analysis)
    ends = mesh.coords[block.conn[:, :2]]
    if not np.allclose(ends[:, 0, 0], ends[:, 1, 0], atol=1e-10, rtol=0):
        raise ValueError("Interface elements must be vertical")
    if not np.allclose(group.xip[..., 0], ends[:, :1, 0], atol=1e-10, rtol=0):
        raise ValueError("Curved or nonvertical joint faces unsupported")
    # The exact local normal must be common to every element along the wall.
    nx = group.R[..., 0, 1]
    ny = group.R[..., 1, 1]
    if not np.allclose(np.abs(nx), 1.0, atol=1e-10, rtol=0) or not np.allclose(
        ny, 0.0, atol=1e-10, rtol=0
    ):
        raise ValueError("Joint interface normal is not horizontal")
    normal_sign = float(np.sign(nx[0, 0]))
    if not np.allclose(nx, normal_sign, atol=1e-10, rtol=0):
        raise ValueError("Joint elements have inconsistent normal orientation")

    # Disjoint segments are allowed, but overlapping physical interface
    # lengths would double-count the independent water resultant.
    spans = sorted(
        (min(float(v[0, 1]), float(v[1, 1])),
         max(float(v[0, 1]), float(v[1, 1]))) for v in ends
    )
    for (_lo, high), (next_low, _hi) in zip(spans, spans[1:]):
        if next_low < high - 1e-10:
            raise ValueError("Overlapping interface segments double-count water forces")

    p = gamma_w * np.maximum(head - group.xip[..., 1], 0.0)
    ids = np.arange(block.ne, dtype=np.int64)
    fe = group.pore_force(ids, p).reshape(block.ne, 2 * group.npe, 2)
    face1 = fe[:, :group.npe].sum(axis=(0, 1))
    face2 = fe[:, group.npe:].sum(axis=(0, 1))
    expected_magnitude = 0.5 * gamma_w * sum(
        max(head - low, 0.0) ** 2 - max(head - high, 0.0) ** 2
        for low, high in spans
    )
    reference = np.array([normal_sign * expected_magnitude, 0.0])
    err = face2 - reference
    scale = max(expected_magnitude, 1.0)
    result = {
        "interface": tag,
        "element_type": block.etype.name,
        "active_elements": block.ne,
        "head_m": float(head),
        "analytical_face2_fx_kn_per_m": float(reference[0]),
        "analytical_face2_fy_kn_per_m": float(reference[1]),
        "assembled_face1_fx_kn_per_m": float(face1[0]),
        "assembled_face1_fy_kn_per_m": float(face1[1]),
        "assembled_face2_fx_kn_per_m": float(face2[0]),
        "assembled_face2_fy_kn_per_m": float(face2[1]),
        "action_reaction_fx_kn_per_m": float(face1[0] + face2[0]),
        "action_reaction_fy_kn_per_m": float(face1[1] + face2[1]),
        "relative_residual": float(np.linalg.norm(err) / scale),
    }
    return classify_balance(result, "relative_residual", tolerance=tolerance)

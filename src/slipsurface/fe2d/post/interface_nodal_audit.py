"""Verify interface tractions as assembled FEM nodal-force contributions.

Unlike face-resultant reciprocity alone, this module scatters the interface
element's integrated *internal* force vector onto its actual mesh node IDs
and checks each face against the independently integrated traction resultants.

No claim is made about the equilibrium of the entire excavation domain:
continuum, beam, bar, pore-water and external loads remain distinct terms.
"""

from __future__ import annotations

import numpy as np

from slipsurface.fe2d.core.enums import Analysis, ElemType
from slipsurface.fe2d.fem.structural import InterfaceGroup
from slipsurface.fe2d.post.interface_balance import interface_force_pair


def interface_nodal_force_transfer(
    mesh, tag, tractions, spec, *, analysis=Analysis.PLANE_STRAIN
):
    """Scatter local interface internal forces onto original mesh node IDs.

    The two returned face resultants are sums of the assembled nodal forces,
    *not* force magnitudes. The same global node ID may occur in multiple
    elements, but scattering preserves it. Inactive (all-NaN) elements are
    excluded; partially invalid active elements raise.
    """
    block = mesh.block(tag)
    if block.etype not in (ElemType.IFACE4, ElemType.IFACE6):
        raise ValueError(f"{tag}: not an interface block")
    group = InterfaceGroup(block, mesh.coords, spec, analysis)
    t = np.asarray(tractions, dtype=float)
    if t.shape != (block.ne, group.npe, 2):
        raise ValueError(f"{tag}: inconsistent traction shape")
    inactive = np.all(np.isnan(t), axis=(1, 2))
    active = ~inactive
    if not np.isfinite(t[active]).all():
        raise ValueError(f"{tag}: nonfinite active interface traction")

    nodes = np.zeros((mesh.nn, 2), dtype=float)
    if np.any(active):
        ids = np.flatnonzero(active)
        tangent = np.zeros((len(ids), group.npe, 2, 2), dtype=float)
        element_force, _ = group._assemble(ids, t[ids], tangent)
        np.add.at(
            nodes,
            block.conn[ids].ravel(),
            element_force.reshape(-1, 2),
        )
        local_force = element_force.reshape(-1, 2 * group.npe, 2)
        face1 = local_force[:, :group.npe].sum(axis=(0, 1))
        face2 = local_force[:, group.npe:].sum(axis=(0, 1))
    else:
        face1 = np.zeros(2)
        face2 = np.zeros(2)

    independent = interface_force_pair(
        mesh, tag, t, spec, analysis=analysis
    )
    expected1 = np.array(
        [independent["face1_fx"], independent["face1_fy"]]
    )
    expected2 = np.array(
        [independent["face2_fx"], independent["face2_fy"]]
    )
    return {
        "tag": tag,
        "active_elements": int(np.count_nonzero(active)),
        "nodal_forces": nodes,
        "face1_resultant": face1,
        "face2_resultant": face2,
        "global_resultant": nodes.sum(axis=0),
        "face1_reference_error": face1 - expected1,
        "face2_reference_error": face2 - expected2,
    }


def stage_interface_nodal_audit(model, stage):
    """Compact JSON-safe per-stage interface nodal-transfer residuals."""
    results = {}
    for tag, tractions in stage.interfaces.items():
        if tag not in model.interfaces:
            raise ValueError(f"Missing interface properties for '{tag}'")
        out = interface_nodal_force_transfer(
            model.mesh, tag, tractions, model.interfaces[tag],
            analysis=model.analysis,
        )
        results[tag] = {
            "active_elements": out["active_elements"],
            "face1_fx": float(out["face1_resultant"][0]),
            "face1_fy": float(out["face1_resultant"][1]),
            "face2_fx": float(out["face2_resultant"][0]),
            "face2_fy": float(out["face2_resultant"][1]),
            "global_residual_fx": float(out["global_resultant"][0]),
            "global_residual_fy": float(out["global_resultant"][1]),
            "reference_error_fx": float(
                max(abs(out["face1_reference_error"][0]),
                    abs(out["face2_reference_error"][0]))
            ),
            "reference_error_fy": float(
                max(abs(out["face1_reference_error"][1]),
                    abs(out["face2_reference_error"][1]))
            ),
        }
    return results

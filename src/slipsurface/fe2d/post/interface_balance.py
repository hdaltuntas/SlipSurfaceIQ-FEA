"""F7 interface action/reaction audit for staged soil–support coupling.

The zero-thickness interface has two opposing faces. Integration of the
solver's local traction at interface integration points must yield exactly
opposite global forces on the soil and structural sides, per metre out of
plane. This diagnostic excludes separate interface-water pressure terms.
"""

from __future__ import annotations

import numpy as np

from slipsurface.fe2d.core.enums import Analysis, ElemType
from slipsurface.fe2d.fem.structural import InterfaceGroup


def interface_force_pair(mesh, tag, tractions, spec, *, analysis=Analysis.PLANE_STRAIN):
    """Return integrated face-1/face-2 forces and an action-reaction residual.

    Input t is (elements, interface points, 2) in local shear/normal
    coordinates. Inactive NaN elements are excluded; partially invalid active
    elements are rejected rather than replaced by zeros.
    """
    block = mesh.block(tag)
    if block.etype not in (ElemType.IFACE4, ElemType.IFACE6):
        raise ValueError(f"{tag}: not an interface block")
    group = InterfaceGroup(block, mesh.coords, spec, analysis)
    t = np.asarray(tractions, dtype=float)
    if t.shape != (block.ne, group.npe, 2):
        raise ValueError(f"{tag}: inconsistent traction shape")
    fully_inactive = np.all(np.isnan(t), axis=(1, 2))
    active = ~fully_inactive
    if not np.isfinite(t[active]).all():
        raise ValueError(f"{tag}: nonfinite active interface traction")
    forces = np.einsum(
        "epij,epj,ep->ei",
        group.R[active], t[active], group.w[active],
        optimize=True,
    ).sum(axis=0)
    if forces.shape != (2,):
        raise ValueError("Expected an in-plane force vector")
    face1 = -forces
    face2 = forces
    return {
        "tag": tag,
        "active_elements": int(np.count_nonzero(active)),
        "face1_fx": float(face1[0]),
        "face1_fy": float(face1[1]),
        "face2_fx": float(face2[0]),
        "face2_fy": float(face2[1]),
        "imbalance_fx": float(face1[0] + face2[0]),
        "imbalance_fy": float(face1[1] + face2[1]),
    }


def stage_interface_pairs(model, stage):
    """Audit all interface tags, requiring a matching material definition."""
    results = {}
    for tag, t in stage.interfaces.items():
        if tag not in model.interfaces:
            raise ValueError(f"Missing interface properties for '{tag}'")
        results[tag] = interface_force_pair(
            model.mesh, tag, t, model.interfaces[tag], analysis=model.analysis
        )
    return results

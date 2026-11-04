"""F7 topology gate for a continuous zero-thickness hydrostatic interface.

Equal-and-opposite force resultants and even correct per-node FEM assembly
cannot prove that physically adjacent interface elements share mesh node
IDs. This opt-in audit first verifies both continuous face-node chains,
then runs the existing independent nodal and analytical water-load gates.
"""

from __future__ import annotations

import numpy as np

from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.post.joint_water_nodal import vertical_joint_nodal_water_audit


def continuous_joint_water_audit(mesh, tag, spec, head, *, tolerance=1e-10):
    """Require adjacent interface segments to share nodes on *both* faces.

    A single straight, connected vertical joint is required. Each face's
    endpoint nodes must be connected by ID at segment junctions; the
    coincident opposite faces must remain topologically separate.
    """
    block = mesh.block(tag)
    if block.etype not in (ElemType.IFACE4, ElemType.IFACE6):
        raise ValueError("Expected IFACE4 or IFACE6 interface")
    if block.ne < 2:
        raise ValueError("At least two connected interface segments required")
    npe = 2 if block.etype is ElemType.IFACE4 else 3
    conn = block.conn
    coords = mesh.coords
    if np.any(conn[:, :npe] == conn[:, npe:]):
        raise ValueError("Opposite interface faces must use distinct node IDs")
    if not np.allclose(
        coords[conn[:, :npe]], coords[conn[:, npe:]], rtol=0, atol=1e-10
    ):
        raise ValueError("Opposite interface faces must be geometrically coincident")
    spans = []
    for element in conn:
        ids_a, ids_b = element[:2], element[npe:npe + 2]
        ya = coords[ids_a, 1]
        if abs(float(ya[0] - ya[1])) <= 1e-12:
            raise ValueError("Degenerate joint segment")
        lower, upper = int(np.argmin(ya)), int(np.argmax(ya))
        spans.append((
            float(ya[lower]), float(ya[upper]),
            (int(ids_a[lower]), int(ids_b[lower])),
            (int(ids_a[upper]), int(ids_b[upper])),
        ))
    spans.sort(key=lambda value: value[0])
    connected = 0
    for previous, current in zip(spans, spans[1:]):
        if abs(previous[1] - current[0]) > 1e-10:
            raise ValueError("Joint segments contain a gap or overlap")
        if previous[3] != current[2]:
            raise ValueError("Interface junction must share node IDs on both faces")
        connected += 1

    result = vertical_joint_nodal_water_audit(
        mesh, tag, spec, head, tolerance=tolerance,
    )
    return {
        **result,
        "connected_junctions": connected,
        "topology_status": "passed",
        "all_passed": result["both_passed"],
    }

"""Saved seepage head, head-BC and reported-discharge evidence for mechanical transfer.

This does not solve or independently verify Darcy/Picard equilibrium.
"""

from __future__ import annotations

import numpy as np

from ..core.units import GAMMA_W
from .seepage_boundary_evidence import seepage_boundary_evidence


def seepage_pressure_evidence(model, stage, water):
    if water.mode != "seepage":
        raise ValueError("An explicit seepage stage is required")
    if model.settings.gauss_order != "default":
        raise ValueError("Seepage pressure transfer currently requires default quadrature")
    mesh = model.mesh
    head = np.asarray(stage.head, dtype=float)
    used = np.zeros(mesh.nn, dtype=bool)
    for block in mesh.continuum_blocks():
        mask = np.asarray(stage.active[block.tag])
        if mask.dtype != bool or mask.shape != (block.ne,):
            raise ValueError("Invalid hydraulic active mask")
        used[block.conn[mask].ravel()] = True
    if not used.any() or head.shape != (mesh.nn,) or not np.isfinite(head[used]).all():
        raise ValueError("Missing/nonfinite active seepage heads")
    if not np.isnan(head[~used]).all():
        raise ValueError("Hydraulically inactive head entries must be NaN")
    boundary = seepage_boundary_evidence(mesh, stage, water, used, head)
    pressure = np.zeros(mesh.nn)
    pressure[used] = GAMMA_W * np.maximum(head[used] - mesh.coords[used, 1], 0.)
    return {
        "head": head, "nodal_pressure": pressure,
        "relative_residual": boundary["relative_residual"],
        "annotations": {
            **boundary["annotations"],
            "hydraulic_node_count": int(used.sum()),
            "hydraulically_inactive_zero_pressure_nodes": int((~used).sum()),
        },
    }

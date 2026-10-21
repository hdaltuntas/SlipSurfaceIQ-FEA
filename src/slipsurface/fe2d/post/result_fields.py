"""Shared stage selection and active geometry for desktop, exports and recovery."""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from ..fem.static import SolveResult, StageResult


def stage_result(result: SolveResult, stage=None) -> StageResult:
    if isinstance(stage, StageResult):
        return stage
    return result.last if stage is None else result.stage(stage)


def active_mesh(mesh, stage):
    """Keep node IDs and remove deactivated cells, including structures."""
    return replace(
        mesh,
        blocks=tuple(
            replace(
                b,
                conn=b.conn[stage.active.get(b.tag, np.ones(b.ne, bool))],
                region=b.region[stage.active.get(b.tag, np.ones(b.ne, bool))],
            )
            for b in mesh.blocks
        ),
    )


def active_values(mesh, stage, values):
    return {
        b.tag: values[b.tag][stage.active.get(b.tag, np.ones(b.ne, bool))]
        for b in mesh.continuum_blocks()
        if b.tag in values
    }


def recovered_stress(result, stage=None, method="spr"):
    from .recovery import nodal_average, spr

    st = stage_result(result, stage)
    mesh = result.model.mesh
    view = active_mesh(mesh, st)
    sig = active_values(mesh, st, st.sig)
    if method == "average":
        return nodal_average(view, sig)
    if method != "spr":
        raise ValueError(f"unknown recovery method '{method}'")
    xy = active_values(mesh, st, {k: g.xg for k, g in result.geom.items()})
    return spr(view, sig, xy)

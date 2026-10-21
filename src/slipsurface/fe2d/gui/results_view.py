"""Read-only PyVista result viewer (debugging aid before the full GUI of Faz 5).

Requires the optional dependency ``pyvista`` (``pip install slipsurface-fe2d[gui]``).

    from slipsurface.fe2d.gui import show_result
    show_result(res, "s1", deform=50)                    # interactive window
    show_result(res, "plastic", screenshot="pl.png")     # off-screen image
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..core.enums import ElemType
from ..fem.static import SolveResult
from ..post.recovery import nodal_average, principal_stresses, spr

_VTK = {ElemType.T3: 5, ElemType.T6: 22, ElemType.Q4: 9, ElemType.Q8: 23}


def _pv() -> Any:
    try:
        import pyvista as pv
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ImportError(
            "the result viewer needs PyVista: pip install 'slipsurface-fe2d[gui]'"
        ) from exc
    return pv


def to_pyvista(result: SolveResult, stage: str | int | None = None, deform: float = 0.0) -> Any:
    """``pyvista.UnstructuredGrid`` with point fields (u, stresses, s1, s3, q, eps_p) and
    cell field ``plastic`` (fraction of yielding Gauss points)."""
    pv = _pv()
    st = result.last if stage is None else result.stage(stage)
    mesh = result.model.mesh
    blocks = [b for b in mesh.continuum_blocks() if b.etype in _VTK]
    cells = np.concatenate(
        [np.hstack([np.full((b.ne, 1), b.etype.nen), b.conn]).ravel() for b in blocks]
    )
    types = np.concatenate([np.full(b.ne, _VTK[b.etype], dtype=np.uint8) for b in blocks])
    u = np.nan_to_num(st.u)
    pts = np.column_stack([mesh.coords + deform * u, np.zeros(mesh.nn)])
    grid = pv.UnstructuredGrid(cells, types, pts)
    s = spr(mesh, st.sig, {k: g.xg for k, g in result.geom.items()})
    p = principal_stresses(s)
    grid.point_data["u"] = np.column_stack([u, np.zeros(mesh.nn)])
    grid.point_data["|u|"] = np.linalg.norm(u, axis=1)
    for i, name in enumerate(("sxx", "syy", "szz", "txy")):
        grid.point_data[name] = s[:, i]
    for name in ("s1", "s3", "q"):
        grid.point_data[name] = p[name]
    if st.q:
        grid.point_data["eps_p"] = np.maximum(
            0.0, nodal_average(mesh, {k: v[..., :1] for k, v in st.q.items()})[:, 0]
        )
    if st.plastic:
        grid.cell_data["plastic"] = np.concatenate(
            [(st.plastic[b.tag] > 0).mean(axis=1) for b in blocks]
        )
    return grid


def show_result(
    result: SolveResult,
    field: str = "|u|",
    stage: str | int | None = None,
    deform: float = 0.0,
    show_edges: bool = False,
    screenshot: str | None = None,
    cmap: str = "viridis",
) -> Any:
    """Contour plot of ``field``; with ``screenshot`` renders off-screen to a PNG."""
    pv = _pv()
    grid = to_pyvista(result, stage, deform)
    pl = pv.Plotter(off_screen=screenshot is not None)
    pl.add_mesh(grid, scalars=field, show_edges=show_edges, cmap=cmap,
                scalar_bar_args={"title": field})  # fmt: skip
    pl.view_xy()
    if screenshot is not None:
        pl.screenshot(screenshot)
        pl.close()
        return screenshot
    pl.show()
    return pl

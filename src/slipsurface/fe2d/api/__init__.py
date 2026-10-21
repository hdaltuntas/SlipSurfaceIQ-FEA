"""Public scripting API (L6).

Example::

    from slipsurface.fe2d import api
    from slipsurface.fe2d.mesh import rectangle

    mesh = rectangle(20.0, 10.0, 40, 20)
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"clay": api.MaterialSpec.elastic("clay", E=2e4, nu=0.3, gamma=18.0)},
        region_material={1: "clay"},
        fixities=(api.Fixity("bottom", True, True), api.Fixity("left", True, False),
                  api.Fixity("right", True, False)),
        stages=[api.Stage("footing", loads=(api.EdgeLoad("top", qn=100.0),))],
    )
    res = api.run(model)
    api.export_vtu(res, "footing.vtu")
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np

from ..core.enums import Analysis, Drainage, ElemType, PlasticFlag
from ..fem.progress import SolveCancelled, SolveProgress
from ..fem.srf import SRFResult, strength_reduction
from ..fem.static import SolveResult, StageResult, solve
from ..io.project import Project, load_project, save_project
from ..io.project_json import load_model, save_model
from ..io.results_h5 import (
    ResultsFile,
    ResultsReader,
    load_results,
    read_results,
    save_results,
    write_results,
)
from ..io.ssproj import open_project_results
from ..io.vtk_export import write_vtu
from ..model import (
    BoltSpec,
    Displacement,
    EdgeLoad,
    ElementBlock,
    Fixity,
    InitialStress,
    InterfaceSpec,
    LinerSpec,
    MaterialSpec,
    Mesh,
    Model,
    PointLoad,
    SolverSettings,
    Stage,
    WaterCondition,
)
from ..post.recovery import nodal_average, principal_stresses
from ..post.result_fields import active_mesh, active_values, recovered_stress, stage_result


def run(
    model: Model, *, progress: Callable[[SolveProgress], None] | None = None,
    cancel: Callable[[], bool] | None = None,
) -> SolveResult:
    """Validate and solve ``model`` (initial stress + all stages)."""
    return solve(model, progress=progress, cancel=cancel)


def nodal_stress(
    result: SolveResult, stage: str | int | None = None, method: str = "spr"
) -> np.ndarray:
    """Nodal stresses (nn, 4): ``method="spr"`` (patch recovery) or ``"average"``."""
    return recovered_stress(result, stage, method)


def export_vtu(
    result: SolveResult,
    path: str | Path,
    stage: str | int | None = None,
    method: str = "spr",
) -> Path:
    """Write displacements, nodal stresses (core sign convention) and plastic state.

    Point data: displacement, sxx/syy/szz/txy, s1/s3/q (recovered with ``method``),
    eps_p (equivalent plastic strain, averaged). Cell data: plastic (fraction of
    yielding Gauss points per element).
    """
    st = stage_result(result, stage)
    original_mesh = result.model.mesh
    mesh = active_mesh(original_mesh, st)
    s = nodal_stress(result, stage, method)
    p = principal_stresses(s)
    pd = {
        "displacement": st.u,
        "sxx": s[:, 0],
        "syy": s[:, 1],
        "szz": s[:, 2],
        "txy": s[:, 3],
        "s1": p["s1"],
        "s3": p["s3"],
        "q": p["q"],
    }
    cd = {}
    if st.q:
        pd["eps_p"] = np.maximum(
            0.0, nodal_average(mesh, active_values(original_mesh, st,
                          {k: v[..., :1] for k, v in st.q.items()}))[:, 0]
        )
    if st.plastic:
        values = []
        for b in mesh.blocks:
            if b.etype in (ElemType.IFACE4, ElemType.IFACE6):
                continue  # zero-thickness joints are not VTU volume/line cells
            if b.tag in st.plastic:
                mask = st.active.get(b.tag, np.ones(b.ne, bool))
                value = (st.plastic[b.tag][mask] > 0).mean(axis=1)
            else:
                value = np.full(b.ne, np.nan)
            values.append(value)
        cd["plastic"] = np.concatenate(values)
    return write_vtu(path, mesh, pd, cd)


__all__ = [
    "ResultsFile",
    "write_results",
    "Analysis",
    "Displacement",
    "Drainage",
    "EdgeLoad",
    "ElemType",
    "ElementBlock",
    "Fixity",
    "InitialStress",
    "InterfaceSpec",
    "BoltSpec",
    "LinerSpec",
    "WaterCondition",
    "MaterialSpec",
    "Mesh",
    "Model",
    "PlasticFlag",
    "PointLoad",
    "Project",
    "ResultsReader",
    "SRFResult",
    "SolveResult",
    "SolveProgress",
    "SolveCancelled",
    "SolverSettings",
    "Stage",
    "StageResult",
    "export_vtu",
    "load_model",
    "load_project",
    "open_project_results",
    "read_results",
    "load_results",
    "nodal_stress",
    "run",
    "save_model",
    "save_project",
    "save_results",
    "strength_reduction",
]

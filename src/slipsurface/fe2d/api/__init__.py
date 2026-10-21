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

from pathlib import Path

import numpy as np

from ..core.enums import Analysis, Drainage, ElemType, PlasticFlag
from ..fem.srf import SRFResult, strength_reduction
from ..fem.static import SolveResult, StageResult, solve
from ..io.project_json import load_model, save_model
from ..io.vtk_export import write_vtu
from ..model import (
    Displacement,
    EdgeLoad,
    ElementBlock,
    Fixity,
    InitialStress,
    MaterialSpec,
    Mesh,
    Model,
    PointLoad,
    SolverSettings,
    Stage,
)
from ..post.recovery import nodal_average, principal_stresses


def run(model: Model) -> SolveResult:
    """Validate and solve ``model`` (initial stress + all stages)."""
    return solve(model)


def nodal_stress(result: SolveResult, stage: str | int | None = None) -> np.ndarray:
    st = result.last if stage is None else result.stage(stage)
    return nodal_average(result.model.mesh, st.sig)


def export_vtu(result: SolveResult, path: str | Path, stage: str | int | None = None) -> Path:
    """Write displacements and nodal stresses (core sign convention) of one stage."""
    st: StageResult = result.last if stage is None else result.stage(stage)
    mesh = result.model.mesh
    s = nodal_average(mesh, st.sig)
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
    return write_vtu(path, mesh, pd)


__all__ = [
    "Analysis",
    "Displacement",
    "Drainage",
    "EdgeLoad",
    "ElemType",
    "ElementBlock",
    "Fixity",
    "InitialStress",
    "MaterialSpec",
    "Mesh",
    "Model",
    "PlasticFlag",
    "PointLoad",
    "SRFResult",
    "SolveResult",
    "SolverSettings",
    "Stage",
    "StageResult",
    "export_vtu",
    "load_model",
    "nodal_stress",
    "run",
    "save_model",
    "strength_reduction",
]

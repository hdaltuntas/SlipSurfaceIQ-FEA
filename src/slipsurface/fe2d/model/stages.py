"""Stage, initial-stress and solver-setting definitions (L1)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .boundary import EdgeLoad, PointLoad, WaterCondition


@dataclass(frozen=True)
class Stage:
    name: str
    active_regions: frozenset[int] | None = None  # None -> all continuum regions
    active_structures: frozenset[str] = frozenset()
    material_override: dict[int, str] = field(default_factory=dict)
    loads: tuple[EdgeLoad | PointLoad, ...] = ()
    water: WaterCondition = field(default_factory=WaterCondition)
    load_split: float = 1.0
    reset_displacements: bool = False


@dataclass(frozen=True)
class InitialStress:
    """How the in-situ stress state is generated before the first user stage.

    * ``"gravity"``: elastic gravity analysis; displacements are reset afterwards.
    * ``"k0_field"``: sv = -sum(gamma*h) below ``surface_y`` (horizontal layering),
      sh = K0*sv, szz = K0*sv. ``k0=None`` uses 1 - sin(phi), or nu/(1-nu) for elastic
      materials.
    * ``"none"``: stress-free start, no self-weight.
    """

    mode: str = "gravity"
    k0: float | None = None
    surface_y: float | None = None  # k0_field: None -> max y of the mesh


@dataclass(frozen=True)
class SolverSettings:
    linear_solver: str = "auto"  # "auto" | "splu" | "pardiso"
    gauss_order: str = "default"  # "default" | "high" (T6: 6-point rule)
    # nonlinear (Faz 2)
    method: str = "NR"
    max_iter: int = 30
    tol_force: float = 1e-3
    tol_energy: float = 1e-3
    dlam0: float = 0.1
    dlam_min: float = 1e-4

"""Stage, initial-stress and solver-setting definitions (L1)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .boundary import Displacement, EdgeLoad, PointLoad, WaterCondition


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
    # prescribed displacements for this stage (total values, added to Model.displacements);
    # they are reached linearly over the stage's load steps
    displacements: tuple[Displacement, ...] = ()


@dataclass(frozen=True)
class InitialStress:
    """How the in-situ stress state is generated before the first user stage.

    * ``"gravity"``: elastic gravity analysis; displacements are reset afterwards.
    * ``"k0_field"``: sv = -sum(gamma*h) below ``surface_y`` (horizontal layering),
      sh = K0*sv, szz = K0*sv. ``k0=None`` uses 1 - sin(phi), or nu/(1-nu) for elastic
      materials.
    * ``"field"``: constant stress ``field = (sxx, syy, szz, txy)`` everywhere (deep
      tunnels, laboratory element tests), no self-weight unless ``gravity=True``.
    * ``"none"``: stress-free start, no self-weight.

    The gravity analysis uses the real (possibly plastic) materials.
    """

    mode: str = "gravity"
    k0: float | None = None
    surface_y: float | None = None  # k0_field: None -> max y of the mesh
    field: tuple[float, float, float, float] | None = None
    gravity: bool = False  # "field" mode: also apply self-weight in the stages

    def __post_init__(self) -> None:
        if self.field is not None:
            object.__setattr__(self, "field", tuple(float(v) for v in self.field))


@dataclass(frozen=True)
class SolverSettings:
    linear_solver: str = "auto"  # "auto" | "splu" | "pardiso"
    gauss_order: str = "default"  # "default" | "high" (T6: 6-point rule)
    # nonlinear stage solution (Faz 2)
    method: str = "NR"  # "NR" | "mNR" | "hybrid" | "initial"
    max_iter: int = 30
    tol_force: float = 1e-3  # ||R|| / ||delta f_ext||
    tol_energy: float = 1e-3  # |du.R| / |du0.R0|
    dlam0: float = 0.1  # first load-factor increment of a plastic stage
    dlam_min: float = 1e-4
    dlam_max: float = 0.5
    fast_iter: int = 4  # converged in <= fast_iter iterations -> grow the step x1.5
    line_search: bool = False
    hybrid_ratio: float = 0.5  # hybrid: switch mNR -> NR if ||R_i||/||R_i-1|| > ratio

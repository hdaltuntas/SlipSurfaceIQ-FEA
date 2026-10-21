"""Material and structural property specifications (L1)."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.enums import Drainage
from ..core.errors import ModelError

_REQUIRED = {
    "elastic": ("E", "nu"),
    "mohr_coulomb": ("E", "nu", "c", "phi"),
    "hoek_brown": ("E", "nu", "sigci", "GSI", "mi"),
    "mcc": ("nu", "M", "lam", "kappa", "e0"),
    "drucker_prager": ("E", "nu", "c", "phi"),
}


@dataclass(frozen=True)
class MaterialSpec:
    name: str
    model: str  # "elastic" | "mohr_coulomb" | "hoek_brown" | "mcc" | "drucker_prager"
    params: dict[str, float]
    gamma_unsat: float = 0.0  # kN/m3
    gamma_sat: float = 0.0
    drainage: Drainage = Drainage.DRAINED
    k_sat: tuple[float, float] = (1e-7, 1e-7)  # kx, ky [m/s]

    def __post_init__(self) -> None:
        if self.model not in _REQUIRED:
            raise ModelError(f"material '{self.name}': unknown model '{self.model}'")
        missing = [p for p in _REQUIRED[self.model] if p not in self.params]
        if missing:
            raise ModelError(f"material '{self.name}': missing parameters {missing}")
        if "nu" in self.params and not (-1.0 < self.params["nu"] < 0.5):
            raise ModelError(f"material '{self.name}': nu must be in (-1, 0.5)")
        if "E" in self.params and self.params["E"] <= 0.0:
            raise ModelError(f"material '{self.name}': E must be positive")

    @classmethod
    def elastic(
        cls, name: str, E: float, nu: float, gamma: float = 0.0, gamma_sat: float | None = None
    ) -> MaterialSpec:
        return cls(
            name, "elastic", {"E": E, "nu": nu}, gamma, gamma if gamma_sat is None else gamma_sat
        )


@dataclass(frozen=True)
class LinerSpec:
    """Timoshenko beam (liner, wall, sheet pile) — per metre out of plane."""

    name: str
    E: float
    nu: float
    A: float
    I: float  # noqa: E741
    As: float
    unit_weight: float = 0.0


@dataclass(frozen=True)
class BoltSpec:
    """End-anchored or fully bonded bar. 2D equivalence: EA/s, T/s."""

    name: str
    EA: float
    T_yield: float
    pretension: float = 0.0
    spacing_out_of_plane: float = 1.0
    extra: dict[str, float] = field(default_factory=dict)

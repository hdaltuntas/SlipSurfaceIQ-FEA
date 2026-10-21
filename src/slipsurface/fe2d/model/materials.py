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
    "von_mises": ("E", "nu", "sy"),
}
DP_MATCH = ("plane_strain", "outer", "inner")  # params["match"] code -> matching


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
        if self.model in ("mohr_coulomb", "drucker_prager"):
            phi, psi = self.params["phi"], self.params.get("psi", 0.0)
            if not (0.0 <= psi <= phi < 90.0):
                raise ModelError(f"material '{self.name}': need 0 <= psi <= phi < 90")
            if self.params["c"] < 0.0:
                raise ModelError(f"material '{self.name}': c must be >= 0")

    @classmethod
    def elastic(
        cls, name: str, E: float, nu: float, gamma: float = 0.0, gamma_sat: float | None = None
    ) -> MaterialSpec:
        return cls(
            name, "elastic", {"E": E, "nu": nu}, gamma, gamma if gamma_sat is None else gamma_sat
        )

    @classmethod
    def mohr_coulomb(
        cls,
        name: str,
        E: float,
        nu: float,
        c: float,
        phi: float,
        psi: float = 0.0,
        sig_t: float | None = None,
        gamma: float = 0.0,
        gamma_sat: float | None = None,
    ) -> MaterialSpec:
        """Mohr-Coulomb; ``sig_t`` = tensile strength (``None``: apex c·cot(phi) only)."""
        p = {"E": E, "nu": nu, "c": c, "phi": phi, "psi": psi}
        if sig_t is not None:
            p["sig_t"] = sig_t
        return cls(name, "mohr_coulomb", p, gamma, gamma if gamma_sat is None else gamma_sat)

    @classmethod
    def drucker_prager(
        cls,
        name: str,
        E: float,
        nu: float,
        c: float,
        phi: float,
        psi: float = 0.0,
        match: str = "plane_strain",
        gamma: float = 0.0,
    ) -> MaterialSpec:
        p = {"E": E, "nu": nu, "c": c, "phi": phi, "psi": psi, "match": DP_MATCH.index(match)}
        return cls(name, "drucker_prager", p, gamma, gamma)

    @classmethod
    def von_mises(
        cls, name: str, E: float, nu: float, sy: float, H: float = 0.0, gamma: float = 0.0
    ) -> MaterialSpec:
        return cls(name, "von_mises", {"E": E, "nu": nu, "sy": sy, "H": H}, gamma, gamma)

    def with_strength_factor(self, F: float) -> MaterialSpec:
        """Strength reduced by F: c/F, tan(phi)/F, psi -> min(psi, phi_F) (SRF)."""
        import math

        if self.model not in ("mohr_coulomb", "drucker_prager"):
            return self
        p = dict(self.params)
        p["c"] = p["c"] / F
        phi_f = math.degrees(math.atan(math.tan(math.radians(p["phi"])) / F))
        p["phi"] = phi_f
        p["psi"] = min(p.get("psi", 0.0), phi_f)
        return MaterialSpec(
            f"{self.name}@F={F:.6g}", self.model, p, self.gamma_unsat, self.gamma_sat,
            self.drainage, self.k_sat,
        )  # fmt: skip


@dataclass(frozen=True)
class LinerSpec:
    """Timoshenko beam (liner, wall, sheet pile) — per metre out of plane.

    E [kPa], nu, A [m2/m], I [m4/m], As (shear area) [m2/m], unit_weight [kN/m3].
    Plane strain uses E / (1 - nu^2) for axial and bending stiffness.
    """

    name: str
    E: float
    nu: float
    A: float
    I: float  # noqa: E741
    As: float
    unit_weight: float = 0.0


@dataclass(frozen=True)
class InterfaceSpec:
    """Zero-thickness Goodman interface: normal/shear stiffness [kPa/m], Mohr-Coulomb slip
    (c, phi, psi) and tensile strength ``sig_t`` (gap opening above it).

    Use :meth:`from_soil` for the usual reduction of the adjacent soil strength
    (``R_inter``: tan(phi_i) = R tan(phi), c_i = R c) with a stiffness based on a virtual
    thickness ``t_v`` (``ks = G_i / t_v``, ``kn = Eoed_i / t_v``).
    """

    name: str
    kn: float
    ks: float
    c: float = 0.0
    phi: float = 0.0
    psi: float = 0.0
    sig_t: float = 0.0

    def __post_init__(self) -> None:
        if self.kn <= 0 or self.ks < 0:
            raise ModelError(f"interface '{self.name}': need kn > 0, ks >= 0")
        if not (0.0 <= self.psi <= self.phi < 90.0) or self.c < 0 or self.sig_t < 0:
            raise ModelError(f"interface '{self.name}': invalid strength parameters")

    @classmethod
    def from_soil(
        cls,
        name: str,
        soil: MaterialSpec,
        R: float = 0.67,
        t_v: float = 0.1,
        R_stiffness: float | None = None,
    ) -> InterfaceSpec:
        """Strength from ``R`` (``c_i = R c``, ``tan phi_i = R tan phi``); stiffness from
        ``E_i = R_s^2 E`` with ``R_s = R_stiffness`` (default ``R``, as in PLAXIS). Use
        ``R_stiffness=1`` for a smooth wall (``R`` -> 0) that must stay normally stiff."""
        import math

        p = soil.params
        E, nu = p["E"], p["nu"]
        Rs = R if R_stiffness is None else R_stiffness
        if not (0.0 < R <= 1.0 and 0.0 < Rs <= 1.0):
            raise ModelError(f"interface '{name}': R and R_stiffness must be in (0, 1]")
        Ei = Rs * Rs * E
        G = Ei / (2 * (1 + nu))
        Eoed = Ei * (1 - nu) / ((1 + nu) * (1 - 2 * nu))
        phi = math.degrees(math.atan(R * math.tan(math.radians(p.get("phi", 0.0)))))
        return cls(name, Eoed / t_v, G / t_v, R * p.get("c", 0.0), phi, 0.0,
                   R * p.get("sig_t", 0.0))  # fmt: skip


@dataclass(frozen=True)
class BoltSpec:
    """End-anchored or fully bonded bar. 2D equivalence: EA/s, T/s."""

    name: str
    EA: float
    T_yield: float
    pretension: float = 0.0
    spacing_out_of_plane: float = 1.0
    extra: dict[str, float] = field(default_factory=dict)

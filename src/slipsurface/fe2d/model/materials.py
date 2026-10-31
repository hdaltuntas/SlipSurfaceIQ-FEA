"""Material and structural property specifications (L1)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..core.enums import Drainage
from ..core.errors import ModelError


def hoek_diederichs_ratio(GSI: float, D: float = 0.0) -> float:
    """``Erm / Ei`` of Hoek & Diederichs (2006); ``D`` is the blast disturbance factor."""
    return 0.02 + (1.0 - D / 2.0) / (1.0 + math.exp((60.0 + 15.0 * D - GSI) / 11.0))


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
    # unsaturated flow (van Genuchten-Mualem): alpha [1/m], n [-], relative k floor
    vg: tuple[float, float, float] = (1.0, 2.0, 1e-4)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ModelError("material name must not be empty")
        if not all(math.isfinite(v) and v >= 0 for v in (self.gamma_unsat, self.gamma_sat)):
            raise ModelError(f"material '{self.name}': unit weights must be finite and >= 0")
        if self.model not in _REQUIRED:
            raise ModelError(f"material '{self.name}': unknown model '{self.model}'")
        missing = [p for p in _REQUIRED[self.model] if p not in self.params]
        if missing:
            raise ModelError(f"material '{self.name}': missing parameters {missing}")
        object.__setattr__(self, "k_sat", tuple(float(v) for v in self.k_sat))
        object.__setattr__(self, "vg", tuple(float(v) for v in self.vg))
        if (len(self.k_sat) != 2 or len(self.vg) != 3
                or not all(math.isfinite(v) for v in (*self.k_sat, *self.vg))
                or min(self.k_sat) < 0 or self.vg[0] <= 0 or self.vg[1] <= 1
                or not 0 < self.vg[2] <= 1):
            raise ModelError(f"material '{self.name}': invalid hydraulic parameters")
        if not all(math.isfinite(v) for v in self.params.values()):
            raise ModelError(f"material '{self.name}': parameters must be finite")
        if "Kw_n" in self.params and self.params["Kw_n"] <= 0:
            raise ModelError(f"material '{self.name}': Kw_n must be positive")
        if "nu" in self.params and not (-1.0 < self.params["nu"] < 0.5):
            raise ModelError(f"material '{self.name}': nu must be in (-1, 0.5)")
        if "E" in self.params and self.params["E"] <= 0.0:
            raise ModelError(f"material '{self.name}': E must be positive")
        object.__setattr__(self, "drainage", Drainage(self.drainage))
        if self.drainage is Drainage.UNDRAINED_C and self.model == "mcc":
            raise ModelError(f"material '{self.name}': undrained (C) needs total-stress parameters")
        if self.model in ("mohr_coulomb", "drucker_prager"):
            phi, psi = self.params["phi"], self.params.get("psi", 0.0)
            if not (0.0 <= psi <= phi < 90.0):
                raise ModelError(f"material '{self.name}': need 0 <= psi <= phi < 90")
            if self.params["c"] < 0.0:
                raise ModelError(f"material '{self.name}': c must be >= 0")
        if self.drainage is Drainage.UNDRAINED_B:
            if self.model not in ("elastic", "mohr_coulomb", "drucker_prager", "von_mises"):
                raise ModelError("undrained B requires a total undrained strength model")
            if self.params.get("phi", 0.0) != 0.0:
                raise ModelError("undrained B requires phi = 0 and c = su")
        if self.model == "hoek_brown":
            p = self.params
            if p["sigci"] <= 0 or not 0 < p["GSI"] <= 100 or p["mi"] <= 0:
                raise ModelError(f"material '{self.name}': need sigci > 0, 0 < GSI <= 100, mi > 0")
            if not 0.0 <= p.get("D", 0.0) <= 1.0 or not 0.0 <= p.get("psi", 0.0) < 90.0:
                raise ModelError(f"material '{self.name}': need 0 <= D <= 1, 0 <= psi < 90")
        if self.params.get("rankine_at_apex", False):
            if self.model != "mohr_coulomb" or self.params["phi"] <= 0 or "sig_t" in self.params:
                raise ModelError("rankine_at_apex needs Mohr-Coulomb, phi > 0 and no sig_t")
        if self.params.get("rankine_at_apex", False) not in (False, True):
            raise ModelError("rankine_at_apex must be boolean")

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
        *,
        rankine_at_apex: bool = False,
    ) -> MaterialSpec:
        """MC with optional associated Rankine flow.

        ``sig_t=None`` adds no Rankine flow. ``rankine_at_apex=True`` explicitly
        adds it at c·cot(phi), recalculated from the current strengths under SRF.
        A numeric ``sig_t`` instead sets an independent, fixed tensile strength.
        """
        p = {"E": E, "nu": nu, "c": c, "phi": phi, "psi": psi}
        if sig_t is not None:
            p["sig_t"] = sig_t
        if rankine_at_apex:
            p["rankine_at_apex"] = rankine_at_apex
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

    @classmethod
    def hoek_brown(
        cls,
        name: str,
        E: float,
        nu: float,
        sigci: float,
        GSI: float,
        mi: float,
        D: float = 0.0,
        psi: float = 0.0,
        gamma: float = 0.0,
        gamma_sat: float | None = None,
    ) -> MaterialSpec:
        """Generalised Hoek-Brown (2002): intact UCS ``sigci`` [kPa], GSI, mi, disturbance
        D; MC-type plastic potential with dilation ``psi`` [deg]."""
        p = {"E": E, "nu": nu, "sigci": sigci, "GSI": GSI, "mi": mi, "D": D, "psi": psi}
        return cls(name, "hoek_brown", p, gamma, gamma if gamma_sat is None else gamma_sat)

    @classmethod
    def mcc(
        cls,
        name: str,
        nu: float,
        M: float,
        lam: float,
        kappa: float,
        e0: float,
        OCR: float = 1.0,
        gamma: float = 0.0,
        gamma_sat: float | None = None,
        drainage: Drainage = Drainage.DRAINED,
        p_min: float = 1.0,
        p_ref: float = 100.0,
    ) -> MaterialSpec:
        """Modified Cam-Clay (lambda, kappa: slopes in e - ln p'; OCR sets the initial
        preconsolidation pressure from the initial stress state)."""
        p = {"nu": nu, "M": M, "lam": lam, "kappa": kappa, "e0": e0, "OCR": OCR,
             "p_min": p_min, "p_ref": p_ref}  # fmt: skip
        return cls(name, "mcc", p, gamma, gamma if gamma_sat is None else gamma_sat, drainage)

    def with_drainage(self, drainage: Drainage, Kw_n: float | None = None) -> MaterialSpec:
        """Copy with another drainage type; ``Kw_n`` overrides the water bulk stiffness
        (method A/B, default 100 K')."""
        import dataclasses

        p = dict(self.params)
        if Kw_n is not None:
            p["Kw_n"] = Kw_n
        return dataclasses.replace(self, params=p, drainage=drainage)

    def with_disturbance(self, D: float, name: str | None = None) -> MaterialSpec:
        """Hoek-Brown copy with blast disturbance ``D`` and Hoek–Diederichs reduced E.

        The parent ``E`` is the rock-mass modulus at the parent's ``D`` (usually 0).
        ``mb``, ``s`` follow from GSI, mi and the new ``D`` at constitutive build time.
        """
        if self.model != "hoek_brown":
            raise ModelError("örselenme yalnız Hoek-Brown kaya malzemesinde tanımlanır")
        if not 0.0 <= D <= 1.0:
            raise ModelError(f"material '{self.name}': need 0 <= D <= 1")
        p = dict(self.params)
        D0 = float(p.get("D", 0.0))
        p["E"] = p["E"] * hoek_diederichs_ratio(p["GSI"], D) / hoek_diederichs_ratio(p["GSI"], D0)
        p["D"] = D
        new_name = name if name is not None else f"{self.name}_D{D:g}"
        return MaterialSpec(
            new_name, self.model, p, self.gamma_unsat, self.gamma_sat,
            self.drainage, self.k_sat, self.vg,
        )  # fmt: skip

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
            self.drainage, self.k_sat, self.vg,
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

    def __post_init__(self) -> None:
        if not all(math.isfinite(v) and v > 0 for v in (self.E, self.A, self.I)):
            raise ModelError(f"liner '{self.name}': E, A and I must be finite and positive")
        if not math.isfinite(self.As) or self.As < 0:
            raise ModelError(f"liner '{self.name}': As must be finite and nonnegative")
        if not -1 < self.nu < 0.5 or not math.isfinite(self.unit_weight) or self.unit_weight < 0:
            raise ModelError(f"liner '{self.name}': invalid nu or unit weight")


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
        if not all(math.isfinite(v) for v in
                   (self.kn, self.ks, self.c, self.phi, self.psi, self.sig_t)):
            raise ModelError(f"interface '{self.name}': properties must be finite")
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

    def __post_init__(self) -> None:
        if not all(math.isfinite(v) and v > 0
                   for v in (self.EA, self.T_yield, self.spacing_out_of_plane)):
            raise ModelError(f"bolt '{self.name}': EA, yield force and spacing must be positive")
        if not math.isfinite(self.pretension) or self.pretension < 0:
            raise ModelError(f"bolt '{self.name}': pretension must be finite and nonnegative")

"""Shotcrete, wire mesh and steel sets smeared to one Timoshenko liner.

No geometry library: the equivalent section is plain data so the beam check can run
without the CAD extra. ``EA`` and ``EI`` are per metre of tunnel, before the plane-strain
factor ``1 / (1 - nu^2)`` applied by the beam element.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace

import numpy as np

# Steel sets: A [cm2], I [cm4] about the bending axis of the ring (approximate catalogue values).
STEEL_RIBS = {
    "Yok": (0.0, 0.0),
    "IPN 160": (22.8, 935.0),
    "IPN 180": (27.9, 1450.0),
    "IPN 200": (33.4, 2140.0),
    "HEB 100": (26.0, 450.0),
    "HEB 120": (34.0, 864.0),
    "HEB 140": (43.0, 1509.0),
    "HEB 160": (54.3, 2492.0),
    "HEB 180": (65.3, 3831.0),
    "HEB 200": (78.1, 5696.0),
    "TH 21": (26.9, 342.0),
    "TH 29": (37.0, 616.0),
}
# Welded wire mesh: steel area per metre [cm2/m] in the main direction.
WIRE_MESH = {
    "Yok": 0.0,
    "Q131": 1.31,
    "Q188": 1.88,
    "Q221": 2.21,
    "Q257": 2.57,
    "Q335": 3.35,
    "Q378": 3.78,
    "Q443": 4.43,
    "Q524": 5.24,
    "Q636": 6.36,
}


@dataclass(frozen=True)
class LiningSystem:
    """Shotcrete + wire mesh + steel sets smeared to one Timoshenko liner per metre of tunnel.

    ``EA = Ec t + Es (n As_mesh + A_rib / s)``, ``EI = Ec t^3 / 12 + Es I_rib / s`` (+ two
    mesh layers at ``±(t / 2 - cover)``); the liner keeps ``E = Ec`` with ``A = EA / Ec`` and
    ``I = EI / Ec``.
    """

    name: str = "Püskürtme beton 25 cm"
    thickness: float = 0.25  # m
    E_shotcrete: float = 1.5e7  # kPa (young shotcrete ~ 5-15 GPa, hardened ~ 25-30 GPa)
    nu: float = 0.2
    unit_weight: float = 24.0
    mesh: str = "Q257"
    mesh_layers: int = 1
    cover: float = 0.03
    rib: str = "Yok"
    rib_area: float = 0.0  # cm2 (custom when rib == "Özel")
    rib_inertia: float = 0.0  # cm4
    rib_spacing: float = 1.0  # m along the tunnel axis
    E_steel: float = 2.1e8  # kPa

    def __post_init__(self):
        values = [self.thickness, self.E_shotcrete, self.unit_weight, self.rib_spacing]
        if not (np.isfinite(values).all() and min(values[:2]) > 0 and self.rib_spacing > 0):
            raise ValueError("Kalınlık, E ve iksa aralığı pozitif olmalıdır.")
        if self.mesh not in WIRE_MESH or self.mesh_layers not in (1, 2):
            raise ValueError("Hasır çelik tipi veya katman sayısı geçersiz.")
        if self.rib != "Özel" and self.rib not in STEEL_RIBS:
            raise ValueError("Çelik iksa profili geçersiz.")

    def rib_section(self):
        """Steel set area [m2] and inertia [m4]."""
        if self.rib == "Özel":
            return self.rib_area * 1e-4, self.rib_inertia * 1e-8
        area, inertia = STEEL_RIBS[self.rib]
        return area * 1e-4, inertia * 1e-8

    def stiffness(self):
        """``(EA [kN/m], EI [kNm2/m])`` per metre of tunnel."""
        t, Ec, Es = self.thickness, self.E_shotcrete, self.E_steel
        As = WIRE_MESH[self.mesh] * 1e-4 * self.mesh_layers
        rib_a, rib_i = self.rib_section()
        EA = Ec * t + Es * (As + rib_a / self.rib_spacing)
        EI = Ec * t**3 / 12 + Es * rib_i / self.rib_spacing
        if self.mesh_layers == 2:
            EI += Es * As * max(t / 2 - self.cover, 0.0) ** 2
        return EA, EI

    def liner_properties(self):
        EA, EI = self.stiffness()
        A, I = EA / self.E_shotcrete, EI / self.E_shotcrete  # noqa: E741
        return dict(E=self.E_shotcrete, nu=self.nu, A=A, I=I, As=A * 5 / 6,
                    unit_weight=self.unit_weight)  # fmt: skip

    def to_dict(self):
        return asdict(self)

    def with_steel(self, steel: SteelSet) -> LiningSystem:
        """Smear ``steel`` into this shotcrete lining (one Timoshenko beam)."""
        return replace(
            self,
            rib=steel.rib,
            rib_area=steel.rib_area,
            rib_inertia=steel.rib_inertia,
            rib_spacing=steel.spacing,
            E_steel=steel.E_steel,
        )


@dataclass(frozen=True)
class SteelSet:
    """Discrete steel ribs smeared per metre of tunnel (spacing along the axis)."""

    rib: str = "HEB 140"
    spacing: float = 1.0  # m along the tunnel axis
    rib_area: float = 0.0  # cm2 (custom when rib == "Özel")
    rib_inertia: float = 0.0  # cm4
    E_steel: float = 2.1e8  # kPa
    nu: float = 0.3
    unit_weight: float = 78.5  # kN/m3

    def __post_init__(self):
        if not np.isfinite([self.spacing, self.E_steel, self.unit_weight]).all():
            raise ValueError("Çelik iksa aralığı, E ve birim ağırlık sonlu olmalıdır.")
        if self.spacing <= 0 or self.E_steel <= 0 or self.unit_weight < 0:
            raise ValueError("Çelik iksa aralığı ve E pozitif, birim ağırlık ≥ 0 olmalıdır.")
        if self.rib != "Özel" and (self.rib not in STEEL_RIBS or self.rib == "Yok"):
            raise ValueError("Çelik iksa profili seçilmelidir.")
        if not -1.0 < self.nu < 0.5:
            raise ValueError("Çelik iksa ν (-1, 0.5) aralığında olmalıdır.")

    def rib_section(self):
        """Steel set area [m2] and inertia [m4] of one rib."""
        if self.rib == "Özel":
            return self.rib_area * 1e-4, self.rib_inertia * 1e-8
        area, inertia = STEEL_RIBS[self.rib]
        return area * 1e-4, inertia * 1e-8

    def liner_properties(self):
        """Equivalent Timoshenko section per metre of tunnel (no shotcrete)."""
        area, inertia = self.rib_section()
        A, I = area / self.spacing, inertia / self.spacing  # noqa: E741
        return dict(E=self.E_steel, nu=self.nu, A=A, I=I, As=A * 5 / 6,
                    unit_weight=self.unit_weight)  # fmt: skip

    def to_dict(self):
        return asdict(self)

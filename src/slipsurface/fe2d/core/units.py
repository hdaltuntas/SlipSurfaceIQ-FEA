"""Unit system and sign convention (L0).

Units are fixed to kN, m, kPa, s. No unit conversion happens inside the core; these
constants exist so that code reads explicitly and post-processing can label outputs.

Sign convention inside the core: continuum mechanics, **tension positive**.
Stress vector ``[sxx, syy, szz, txy]``; strain vector ``[exx, eyy, ezz, gxy]`` with
engineering shear strain ``gxy = 2 * exy``. In axisymmetric analysis x = r, y = z and the
third component is the hoop (theta) direction. Geotechnical display (compression
positive) is applied only in the post-processing layer.
"""

from __future__ import annotations

FORCE = "kN"
LENGTH = "m"
STRESS = "kPa"
TIME = "s"
UNIT_WEIGHT = "kN/m3"

GAMMA_W: float = 9.81
"""Unit weight of water [kN/m3]."""

NSTRESS: int = 4
"""Number of stress components stored per Gauss point."""

STRESS_LABELS: tuple[str, ...] = ("sxx", "syy", "szz", "txy")


def to_geotechnical(stress_component: float) -> float:
    """Flip sign for compression-positive display (post-processing only)."""
    return -stress_component

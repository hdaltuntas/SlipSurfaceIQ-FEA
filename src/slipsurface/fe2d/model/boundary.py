"""Boundary conditions and loads (L1).

Load sign conventions
---------------------
* ``EdgeLoad.qn`` > 0 is a **pressure**: it pushes into the material (acts against the
  outward normal). ``qt`` acts along the edge tangent obtained by rotating the outward
  normal 90° counter-clockwise. The outward side is determined from the adjacent element,
  so edge node order does not matter.
* ``PointLoad`` components are global, in kN/m (plane strain) or kN/rad (axisymmetric).
* In axisymmetric analysis all loads and reactions are **per radian**.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class Fixity:
    node_set: str
    ux: bool
    uy: bool
    rz: bool = False


@dataclass(frozen=True)
class Displacement:
    """Prescribed (possibly non-zero) displacement; ``None`` leaves the component free."""

    node_set: str
    ux: float | None = None
    uy: float | None = None


@dataclass(frozen=True)
class EdgeLoad:
    edge_set: str
    qn: float = 0.0  # kPa, pressure positive
    qt: float = 0.0  # kPa


@dataclass(frozen=True)
class PointLoad:
    node: int
    fx: float = 0.0
    fy: float = 0.0


@dataclass(frozen=True)
class HeadBC:
    node_set: str
    head: float  # m


@dataclass(frozen=True)
class FluxBC:
    edge_set: str
    q: float  # m/s


@dataclass(frozen=True, eq=False)
class WaterCondition:
    mode: str = "none"  # "none" | "piezo_line" | "seepage"
    piezo_polyline: NDArray[np.float64] | None = None
    head_bcs: tuple[HeadBC, ...] = ()
    flux_bcs: tuple[FluxBC, ...] = ()

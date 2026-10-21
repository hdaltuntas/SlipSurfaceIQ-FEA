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
    """Groundwater for a stage.

    ``"piezo_line"``: hydrostatic pore pressure p = gamma_w (h(x) - y) below the polyline
    h(x) (linearly interpolated, constant beyond its ends); ``"none"``: dry.
    ``"seepage"`` (steady-state flow) arrives in Faz 4.
    """

    mode: str = "none"  # "none" | "piezo_line" | "seepage"
    piezo_polyline: NDArray[np.float64] | None = None
    head_bcs: tuple[HeadBC, ...] = ()
    flux_bcs: tuple[FluxBC, ...] = ()

    def __post_init__(self) -> None:
        if self.piezo_polyline is not None:
            p = np.atleast_2d(np.asarray(self.piezo_polyline, dtype=float))
            if p.shape[1] != 2 or p.shape[0] < 1:
                raise ValueError("piezo_polyline must have shape (n, 2)")
            order = np.argsort(p[:, 0], kind="stable")
            object.__setattr__(self, "piezo_polyline", p[order])
        if self.mode == "piezo_line" and self.piezo_polyline is None:
            raise ValueError("mode 'piezo_line' needs piezo_polyline")

    @classmethod
    def piezo(cls, points: object) -> WaterCondition:
        """Phreatic/piezometric line from (x, h) points; one point = horizontal level."""
        return cls("piezo_line", np.atleast_2d(np.asarray(points, dtype=float)))

    def head(self, x: NDArray[np.float64]) -> NDArray[np.float64]:
        """Piezometric level h(x) (-inf when dry)."""
        if self.mode != "piezo_line" or self.piezo_polyline is None:
            return np.full(np.shape(x), -np.inf)
        p = self.piezo_polyline
        if p.shape[0] == 1:
            return np.full(np.shape(x), p[0, 1])
        return np.interp(x, p[:, 0], p[:, 1])

    def key(self) -> tuple:
        pl = None if self.piezo_polyline is None else self.piezo_polyline.tobytes()
        return (self.mode, pl, self.head_bcs, self.flux_bcs)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, WaterCondition) and self.key() == other.key()

    def __hash__(self) -> int:
        return hash(self.key())

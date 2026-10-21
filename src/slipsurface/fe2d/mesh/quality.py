"""Mesh quality report (corner geometry of triangles)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from ..core.enums import ElemType
from ..model.mesh import Mesh


@dataclass(frozen=True, eq=False)
class QualityReport:
    n_elements: int
    min_angle: float  # degrees, worst element
    max_angle: float
    mean_min_angle: float
    max_aspect: float  # longest edge / shortest altitude-based ratio (1.155 = equilateral)
    max_radius_edge: float  # circumradius / shortest edge (0.577 = equilateral)
    angle_hist: tuple[NDArray[np.int64], NDArray[np.float64]]  # counts, bin edges
    per_element_min_angle: NDArray[np.float64]

    def __str__(self) -> str:
        counts, edges = self.angle_hist
        rows = "\n".join(
            f"  {edges[i]:5.1f}–{edges[i + 1]:5.1f}°  {counts[i]:8d}" for i in range(counts.size)
        )
        return (
            f"elements: {self.n_elements}\n"
            f"min angle: {self.min_angle:.2f}°  "
            f"(mean of element minima {self.mean_min_angle:.2f}°)\n"
            f"max angle: {self.max_angle:.2f}°\n"
            f"max aspect ratio: {self.max_aspect:.3f}\n"
            f"max radius/edge: {self.max_radius_edge:.3f}\n"
            f"element minimum-angle histogram:\n{rows}"
        )


def triangle_angles(coords: NDArray[np.float64], conn: NDArray[np.int64]) -> NDArray[np.float64]:
    """Corner angles in degrees, (ne, 3) for corners 0, 1, 2."""
    X = coords[conn[:, :3]]
    out = np.empty((X.shape[0], 3))
    for i in range(3):
        u = X[:, (i + 1) % 3] - X[:, i]
        v = X[:, (i + 2) % 3] - X[:, i]
        cos = np.einsum("ij,ij->i", u, v) / (np.linalg.norm(u, axis=1) * np.linalg.norm(v, axis=1))
        out[:, i] = np.degrees(np.arccos(np.clip(cos, -1.0, 1.0)))
    return out


def mesh_quality(mesh: Mesh) -> QualityReport:
    blocks = [b for b in mesh.blocks if b.etype in (ElemType.T3, ElemType.T6)]
    conn = np.vstack([b.conn[:, :3] for b in blocks]) if blocks else np.empty((0, 3), int)
    ang = triangle_angles(mesh.coords, conn)
    X = mesh.coords[conn]
    e = np.stack([np.linalg.norm(X[:, (i + 1) % 3] - X[:, i], axis=1) for i in range(3)], 1)
    area = 0.5 * np.abs(
        (X[:, 1, 0] - X[:, 0, 0]) * (X[:, 2, 1] - X[:, 0, 1])
        - (X[:, 2, 0] - X[:, 0, 0]) * (X[:, 1, 1] - X[:, 0, 1])
    )
    lmax, lmin = e.max(axis=1), e.min(axis=1)
    aspect = lmax**2 / (2.0 * area)  # longest edge / its altitude
    R = e.prod(axis=1) / (4.0 * area)
    amin = ang.min(axis=1)
    hist = np.histogram(amin, bins=np.arange(0.0, 65.0, 5.0))
    return QualityReport(
        n_elements=int(conn.shape[0]),
        min_angle=float(amin.min()),
        max_angle=float(ang.max()),
        mean_min_angle=float(amin.mean()),
        max_aspect=float(aspect.max()),
        max_radius_edge=float((R / lmin).max()),
        angle_hist=(hist[0], hist[1]),
        per_element_min_angle=amin,
    )

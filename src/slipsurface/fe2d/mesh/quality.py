"""Corner-geometry quality for triangle/quad meshes; curved Jacobians need FE checks."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from ..core.enums import ElemType
from ..core.errors import MeshError
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
    n_triangles: int = 0
    n_quads: int = 0
    min_quad_scaled_jacobian: float = float("nan")

    def __str__(self) -> str:
        counts, edges = self.angle_hist
        rows = "\n".join(
            f"  {edges[i]:5.1f}–{edges[i + 1]:5.1f}°  {counts[i]:8d}" for i in range(counts.size)
        )
        return (
            f"elements: {self.n_elements} (triangles {self.n_triangles}, quads {self.n_quads})\n"
            f"min angle: {self.min_angle:.2f}°  "
            f"(mean of element minima {self.mean_min_angle:.2f}°)\n"
            f"max angle: {self.max_angle:.2f}°\n"
            f"max aspect ratio: {self.max_aspect:.3f}\n"
            f"max radius/edge (triangles only): {self.max_radius_edge:.3f}\n"
            f"min scaled Jacobian (quad corners): {self.min_quad_scaled_jacobian:.3f}\n"
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
    angles, aspects, radii, jacobians = [], [], [], []
    ntri = nquad = 0
    for block in mesh.continuum_blocks():
        if not block.ne:
            continue
        if block.etype in (ElemType.T3, ElemType.T6):
            ntri += block.ne
            conn = block.conn[:, :3]
            ang = triangle_angles(mesh.coords, conn)
            X = mesh.coords[conn]
            e = np.stack([np.linalg.norm(X[:, (i + 1) % 3] - X[:, i], axis=1) for i in range(3)], 1)
            area2 = np.abs(
                (X[:, 1, 0] - X[:, 0, 0]) * (X[:, 2, 1] - X[:, 0, 1])
                - (X[:, 2, 0] - X[:, 0, 0]) * (X[:, 1, 1] - X[:, 0, 1])
            )
            aspects.append(e.max(axis=1) ** 2 / area2)
            radii.append(e.prod(axis=1) / (2 * area2 * e.min(axis=1)))
        else:
            nquad += block.ne
            X = mesh.coords[block.conn[:, :4]]
            edge = np.roll(X, -1, axis=1) - X
            prev = np.roll(edge, 1, axis=1)
            lengths = np.linalg.norm(edge, axis=2)
            cross = prev[..., 0] * edge[..., 1] - prev[..., 1] * edge[..., 0]
            ang = 180 - np.degrees(np.arctan2(cross, np.sum(prev * edge, axis=2)))
            denominator = np.roll(lengths, 1, axis=1) * lengths
            jacobians.append(np.min(cross / denominator, axis=1))
            mincross = cross.min(axis=1)
            aspect = np.full(block.ne, np.inf)
            np.divide(lengths.max(axis=1) ** 2, mincross, out=aspect, where=mincross > 0)
            aspects.append(aspect)
        angles.append(ang)
    if not angles:
        raise MeshError("quality report requires at least one continuum element")
    amin = np.concatenate([a.min(axis=1) for a in angles])
    hist = np.histogram(amin, bins=np.arange(0.0, 100.0, 5.0))
    return QualityReport(
        n_elements=ntri + nquad,
        min_angle=float(amin.min()),
        max_angle=float(max(a.max() for a in angles)),
        mean_min_angle=float(amin.mean()),
        max_aspect=float(np.concatenate(aspects).max()),
        max_radius_edge=float(np.concatenate(radii).max()) if radii else float("nan"),
        angle_hist=(hist[0], hist[1]),
        per_element_min_angle=amin,
        n_triangles=ntri,
        n_quads=nquad,
        min_quad_scaled_jacobian=float(np.concatenate(jacobians).min())
        if jacobians
        else float("nan"),
    )

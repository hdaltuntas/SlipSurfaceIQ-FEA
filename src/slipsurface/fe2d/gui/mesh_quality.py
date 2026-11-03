"""Geometric preflight diagnostics for continuum finite-element meshes.

Reports corner-geometry area and aspect proxies only. High-order Jacobians
must still be validated by the element quadrature kernels before solving.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.enums import ElemType
from ..model.mesh import Mesh


@dataclass(frozen=True)
class MeshQualityReport:
    elements: int
    minimum_area: float
    median_area: float
    maximum_aspect: float
    inverted_or_degenerate: int
    tiny_elements: int

    def summary(self) -> str:
        return (
            f"Continuum elements: {self.elements:,}\n"
            f"Minimum corner area: {self.minimum_area:.6g} m²\n"
            f"Median corner area: {self.median_area:.6g} m²\n"
            f"Maximum edge aspect proxy: {self.maximum_aspect:.3g}\n"
            f"Inverted / degenerate: {self.inverted_or_degenerate}\n"
            f"Tiny area (< 1% of median): {self.tiny_elements}\n\n"
            "Corner geometry only; curved T6/Q8 Jacobian quality is not checked. "
            "Review material interfaces and re-entrant corners before FEM validation."
        )


def mesh_quality_report(mesh: Mesh) -> MeshQualityReport:
    areas = []
    aspects = []
    inverted = 0
    for block in mesh.continuum_blocks():
        corners = 3 if block.etype in (ElemType.T3, ElemType.T6) else 4
        points = mesh.coords[block.conn[:, :corners]]
        if not len(points):
            continue
        nxt = np.roll(points, -1, axis=1)
        cross = points[..., 0] * nxt[..., 1] - nxt[..., 0] * points[..., 1]
        area = 0.5 * np.sum(cross, axis=1)
        lengths = np.linalg.norm(nxt - points, axis=2)
        minimum = np.min(lengths, axis=1)
        maximum = np.max(lengths, axis=1)
        aspects.extend((maximum / np.maximum(minimum, 1e-30)).tolist())
        areas.extend(area.tolist())
        inverted += int(np.count_nonzero(~np.isfinite(area) | (area <= 0)))
    if not areas:
        return MeshQualityReport(0, 0.0, 0.0, 0.0, 0, 0)
    magnitude = np.abs(np.asarray(areas, dtype=float))
    median = float(np.median(magnitude))
    return MeshQualityReport(
        elements=len(areas),
        minimum_area=float(np.min(magnitude)),
        median_area=median,
        maximum_aspect=float(np.max(aspects)),
        inverted_or_degenerate=inverted,
        tiny_elements=int(np.count_nonzero(magnitude < 0.01 * median)),
    )

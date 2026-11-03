"""Geometric and Gauss-point Jacobian preflight for continuum FEM meshes.

The report does not replace convergence or constitutive validation. It checks
the same default reference quadrature used by the element kernels, without
assembling global matrices or allocating full element B matrices.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.enums import ElemType
from ..fem.elements import kernel
from ..model.mesh import Mesh


@dataclass(frozen=True)
class MeshQualityReport:
    elements: int
    minimum_area: float
    median_area: float
    maximum_aspect: float
    inverted_or_degenerate: int
    tiny_elements: int
    minimum_jacobian: float = 0.0
    nonpositive_jacobian_elements: int = 0
    sampled_gauss_points: int = 0

    def summary(self) -> str:
        return (
            f"Continuum elements: {self.elements:,}\n"
            f"Minimum corner area: {self.minimum_area:.6g} m²\n"
            f"Median corner area: {self.median_area:.6g} m²\n"
            f"Maximum edge aspect proxy: {self.maximum_aspect:.3g}\n"
            f"Inverted / degenerate corner polygons: {self.inverted_or_degenerate}\n"
            f"Tiny area (< 1% of median): {self.tiny_elements}\n"
            f"Minimum Gauss-point det(J): {self.minimum_jacobian:.6g}\n"
            f"Elements with non-positive/nonfinite Gauss det(J): "
            f"{self.nonpositive_jacobian_elements}\n"
            f"Gauss points sampled: {self.sampled_gauss_points:,}\n\n"
            "Jacobian sampling uses the solver's default quadrature points. "
            "A positive sampled determinant does not guarantee an untangled "
            "curved element between all points. Refine the mesh and check "
            "force balance and convergence independently."
        )


def mesh_quality_report(mesh: Mesh, *, batch_size: int = 2048) -> MeshQualityReport:
    """Inspect T3/T6/Q4/Q8 blocks, including midside-node mapping defects.

    Determinants are in squared model-length units. No arbitrary physical
    tolerance is applied: zero, negative and nonfinite det(J) are invalid.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    areas: list[float] = []
    aspects: list[float] = []
    inverted = 0
    gp_invalid = 0
    gp_count = 0
    minimum_j = np.inf
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

        element = kernel(block.etype)
        _, derivatives = element.shape(element.rule().points)
        number_gp = derivatives.shape[0]
        for start in range(0, block.ne, batch_size):
            conn = block.conn[start : start + batch_size]
            coords = mesh.coords[conn]
            jac = np.einsum("gni,enj->egij", derivatives, coords, optimize=True)
            det = jac[..., 0, 0] * jac[..., 1, 1] - jac[..., 0, 1] * jac[..., 1, 0]
            invalid = ~np.isfinite(det) | (det <= 0)
            gp_invalid += int(np.count_nonzero(np.any(invalid, axis=1)))
            gp_count += len(conn) * number_gp
            if det.size:
                finite = det[np.isfinite(det)]
                minimum_j = min(minimum_j, float(finite.min()) if finite.size else -np.inf)
    if not areas:
        return MeshQualityReport(0, 0.0, 0.0, 0.0, 0, 0)
    magnitude = np.abs(np.asarray(areas, dtype=float))
    finite_magnitude = magnitude[np.isfinite(magnitude)]
    median = float(np.median(finite_magnitude)) if finite_magnitude.size else 0.0
    tiny = np.count_nonzero(magnitude < 0.01 * median)
    return MeshQualityReport(
        elements=len(areas),
        minimum_area=float(np.min(magnitude)),
        median_area=median,
        maximum_aspect=float(np.max(aspects)),
        inverted_or_degenerate=inverted,
        tiny_elements=int(tiny),
        minimum_jacobian=float(minimum_j),
        nonpositive_jacobian_elements=gp_invalid,
        sampled_gauss_points=gp_count,
    )

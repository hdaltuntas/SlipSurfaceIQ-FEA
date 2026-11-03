"""Exact straight-sided element area split by a horizontal water table.

F7 geometry-only reference. Clipping operates on physical corner coordinates,
not Gauss-point classification and not the solver's nodal pore forces.
Curved quadratic elements must be rejected rather than silently linearized.
"""

from __future__ import annotations

import numpy as np

from slipsurface.fe2d.core.enums import ElemType


def polygon_area(points):
    """Unsigned shoelace area of a simple straight-sided polygon."""
    xy = np.asarray(points, dtype=float)
    if xy.ndim != 2 or xy.shape[1] != 2 or len(xy) < 3:
        raise ValueError("Polygon requires at least three two-dimensional vertices")
    if not np.isfinite(xy).all():
        raise ValueError("Polygon vertices must be finite")
    return 0.5 * abs(float(
        np.dot(xy[:, 0], np.roll(xy[:, 1], -1))
        - np.dot(xy[:, 1], np.roll(xy[:, 0], -1))
    ))


def area_below_horizontal_head(points, head):
    """Clip polygon to y <= head; return exact saturated plan area [m²]."""
    vertices = np.asarray(points, dtype=float)
    if not np.isfinite(head):
        raise ValueError("Water head must be finite")
    _ = polygon_area(vertices)
    clipped = []
    for previous, current in zip(np.roll(vertices, 1, axis=0), vertices):
        prev_wet = previous[1] <= head
        curr_wet = current[1] <= head
        if prev_wet != curr_wet:
            fraction = (head - previous[1]) / (current[1] - previous[1])
            clipped.append(previous + fraction * (current - previous))
        if curr_wet:
            clipped.append(current)
    if len(clipped) < 3:
        return 0.0
    return polygon_area(np.asarray(clipped))


def mesh_element_water_areas(mesh, head):
    """Return per-block (dry areas, saturated areas), rejecting curved sides."""
    results = {}
    for block in mesh.continuum_blocks():
        ncorner = 3 if block.etype in (ElemType.T3, ElemType.T6) else 4
        corners = mesh.coords[block.conn[:, :ncorner]]
        if block.etype in (ElemType.T6, ElemType.Q8):
            mid = mesh.coords[block.conn[:, ncorner:]]
            expected = 0.5 * (
                corners + np.roll(corners, -1, axis=1)
            )
            if not np.allclose(mid, expected, rtol=0, atol=1e-9):
                raise ValueError("Curved quadratic elements cannot use polygon clipping")
        total = np.array([polygon_area(p) for p in corners])
        if not np.isfinite(total).all() or np.any(total <= 0):
            raise ValueError("Mesh contains nonpositive polygon area")
        wet = np.array([
            area_below_horizontal_head(p, head) for p in corners
        ])
        dry = total - wet
        if np.any(dry < -1e-9) or np.any(wet > total + 1e-9):
            raise ValueError("Clipping area conservation failed")
        results[block.tag] = (np.maximum(dry, 0), wet)
    return results

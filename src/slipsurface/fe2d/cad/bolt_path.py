"""Arc-length picking on CAD boundaries; no mesh or screen coordinates required."""

import numpy as np


def boundary_path(entity):
    points = np.asarray(entity.points, dtype=float)
    if entity.kind != "line":
        points = np.vstack((points, points[0]))
    lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    return points, np.r_[0.0, np.cumsum(lengths)]


def project_boundary(entity, point):
    """Nearest station and distance, including points inside individual edges."""
    points, stations = boundary_path(entity)
    directions = np.diff(points, axis=0)
    length2 = np.sum(directions**2, axis=1)
    fractions = np.clip(
        np.sum((point - points[:-1]) * directions, axis=1) / np.maximum(length2, 1e-30),
        0, 1,
    )
    distances = np.linalg.norm(points[:-1] + fractions[:, None] * directions - point, axis=1)
    k = int(np.argmin(distances))
    return float(stations[k] + fractions[k] * np.sqrt(length2[k])), float(distances[k])


def range_stations(entity, selected_range):
    """Validate an unwrapped range. Closed paths may cross their first vertex once."""
    points, stations = boundary_path(entity)
    total = float(stations[-1])
    start, end = sorted(map(float, selected_range))
    if not np.isfinite([start, end]).all() or not 1e-9 < end - start <= total + 1e-9:
        raise ValueError("Drag along a non-zero boundary interval, at most one full perimeter.")
    closed = np.allclose(points[0], points[-1])
    if not closed and (start < -1e-9 or end > total + 1e-9):
        raise ValueError("Selected interval is outside the host line.")
    return start, end, total, closed


def selected_path(entity, selected_range):
    """Polyline for the highlighted interval, retaining corners and the closure seam."""
    start, end, total, closed = range_stations(entity, selected_range)
    points, stations = boundary_path(entity)
    knots = [start, end]
    for shift in range(int(np.floor(start / total)), int(np.floor(end / total)) + 1):
        knots.extend(s + shift * total for s in stations if start < s + shift * total < end)
    samples = np.asarray(sorted(set(knots)))
    if closed:
        samples %= total
    return np.column_stack([np.interp(samples, stations, points[:, j]) for j in (0, 1)])

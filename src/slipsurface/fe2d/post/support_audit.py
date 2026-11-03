"""F7 supported-excavation structural force profiles on a common geometric axis.

Profiles use the CAD-defined endpoints rather than mesh node numbering, which
is not invariant under remeshing. Beam end forces are sampled at actual beam
nodes; bar axial forces at element midpoints. NaN and missing support tags
are retained as failures, not treated as zero structural force.
"""

from __future__ import annotations

import numpy as np


def sample_support_profile(
    mesh, stage, tag, endpoints, *, kind="beam", count=51, signed=False
):
    """Sample structural forces on a fixed 0..1 support-length coordinate.

    signed=True preserves the solver's local N/V/M signs; beam elements must
    all point along the CAD line. Reversed beams are rejected rather than
    silently applying an unverified transformation to their local sections.
    """
    if not isinstance(signed, bool):
        raise ValueError("signed must be boolean")
    if count < 2:
        raise ValueError("At least two profile samples are required.")
    start, end = np.asarray(endpoints, dtype=float)
    direction = end - start
    length2 = float(direction @ direction)
    if length2 <= 0 or not np.isfinite(length2):
        raise ValueError("Support endpoints must be distinct and finite.")
    sources = stage.beams if kind == "beam" else stage.bars if kind == "bar" else None
    if sources is None:
        raise ValueError("kind must be beam or bar")
    if tag not in sources:
        raise KeyError(f"Missing active {kind} support: {tag}")
    block = mesh.block(tag)
    connectivity = block.conn[:, :2]
    coords = mesh.coords[connectivity]
    values = np.asarray(sources[tag], dtype=float)
    if kind == "beam":
        if signed:
            element_vectors = coords[:, 1] - coords[:, 0]
            projection = element_vectors @ direction
            if not np.all(np.isfinite(projection)) or np.any(projection <= 0):
                raise ValueError(
                    f"{tag}: signed beam profiles require consistent CAD orientation"
                )
        if values.shape != (block.ne, 2, 3):
            raise ValueError(f"{tag}: beam force shape does not match mesh")
        # Project both end sections; the vector contains N, V and M.
        positions = coords.reshape(-1, 2)
        forces = values.reshape(-1, 3)
    else:
        if values.shape != (block.ne,):
            raise ValueError(f"{tag}: bar force shape does not match mesh")
        positions = coords.mean(axis=1)
        forces = values[:, None]
    projected = ((positions - start) @ direction) / length2
    if not np.isfinite(forces).all() or not np.isfinite(projected).all():
        raise ValueError(f"{tag}: nonfinite support forces or geometry")
    if np.any(projected < -1e-6) or np.any(projected > 1 + 1e-6):
        raise ValueError(f"{tag}: elements lie outside CAD endpoints")
    projected = np.clip(projected, 0.0, 1.0)
    order = np.argsort(projected)
    projected = projected[order]
    forces = forces[order]
    # Duplicate beam end stations share a position. Average the two element
    # end force magnitudes to avoid arbitrary mesh ordering.
    stations, inverse = np.unique(projected, return_inverse=True)
    if len(stations) < 2:
        raise ValueError(f"{tag}: insufficient distinct force stations")
    sampled = forces if signed else np.abs(forces)
    sums = np.zeros((len(stations), sampled.shape[1]))
    np.add.at(sums, inverse, sampled)
    counts = np.bincount(inverse)
    section = sums / counts[:, None]
    target = np.linspace(0.0, 1.0, count)
    interpolated = np.column_stack([
        np.interp(target, stations, section[:, i]) for i in range(section.shape[1])
    ])
    return {
        "tag": tag, "kind": kind,
        "mode": "signed_local" if signed else "magnitude",
        "s": target.tolist(), "components": interpolated.tolist(),
    }


def compare_profiles(before, after):
    """Normalized RMS differences on matching support tags and sampling stations."""
    if before["tag"] != after["tag"] or before["kind"] != after["kind"]:
        raise ValueError("Cannot compare different support identities")
    if before.get("mode", "magnitude") != after.get("mode", "magnitude"):
        raise ValueError("Cannot compare signed and magnitude support profiles")
    x0, x1 = np.asarray(before["s"]), np.asarray(after["s"])
    a, b = np.asarray(before["components"]), np.asarray(after["components"])
    if a.shape != b.shape or not np.array_equal(x0, x1):
        raise ValueError("Support profiles require identical sampling stations")
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("Nonfinite support distribution")
    diff = np.sqrt(np.mean((a - b) ** 2, axis=0))
    scales = np.maximum(
        np.maximum(np.sqrt(np.mean(a * a, axis=0)),
                   np.sqrt(np.mean(b * b, axis=0))),
        1e-12,
    )
    return (diff / scales).tolist()

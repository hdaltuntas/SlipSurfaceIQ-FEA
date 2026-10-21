"""Stage-aware point/line queries and oriented beam diagrams, independent of Qt."""

from dataclasses import dataclass

import numpy as np

from ..core.enums import ElemType
from ..fem.elements import kernel
from .recovery import element_nodal_values, principal_stresses
from .result_fields import stage_result


@dataclass
class LineProfile:
    distance: np.ndarray
    xy: np.ndarray
    values: np.ndarray
    regions: np.ndarray
    field: str
    unit: str


def field_unit(field):
    return "m" if field in ("|u|", "ux", "uy") else "kPa"


def _local_point(element, coords, point):
    """Invert the actual isoparametric map, not a triangulation across holes."""
    triangular = element.nen in (3, 6)
    xi = np.array([1 / 3, 1 / 3] if triangular else [0.0, 0.0])
    scale = max(float(np.ptp(coords, axis=0).max()), 1.0)
    for _ in range(20):
        N, dN = element.shape(xi[None])
        residual = N[0] @ coords - point
        if np.linalg.norm(residual) <= 1e-10 * scale:
            inside = (
                (np.min(xi) >= -1e-9 and xi.sum() <= 1 + 1e-9)
                if triangular
                else np.max(np.abs(xi)) <= 1 + 1e-9
            )
            return N[0] if inside else None
        try:
            xi -= np.linalg.solve(coords.T @ dN[0], residual)
        except np.linalg.LinAlgError:
            return None
        if np.linalg.norm(xi) > 10:
            return None
    return None


def line_profile(result, start, end, field="|u|", count=101, stage=None, region=None):
    """Query active elements only; gaps are NaN. Boundary ties use the first element.

    Displacements use the element shape functions. Stress/pore fields use element-local
    GP extrapolation, preserving jumps between regions and opposite interface faces.
    ``region`` optionally selects one side of a material boundary.
    """
    a, b = np.asarray(start, float), np.asarray(end, float)
    if (
        a.shape != (2,)
        or b.shape != (2,)
        or not np.isfinite([a, b]).all()
        or np.linalg.norm(b - a) <= 1e-12
        or not 2 <= count <= 10001
    ):
        raise ValueError("Need two distinct finite points and 2–10001 samples")
    if field not in {
        "|u|",
        "ux",
        "uy",
        "sxx",
        "syy",
        "szz",
        "txy",
        "s1",
        "s2",
        "s3",
        "q",
        "pore",
        "excess_pore",
    }:
        raise ValueError(f"Unknown query field: {field}")
    st = stage_result(result, stage)
    mesh = result.model.mesh
    xy = np.linspace(a, b, count)
    values, regions = np.full(count, np.nan), np.full(count, -1, dtype=int)
    for block in mesh.continuum_blocks():
        active = st.active.get(block.tag, np.ones(block.ne, bool)).copy()
        if region is not None:
            active &= block.region == region
        element = kernel(block.etype)
        nodal = None
        if field not in {"|u|", "ux", "uy"}:
            raw = (
                getattr(st, field).get(block.tag)
                if field in {"pore", "excess_pore"}
                else st.sig.get(block.tag)
            )
            if raw is None:
                continue
            nodal = element_nodal_values(block, raw[..., None] if raw.ndim == 2 else raw)
        for e in np.flatnonzero(active):
            X = mesh.coords[block.conn[e]]
            candidates = np.flatnonzero(
                (regions < 0) & (xy >= X.min(0) - 1e-9).all(1) & (xy <= X.max(0) + 1e-9).all(1)
            )
            for i in candidates:
                weights = _local_point(element, X, xy[i])
                if weights is None:
                    continue
                if nodal is None:
                    u = weights @ st.u[block.conn[e]]
                    v = np.linalg.norm(u) if field == "|u|" else u[0 if field == "ux" else 1]
                else:
                    v = weights @ nodal[e]
                    if field in {"sxx", "syy", "szz", "txy"}:
                        v = v[("sxx", "syy", "szz", "txy").index(field)]
                    elif field in {"pore", "excess_pore"}:
                        v = v[0]
                    else:
                        v = principal_stresses(v)[field]
                values[i], regions[i] = v, block.region[e]
    return LineProfile(
        np.linspace(0, np.linalg.norm(b - a), count), xy, values, regions, field, field_unit(field)
    )


@dataclass
class BeamPath:
    elements: np.ndarray
    nodes: np.ndarray  # (ne, 2) traversal order
    distance: np.ndarray  # (ne, 2); endpoints deliberately not averaged
    forces: np.ndarray  # (ne, 2, 3), transformed to traversal direction


def beam_paths(result, tag, stage=None):
    """Order active beam chains/rings. Branches stop a path rather than inventing continuity.

    Local x follows traversal, local y is 90° CCW. N tension positive. For a reversed
    element the end order reverses and M changes sign; N and V keep their section signs.
    At start the values are minus local nodal actions; at end plus local nodal actions.
    """
    st = stage_result(result, stage)
    block = result.model.mesh.block(tag)
    if block.etype is not ElemType.BEAM2:
        raise ValueError("A beam block is required")
    ids = np.flatnonzero(st.active.get(tag, np.ones(block.ne, bool)))
    if tag not in st.beams:
        return []
    adjacency = {}
    for e in ids:
        for node in block.conn[e]:
            adjacency.setdefault(int(node), []).append(int(e))
    remaining = set(map(int, ids))
    paths = []
    while remaining:
        terminal = sorted(
            n for n, es in adjacency.items() if len(es) != 2 and any(e in remaining for e in es)
        )
        node = terminal[0] if terminal else int(min(block.conn[list(remaining)].ravel()))
        elements, pairs, positions, forces = [], [], [], []
        distance = 0.0
        while True:
            candidates = sorted(e for e in adjacency[node] if e in remaining)
            if not candidates:
                break
            e = candidates[0]
            remaining.remove(e)
            a, b = map(int, block.conn[e])
            reverse = node == b
            other = a if reverse else b
            f = st.beams[tag][e].copy()
            if reverse:
                f = f[::-1] * [1, 1, -1]
            length = np.linalg.norm(
                result.model.mesh.coords[other] - result.model.mesh.coords[node]
            )
            elements.append(e)
            pairs.append((node, other))
            positions.append((distance, distance + length))
            forces.append(f)
            distance += length
            node = other
            if len(adjacency[node]) != 2:
                break
        paths.append(
            BeamPath(np.array(elements), np.array(pairs), np.array(positions), np.array(forces))
        )
    return paths

"""Solver-quadrature resultants of STORED dry normal-contact tractions.

Actions on the bodies are the negative of the element's assembled internal
force contributions. All moments use original mesh coordinates and one explicit
origin. This is post-processing, not an independent external equilibrium check.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real

import numpy as np

from ..core.enums import Analysis, ElemType
from .contact_results import contact_points, normal_contact_tags
from .result_fields import stage_result


@dataclass(frozen=True)
class FaceAction:
    """Contact action on one face: kN/m, kN/m and kN*m/m; counter-clockwise M+."""

    fx: float
    fy: float
    moment: float


@dataclass(frozen=True)
class ContactResultant:
    tag: str
    origin_m: tuple[float, float]
    availability: str  # available, active_subset, inactive or unavailable
    element_count: int
    active_elements: int
    available_points: int
    unavailable_points: int
    inactive_points: int
    total_length_m: float
    active_length_m: float
    pressure_integral: float | None  # sum(w*p), not the norm of a vector sum
    face1: FaceAction | None
    face2: FaceAction | None


def moment_origin(origin):
    """Require two finite real coordinates; reject bools and numeric strings."""
    try:
        values = tuple(origin)
    except TypeError as exc:
        raise ValueError("Moment origin requires two finite real coordinates") from exc
    if len(values) != 2 or any(isinstance(x, (bool, np.bool_)) or not isinstance(x, Real)
                               or not math.isfinite(x) for x in values):
        raise ValueError("Moment origin requires two finite real coordinates")
    return float(values[0]), float(values[1])


def _geometry(mesh, block):
    """Independent fixed-normal quadrature, matching straight IFACE4/6 contracts.

    Do not call the native contact group or read its weights/forces. IFACE6
    order is endpoint, endpoint, midpoint, with weights L/6, L/6, 2L/3.
    """
    if block.etype not in (ElemType.IFACE4, ElemType.IFACE6) or block.ne < 1:
        raise ValueError("Require a nonempty straight IFACE4/IFACE6 contact block")
    n = block.etype.nen // 2
    xy, conn = np.asarray(mesh.coords), np.asarray(block.conn)
    if (xy.ndim != 2 or xy.shape[1] != 2 or xy.dtype.kind not in "fiu"
            or conn.shape != (block.ne, 2*n) or conn.dtype.kind not in "iu"
            or np.any(conn < 0) or np.any(conn >= len(xy))):
        raise ValueError(f"{block.tag}: invalid contact geometry/connectivity")
    first, second = xy[conn[:, :n]].astype(float), xy[conn[:, n:]].astype(float)
    if not np.isfinite(first).all() or not np.isfinite(second).all():
        raise ValueError(f"{block.tag}: nonfinite contact coordinates")
    with np.errstate(over="raise", invalid="raise", divide="raise"):
        vector = first[:, 1] - first[:, 0]
        length = np.hypot(vector[:, 0], vector[:, 1])
        if not np.isfinite(length).all() or np.any(length <= 0):
            raise ValueError(f"{block.tag}: degenerate contact face")
        tolerance = 1e-12 * np.maximum(length, 1.0)
        if np.any(np.max(np.abs(first-second), axis=(1, 2)) > tolerance):
            raise ValueError(f"{block.tag}: reference contact faces must coincide")
        if n == 3 and np.any(np.max(np.abs(first[:, 2] - (first[:, 0] + vector/2)), axis=1)
                             > tolerance):
            raise ValueError(f"{block.tag}: IFACE6 requires a centred straight midpoint")
        direction = vector / length[:, None]
        normal = np.column_stack([-direction[:, 1], direction[:, 0]])
        weights = length[:, None] * np.array([0.5, 0.5] if n == 2 else [1/6, 1/6, 2/3])
    return first, second, normal, weights, length


def _sum(values):
    value = math.fsum(float(v) for v in values)
    if not math.isfinite(value):
        raise ValueError("Nonfinite contact resultant")
    return value


def _action(forces, positions, origin):
    moments = (positions[:, 0]-origin[0])*forces[:, 1] - (
        positions[:, 1]-origin[1])*forces[:, 0]
    return FaceAction(_sum(forces[:, 0]), _sum(forces[:, 1]), _sum(moments))


def contact_resultants(result, stage=None, tag=None, *, origin=(0.0, 0.0)):
    """One separate resultant per interface; never cancel distinct faces/tags away.

    Active/inactive topology comes from the stored activity mask. Only fully
    available active data are summed. Missing active evidence makes the entire
    interface unavailable, not a partial zero. Wholly inactive totals are blank.
    An active_subset explicitly denotes integration over active elements only.
    """
    origin = moment_origin(origin)
    if result.model.analysis is not Analysis.PLANE_STRAIN:
        raise ValueError("Contact resultants support plane strain only")
    keys = normal_contact_tags(result.model)
    if tag is not None:
        if tag not in keys:
            raise ValueError(f"{tag}: not a declared unilateral normal-contact interface")
        keys = (tag,)
    snapshot = stage_result(result, stage)
    summaries = []
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            for key in keys:
                block = result.model.mesh.block(key)
                first, second, normal, weights, lengths = _geometry(result.model.mesh, block)
                points = contact_points(result, snapshot, key)
                active = snapshot.active[key]
                available = sum(p.availability == "available" for p in points)
                missing = sum(p.availability == "unavailable" for p in points)
                inactive = sum(not p.active for p in points)
                integral = face1 = face2 = None
                if not active.any():
                    status = "inactive"
                elif missing:
                    status = "unavailable"
                else:
                    status = "available" if active.all() else "active_subset"
                    pressure = np.array([p.pressure_kpa for p in points if p.active])
                    selected_weights = weights[active].ravel()
                    contribution = pressure * selected_weights
                    normals = np.repeat(normal[active], weights.shape[1], axis=0)
                    # p = -stored sigma_n. Action on face 2 is +p*n; native f_int is -p*n.
                    on_two = contribution[:, None] * normals
                    face1 = _action(-on_two, first[active].reshape(-1, 2), origin)
                    face2 = _action(on_two, second[active].reshape(-1, 2), origin)
                    integral = _sum(contribution)
                summaries.append(ContactResultant(
                    key, origin, status, block.ne, int(active.sum()), available, missing,
                    inactive, _sum(lengths), _sum(lengths[active]), integral, face1, face2,
                ))
    except (FloatingPointError, OverflowError) as exc:
        raise ValueError("Contact resultant arithmetic overflow") from exc
    return tuple(summaries)

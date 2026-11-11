"""Read stored normal-contact integration-point results without recovering a new gap.

Display datum resets, remeshing and missing snapshots must never be interpreted
as a geometric contact measurement. Values come only from accepted result maps.
Point/face identities remain distinct; no nodal averaging or interpolation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from ..core.enums import ElemType
from .result_fields import stage_result

CONTACT_FIELDS = ("contact_gap", "contact_pressure", "contact_status")
CONTACT_STATUS_NAMES = {0: "OPEN", 1: "TOUCHING", 2: "COMPRESSED", 255: "INACTIVE"}


@dataclass(frozen=True)
class ContactPoint:
    tag: str
    element: int
    point: int
    face1_node: int
    face2_node: int
    x_m: float
    y_m: float
    active: bool
    availability: str
    gap_m: float | None = None
    normal_traction_kpa: float | None = None
    status_code: int | None = None

    @property
    def status(self):
        return CONTACT_STATUS_NAMES.get(self.status_code, "UNAVAILABLE")

    @property
    def pressure_kpa(self):
        """Compression-positive presentation; stored normal traction is tension positive."""
        return None if self.normal_traction_kpa is None else -self.normal_traction_kpa

    def display_value(self, field):
        if field not in CONTACT_FIELDS:
            raise ValueError(f"Unknown contact field: {field}")
        if self.availability != "available":
            return None
        return (self.gap_m * 1000.0 if field == "contact_gap" else
                self.pressure_kpa if field == "contact_pressure" else self.status_code)


def normal_contact_tags(model):
    return tuple(tag for tag, spec in model.interfaces.items()
                 if getattr(spec, "law", "goodman") == "unilateral_normal")


def _array(value, shape, name, kinds="fiu"):
    data = np.asarray(value)
    if data.shape != shape or data.dtype.kind not in kinds:
        raise ValueError(f"{name}: invalid result shape or numeric type; expected {shape}")
    return data


def contact_points(result, stage=None, tag=None, *, checkpoint=None):
    """Stored IFACE4/IFACE6 point data for one stage, including inactive/missing rows.

    Missing optional contact maps (old snapshots) are unavailable, not zero.
    Present but malformed/inconsistent data raise ValueError before export/drawing.
    An optional synchronous checkpoint supports audit cancellation; it never
    changes the returned measurements and its exceptions propagate unchanged.
    Inactive masks remain authoritative and require NaN/255 when maps are present.
    """
    if checkpoint is not None:
        if not callable(checkpoint):
            raise TypeError("checkpoint must be callable or None")
        checkpoint()
    st = stage_result(result, stage)
    tags = normal_contact_tags(result.model)
    if tag is not None:
        if tag not in tags:
            raise ValueError(f"{tag}: not a declared unilateral normal-contact interface")
        tags = (tag,)
    points = []
    for key in tags:
        if checkpoint is not None:
            checkpoint()
        block = result.model.mesh.block(key)
        if block.etype not in (ElemType.IFACE4, ElemType.IFACE6):
            raise ValueError(f"{key}: normal-contact results require IFACE4 or IFACE6")
        n = block.etype.nen // 2
        shape = (block.ne, n)
        mask = _array(st.active.get(key), (block.ne,), f"{key} activity", kinds="b")
        maps = [getattr(st, name, {}) for name in ("contact_gap", "contact_status", "interfaces")]
        if any(not isinstance(item, Mapping) for item in maps):
            raise ValueError(f"{key}: malformed contact result maps")
        present = [key in item for item in maps]
        gap = code = traction = None
        if present[0]:
            gap = _array(maps[0][key], shape, f"{key} gap")
            if not np.isfinite(gap[mask]).all() or not np.isnan(gap[~mask]).all():
                raise ValueError(f"{key}: invalid active/inactive contact gaps")
        if present[1]:
            code = _array(maps[1][key], shape, f"{key} contact status", kinds="iu")
            if not np.isin(code[mask], (0, 1, 2)).all() or np.any(code[~mask] != 255):
                raise ValueError(f"{key}: invalid active/inactive contact status")
        if present[2]:
            traction = _array(maps[2][key], (*shape, 2), f"{key} traction")
            if (not np.isfinite(traction[mask]).all() or not np.isnan(traction[~mask]).all()
                    or np.any(traction[mask, :, 0] != 0) or np.any(traction[mask, :, 1] > 0)):
                raise ValueError(f"{key}: invalid frictionless normal-contact tractions")
        available = all(present)
        if available:
            expected = np.where(gap[mask] < 0, 2, np.where(gap[mask] > 0, 0, 1))
            if not np.array_equal(code[mask], expected):
                raise ValueError(f"{key}: contact state contradicts stored gap")
            if np.any(traction[..., 1][mask][gap[mask] >= 0] != 0):
                raise ValueError(f"{key}: open/touching contact carries a nonzero traction")
        for e, conn in enumerate(block.conn):
            if checkpoint is not None and e % 256 == 0:
                checkpoint()
            for ip in range(n):
                one, two = int(conn[ip]), int(conn[n + ip])
                xy = result.model.mesh.coords[one]
                if not np.isfinite(xy).all():
                    raise ValueError(f"{key}: nonfinite contact point coordinates")
                active = bool(mask[e])
                state = "inactive" if not active else "available" if available else "unavailable"
                points.append(ContactPoint(
                    key, e, ip, one, two, float(xy[0]), float(xy[1]), active, state,
                    float(gap[e, ip]) if active and available else None,
                    float(traction[e, ip, 1]) if active and available else None,
                    int(code[e, ip]) if active and available else 255 if not active else None,
                ))
    if checkpoint is not None:
        checkpoint()
    return tuple(points)

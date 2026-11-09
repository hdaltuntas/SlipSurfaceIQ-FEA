"""Ordered accepted snapshots of one contact point, never a recovered time history."""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Integral, Real

from .contact_results import ContactPoint, contact_points, normal_contact_tags


@dataclass(frozen=True)
class ContactHistorySample:
    stage_index: int  # 0 is initial; 1..N follow stored stage order, not time or lambda
    stage_name: str
    load_factor: float
    contact: ContactPoint


def contact_point_history(result, tag, element, point):
    """Return initial + accepted stages for a single unchanged mesh-point identity.

    Validate every snapshot before returning any data. Missing optional maps and
    inactive points remain explicit records with no numerical measurements.
    Duplicate stage names are allowed: the stored index is the identity.
    """
    if tag not in normal_contact_tags(result.model):
        raise ValueError(f"{tag}: not a declared unilateral normal-contact interface")
    block = result.model.mesh.block(tag)
    for value, size, label in ((element, block.ne, "element"),
                                (point, block.etype.nen // 2, "point")):
        if isinstance(value, bool) or not isinstance(value, Integral) or not 0 <= value < size:
            raise ValueError(f"Invalid contact {label} index")
    history = []
    for index, stage in enumerate([result.initial, *result.stages]):
        factor = stage.lam
        if (isinstance(factor, bool) or not isinstance(factor, Real)
                or not math.isfinite(factor) or not 0 <= factor <= 1):
            raise ValueError(f"Stage {index}: invalid accepted load factor")
        if not isinstance(stage.name, str):
            raise ValueError(f"Stage {index}: invalid stage name")
        points = contact_points(result, stage, tag)
        selected = [p for p in points if p.element == element and p.point == point]
        if len(selected) != 1:
            raise ValueError(f"Stage {index}: missing or duplicate contact point identity")
        # Also check display-unit conversion: finite metres can overflow in mm.
        for field in ("contact_gap", "contact_pressure"):
            value = selected[0].display_value(field)
            if value is not None and not math.isfinite(value):
                raise ValueError(f"Stage {index}: nonfinite displayed contact measurement")
        history.append(ContactHistorySample(index, stage.name, float(factor), selected[0]))
    return tuple(history)


def contact_history_segments(history, field):
    """Display-only polylines; never bridge missing/inactive snapshots or plot states.

    Joining adjacent stored samples is a visual guide, not an interpolated
    constitutive path. Gap is in mm, pressure compression-positive kPa.
    """
    if field not in ("contact_gap", "contact_pressure"):
        raise ValueError("History plots support gap or pressure, not categorical states")
    segments, current = [], []
    for sample in history:
        value = sample.contact.display_value(field)
        if value is None:
            if current:
                segments.append(tuple(current))
                current = []
        else:
            current.append((sample.stage_index, value))
    if current:
        segments.append(tuple(current))
    return tuple(segments)

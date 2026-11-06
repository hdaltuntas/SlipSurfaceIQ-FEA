"""Qt-independent, transactional interface-law authoring for desktop forms."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import replace

from ..model.materials import InterfaceSpec

GOODMAN_FIELDS = ("kn", "ks", "c", "phi", "psi", "sig_t")
NORMAL_FIELDS = ("kn", "initial_gap")


def interface_spec_from_fields(name, law, fields: Mapping, *, original=None):
    """Parse only the selected law's fields; switching law must be explicit.

    Disabled UI values stay in the form for toggling back, but cannot leak
    friction/cohesion into normal contact or geometric clearance into Goodman.
    Existing dataclass fields not owned by this form are preserved with replace.
    """
    if law not in ("goodman", "unilateral_normal"):
        raise ValueError("Select a known interface law.")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Interface name must not be empty.")
    if original is not None and not isinstance(original, InterfaceSpec):
        raise ValueError("Invalid original interface properties.")
    active = NORMAL_FIELDS if law == "unilateral_normal" else GOODMAN_FIELDS
    values = {key: 0.0 for key in (*GOODMAN_FIELDS, "initial_gap")}
    for key in active:
        raw = fields.get(key)
        if isinstance(raw, bool):
            raise ValueError(f"{key} must be a finite number, not a boolean.")
        try:
            value = float(raw)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{key} must be a finite number.") from exc
        if not math.isfinite(value):
            raise ValueError(f"{key} must be a finite number.")
        values[key] = value
    parameters = dict(name=name.strip(), law=law, **values)
    return (replace(original, **parameters) if original is not None
            else InterfaceSpec(**parameters))


def apply_interface_spec(model, spec, *, tag=None, edge_set=None, side="left"):
    """Return a validated new model; never repair settings or mutate the source.

    Reuse the native Model contract for dry/drained/NR/initial-state limits.
    Validate the actual interface geometry before accepting normal-contact edits.
    This is a preflight check, not a proof of global constraint sufficiency.
    """
    # Geometry editing has optional CAD dependencies; parsing does not.
    from ..fem.unilateral_contact import StagedNormalContactGroup
    from .editing import put_interface, validate_edit

    if not isinstance(spec, InterfaceSpec):
        raise ValueError("Expected interface properties.")
    if tag is None:
        candidate = put_interface(model, spec, edge_set, side)
        key = spec.name
    else:
        if tag not in model.interfaces:
            raise ValueError("The selected interface no longer exists.")
        candidate = validate_edit(replace(
            model, interfaces={**model.interfaces, tag: spec},
        ))
        key = tag
    if spec.law == "unilateral_normal":
        StagedNormalContactGroup(candidate.mesh.block(key), candidate.mesh.coords,
                                 spec, candidate.analysis)
    return candidate
